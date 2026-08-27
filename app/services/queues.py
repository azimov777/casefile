"""Сценарии по очередям: создание, настройка, архивация, выдача номеров задач.

Очередь владеет процессом, поэтому здесь же собирается её конфигурация целиком —
типы задач, статусы, резолюции и поля одним вызовом. Этот сценарий — основной источник
данных для формы создания задачи во фронтенде и для агента, который только что
подключился к незнакомой очереди.

Зависимость на справочники и на реестр полей односторонняя: очереди знают про них, они
про очереди — нет. Поэтому разрешение ссылок вида `TRK.open` и `TRK.severity` живёт
здесь: чтобы найти объект по ссылке, надо сначала найти очередь, а это дело сценариев
очередей.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.field import Field
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import CatalogRepository, QueueRepository
from app.domain.catalogs import (
    DEFAULT_ISSUE_TYPE_KEY,
    DEFAULT_STATUS_KEY,
    CatalogKind,
    parse_catalog_ref,
)
from app.domain.errors import (
    ActorInactiveError,
    CatalogEntryUnavailableError,
    QueueArchivedError,
    QueueKeyTakenError,
    QueueNotEmptyError,
    QueueNotFoundError,
)
from app.domain.fields import parse_field_ref
from app.domain.queues import format_issue_key, validate_queue_key
from app.services import catalogs as catalogs_service
from app.services import fields as fields_service
from app.services import issue_usage
from app.services.permissions import ensure_allowed


@dataclass(frozen=True, slots=True)
class QueueConfig:
    """Конфигурация очереди целиком: всё, что нужно, чтобы завести в ней задачу.

    Собирается одним сценарием намеренно. Фронтенду для формы создания задачи и агенту
    для первого знакомства с очередью нужен один запрос, а не четыре: иначе каждый
    клиент соберёт свой набор вызовов и получит слегка разное представление о процессе.

    В набор входят только активные записи: конфигурация отвечает на вопрос «чем можно
    пользоваться сейчас», а не «что когда-либо заводили». Скрытые поля по той же
    причине в конфигурацию не попадают.
    """

    queue: Queue
    issue_types: list[IssueType]
    statuses: list[Status]
    resolutions: list[Resolution]
    fields: list[Field]


async def get_queue_by_key(session: AsyncSession, key: str) -> Queue:
    """Очередь по ключу или `queue_not_found`. Прав не проверяет: точка входа — `read_queue`."""
    queue = await QueueRepository(session).get_by_key(validate_queue_key(key))
    if queue is None:
        raise QueueNotFoundError(details={"key": key})
    return queue


async def resolve_scope(session: AsyncSession, queue_key: str | None) -> Queue | None:
    """Область справочника по ключу очереди: `None` — глобальная."""
    if queue_key is None:
        return None
    return await get_queue_by_key(session, queue_key)


async def resolve_catalog_ref(
    session: AsyncSession,
    kind: CatalogKind,
    ref: str,
    *,
    initiator: Actor,
) -> Status | IssueType | Resolution:
    """Находит запись справочника по ссылке `open` или `TRK.open`.

    Живёт в сценариях очередей, а не справочников: ссылка на локальную запись содержит
    ключ очереди, и разрешить его умеет только тот, кто знает про очереди. Обратная
    зависимость замкнула бы два модуля в цикл.

    Проверка прав здесь, а не у вызывающего: разрешить ссылку — значит прочитать
    справочник, и отдельного «неохраняемого» разрешения быть не должно. Сценарии,
    которые потом что-то меняют, проверяют своё действие дополнительно.
    """
    ensure_allowed(initiator, f"{kind.value}.read")
    parsed = parse_catalog_ref(ref, kind=kind)
    queue = await resolve_scope(session, parsed.queue_key)
    return await catalogs_service.get_entry(session, kind, key=parsed.key, queue=queue)


async def resolve_field_ref(
    session: AsyncSession,
    ref: str,
    *,
    initiator: Actor,
) -> Field:
    """Находит поле по ссылке `severity` или `TRK.severity`.

    Живёт здесь по той же причине, что и `resolve_catalog_ref`: ссылка на локальный
    объект содержит ключ очереди, и разрешить его умеет только тот, кто знает про
    очереди. Обратная зависимость замкнула бы сценарии полей и очередей в цикл.

    Разбор ссылки — той же функцией, что разбирает `TRK.open`: формат один на весь
    проект, и второй разбор истолковал бы одну и ту же строку иначе.
    """
    ensure_allowed(initiator, "field.read")
    parsed = parse_field_ref(ref)
    queue = await resolve_scope(session, parsed.queue_key)
    return await fields_service.get_field(session, key=parsed.key, queue=queue)


async def read_queue(session: AsyncSession, key: str, *, initiator: Actor) -> Queue:
    ensure_allowed(initiator, "queue.read")
    return await get_queue_by_key(session, key)


async def list_queues(
    session: AsyncSession,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
    is_archived: bool | None = None,
    owner: Actor | None = None,
) -> Page[Queue]:
    ensure_allowed(initiator, "queue.list")
    return await QueueRepository(session).list_page(
        limit=limit,
        cursor=cursor,
        is_archived=is_archived,
        owner_id=None if owner is None else owner.id,
    )


async def create_queue(
    session: AsyncSession,
    *,
    initiator: Actor,
    key: str,
    name: str,
    description: str = "",
    owner: Actor | None = None,
    issue_type_refs: list[str] | None = None,
    default_issue_type_ref: str | None = None,
    default_status_ref: str | None = None,
) -> Queue:
    """Создаёт очередь с рабочей конфигурацией.

    Не переданное берётся из глобальных справочников: все активные типы задач
    разрешаются в очереди, значениями по умолчанию становятся `task` и `open`, если
    они существуют, иначе — первые по времени создания. Очередь без единого типа или
    без статуса по умолчанию создать нельзя: в ней нельзя было бы завести задачу, а
    узналось бы это гораздо позже.

    Ссылки на справочники здесь могут быть только глобальными: локальных записей у
    очереди, которой ещё нет, существовать не может.
    """
    ensure_allowed(initiator, "queue.create")
    normalized_key = validate_queue_key(key)

    repository = QueueRepository(session)
    if await repository.get_by_key(normalized_key) is not None:
        raise QueueKeyTakenError(details={"key": normalized_key})

    queue_owner = owner or initiator
    if not queue_owner.is_active:
        raise ActorInactiveError(details={"key": queue_owner.key, "reason": "cannot_own_queue"})

    issue_types = await _resolve_global_issue_types(session, issue_type_refs)
    default_issue_type = await _choose_default(
        session,
        CatalogKind.ISSUE_TYPE,
        ref=default_issue_type_ref,
        available=issue_types,
        preferred_key=DEFAULT_ISSUE_TYPE_KEY,
    )
    statuses = await CatalogRepository(session, Status).list_global_active()
    default_status = await _choose_default(
        session,
        CatalogKind.STATUS,
        ref=default_status_ref,
        available=statuses,
        preferred_key=DEFAULT_STATUS_KEY,
    )

    queue = await repository.add(
        Queue(
            key=normalized_key,
            name=name.strip(),
            description=description.strip(),
            owner=queue_owner,
            default_issue_type=default_issue_type,
            default_status=default_status,
        )
    )
    for issue_type in issue_types:
        await repository.bind_issue_type(queue.id, issue_type.id)
    return queue


async def update_queue(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
    name: str | None = None,
    description: str | None = None,
    owner: Actor | None = None,
    default_issue_type_ref: str | None = None,
    default_status_ref: str | None = None,
) -> Queue:
    """Меняет настройки очереди. `None` означает «поле не передано».

    Ключ очереди не меняется никогда и в этот сценарий не приходит: на нём построены
    ключи уже заведённых задач (`TRK-123`), и смена ключа сделала бы их ссылками в
    никуда — во внешних системах, в переписке и в истории изменений.

    Архивная очередь настройки менять позволяет: иначе привести её в порядок перед
    возвратом из архива было бы нечем.
    """
    ensure_allowed(initiator, "queue.update", target=queue)

    if name is not None:
        queue.name = name.strip()
    if description is not None:
        queue.description = description.strip()
    if owner is not None:
        if not owner.is_active:
            raise ActorInactiveError(details={"key": owner.key, "reason": "cannot_own_queue"})
        queue.owner = owner
    if default_issue_type_ref is not None:
        queue.default_issue_type = await _resolve_default_issue_type(
            session, queue, default_issue_type_ref, initiator=initiator
        )
    if default_status_ref is not None:
        entry = await resolve_catalog_ref(
            session, CatalogKind.STATUS, default_status_ref, initiator=initiator
        )
        catalogs_service.ensure_available_in_queue(entry, kind=CatalogKind.STATUS, queue=queue)
        queue.default_status = entry

    await session.flush()
    return queue


async def set_issue_types(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
    refs: list[str],
) -> list[IssueType]:
    """Задаёт набор типов задач, разрешённых в очереди, целиком.

    Замена набора, а не добавление по одному: агенту и фронту проще прислать нужное
    состояние, чем вычислять разницу, а результат от порядка вызовов не зависит.

    Тип, выбранный в очереди по умолчанию, из набора убрать нельзя — сначала надо
    выбрать другой умолчательный. Иначе очередь осталась бы с настройкой, которой
    нельзя воспользоваться.
    """
    ensure_allowed(initiator, "queue.update", target=queue)
    if not refs:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.ISSUE_TYPE.value,
                "queue": queue.key,
                "reason": "at_least_one_issue_type_required",
            },
        )

    requested: list[IssueType] = []
    seen: set[str] = set()
    for ref in refs:
        entry = await resolve_catalog_ref(session, CatalogKind.ISSUE_TYPE, ref, initiator=initiator)
        catalogs_service.ensure_available_in_queue(entry, kind=CatalogKind.ISSUE_TYPE, queue=queue)
        if str(entry.id) not in seen:
            seen.add(str(entry.id))
            requested.append(entry)

    if queue.default_issue_type_id not in {entry.id for entry in requested}:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.ISSUE_TYPE.value,
                "queue": queue.key,
                "ref": catalogs_service.format_entry_ref(queue.default_issue_type),
                "reason": "default_issue_type_must_stay",
            },
        )

    repository = QueueRepository(session)
    current = await repository.list_issue_types(queue.id)
    current_ids = {entry.id for entry in current}
    requested_ids = {entry.id for entry in requested}

    await repository.unbind_issue_types(queue.id, list(current_ids - requested_ids))
    for entry in requested:
        if entry.id not in current_ids:
            await repository.bind_issue_type(queue.id, entry.id)
    return await repository.list_issue_types(queue.id)


async def archive_queue(session: AsyncSession, queue: Queue, *, initiator: Actor) -> Queue:
    """Убирает очередь в архив. Повторный вызов ничего не меняет и ошибкой не считается.

    Архивация — замена удалению: задачи, ключи и история остаются на месте, но новых
    задач в очереди не заводят. Идемпотентность здесь по той же причине, что и у
    отзыва токена: клиент, не получивший ответ и повторивший запрос, не должен
    получать ошибку на выполненное действие.
    """
    ensure_allowed(initiator, "queue.archive", target=queue)
    if not queue.is_archived:
        queue.is_archived = True
        queue.archived_at = datetime.now(UTC)
        await session.flush()
    return queue


async def unarchive_queue(session: AsyncSession, queue: Queue, *, initiator: Actor) -> Queue:
    """Возвращает очередь из архива. Тоже идемпотентно."""
    ensure_allowed(initiator, "queue.archive", target=queue)
    if queue.is_archived:
        queue.is_archived = False
        queue.archived_at = None
        await session.flush()
    return queue


async def delete_queue(session: AsyncSession, queue: Queue, *, initiator: Actor) -> None:
    """Удаляет пустую очередь. Очередь с задачами удалить нельзя — для этого есть архив.

    Вместе с очередью исчезают её локальные справочники и привязки типов задач: они
    существуют только внутри очереди. Удаление доступно ради опечатки в ключе сразу
    после создания — ключ неизменяем, и другого способа исправить его нет.
    """
    ensure_allowed(initiator, "queue.delete", target=queue)
    issues = await issue_usage.count_issues_in_queue(session, queue.id)
    if issues:
        raise QueueNotEmptyError(
            details={"key": queue.key, "issues": issues, "hint": "archive the queue instead"},
        )
    await QueueRepository(session).delete(queue)


async def get_queue_config(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
) -> QueueConfig:
    """Конфигурация очереди целиком: типы задач, статусы, резолюции и поля одним запросом.

    Поля отдаются в порядке показа и без ограничения по типу задачи: конфигурация
    описывает очередь целиком, а какие поля применимы к конкретному типу, видно по
    их собственному списку типов. Сузить набор до пары «очередь + тип» можно
    запросом `GET /api/v1/fields?queue=TRK&issue_type=bug`.
    """
    ensure_allowed(initiator, "queue.read", target=queue)
    repository = QueueRepository(session)
    return QueueConfig(
        queue=queue,
        issue_types=await repository.list_issue_types(queue.id, active_only=True),
        statuses=await CatalogRepository(session, Status).list_available(queue.id),
        resolutions=await CatalogRepository(session, Resolution).list_available(queue.id),
        fields=await fields_service.applicable_fields(session, queue=queue),
    )


async def allocate_issue_number(session: AsyncSession, queue: Queue) -> int:
    """Выдаёт следующий номер задачи в очереди.

    Точка, ради которой в задаче 03 продуман счётчик: номера не должны иметь дыр и не
    должны повторяться при параллельных запросах. Механика — в
    `QueueRepository.allocate_issue_number`, там же описана её цена.

    Здесь же стоит запрет на архивную очередь: это единственное место, через которое
    заводятся задачи, и другого способа запретить пополнение архива не нужно.
    """
    if queue.is_archived:
        raise QueueArchivedError(details={"key": queue.key, "reason": "cannot_create_issue"})
    return await QueueRepository(session).allocate_issue_number(queue)


async def allocate_issue_key(session: AsyncSession, queue: Queue) -> str:
    """Следующий ключ задачи (`TRK-123`). Формат собирается в одном месте на весь проект."""
    return format_issue_key(queue.key, await allocate_issue_number(session, queue))


async def _resolve_global_issue_types(
    session: AsyncSession,
    refs: list[str] | None,
) -> list[IssueType]:
    """Типы задач для новой очереди: указанные глобальные либо все активные глобальные."""
    repository = CatalogRepository(session, IssueType)
    if refs is None:
        issue_types = await repository.list_global_active()
    else:
        issue_types = []
        seen: set[str] = set()
        for ref in refs:
            key = _require_global_ref(ref, CatalogKind.ISSUE_TYPE)
            issue_type = await catalogs_service.get_entry(
                session, CatalogKind.ISSUE_TYPE, key=key, queue=None
            )
            if not issue_type.is_active:
                raise CatalogEntryUnavailableError(
                    details={
                        "kind": CatalogKind.ISSUE_TYPE.value,
                        "ref": ref,
                        "reason": "inactive",
                    },
                )
            if str(issue_type.id) not in seen:
                seen.add(str(issue_type.id))
                issue_types.append(issue_type)

    if not issue_types:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.ISSUE_TYPE.value,
                "reason": "no_active_global_issue_types",
                "hint": "create an issue type before creating a queue",
            },
        )
    return issue_types


async def _choose_default[EntryT: (Status, IssueType)](
    session: AsyncSession,
    kind: CatalogKind,
    *,
    ref: str | None,
    available: list[EntryT],
    preferred_key: str,
) -> EntryT:
    """Значение по умолчанию для новой очереди: указанное, привычное или первое доступное."""
    if ref is not None:
        key = _require_global_ref(ref, kind)
        chosen = next((entry for entry in available if entry.key == key), None)
        if chosen is None:
            # Запись не подошла — но по разной причине, и клиенту нужна именно она.
            # Лишний запрос идёт только по ветке отказа: `<kind>_not_found`, если
            # такой записи нет вовсе, и `catalog_entry_unavailable`, если она есть,
            # но отключена или не вошла в выбранный набор.
            await catalogs_service.get_entry(session, kind, key=key, queue=None)
            raise CatalogEntryUnavailableError(
                details={"kind": kind.value, "ref": ref, "reason": "not_available_for_new_queue"},
            )
        return chosen

    preferred = next((entry for entry in available if entry.key == preferred_key), None)
    if preferred is not None:
        return preferred
    if not available:
        raise CatalogEntryUnavailableError(
            details={"kind": kind.value, "reason": "no_active_global_entries"},
        )
    return available[0]


def _require_global_ref(ref: str, kind: CatalogKind) -> str:
    """Ключ из ссылки, которая обязана быть глобальной.

    У создаваемой очереди локальных справочников быть не может — её самой ещё нет.
    Ссылка с префиксом другой очереди отвергается вместо того, чтобы молча
    истолковаться как глобальный ключ.
    """
    parsed = parse_catalog_ref(ref, kind=kind)
    if parsed.queue_key is not None:
        raise CatalogEntryUnavailableError(
            details={
                "kind": kind.value,
                "ref": ref,
                "reason": "must_be_global",
                "queue": parsed.queue_key,
            },
        )
    return parsed.key


async def _resolve_default_issue_type(
    session: AsyncSession,
    queue: Queue,
    ref: str,
    *,
    initiator: Actor,
) -> IssueType:
    """Тип задачи по умолчанию: доступен в очереди и явно в ней разрешён."""
    entry = await resolve_catalog_ref(session, CatalogKind.ISSUE_TYPE, ref, initiator=initiator)
    catalogs_service.ensure_available_in_queue(entry, kind=CatalogKind.ISSUE_TYPE, queue=queue)
    if not await QueueRepository(session).has_issue_type(queue.id, entry.id):
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.ISSUE_TYPE.value,
                "ref": ref,
                "queue": queue.key,
                "reason": "not_allowed_in_queue",
            },
        )
    return entry
