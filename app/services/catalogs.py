"""Сценарии по справочникам: статусы, типы задач, резолюции.

Три справочника обслуживаются одним набором функций: форма у них общая, а различия
(обязательная категория у статуса, иконка у типа задачи) вынесены в параметры.
Конкретика справочника собрана в `CatalogSpec`, чтобы коды ошибок оставались
точными — фронтенд отличает `status_not_found` от `issue_type_not_found`.

Область записи (`queue`) сюда приходит уже разрешённым объектом, а не ключом. Так этот
модуль не зависит от сценариев очередей, и зависимость между ними остаётся
односторонней: очереди знают про справочники, справочники про очереди — нет.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import CatalogRepository, QueueRepository
from app.domain.catalogs import (
    CatalogKind,
    CatalogRef,
    StatusCategory,
    format_catalog_ref,
    validate_catalog_key,
)
from app.domain.errors import (
    CatalogEntryUnavailableError,
    IssueTypeInUseError,
    IssueTypeKeyTakenError,
    IssueTypeNotFoundError,
    ResolutionInUseError,
    ResolutionKeyTakenError,
    ResolutionNotFoundError,
    StatusCategoryLockedError,
    StatusInUseError,
    StatusKeyTakenError,
    StatusNotFoundError,
)
from app.services import issue_usage
from app.services.permissions import ensure_allowed

#: Любая из трёх записей справочника. Общего базового класса у них нет: `BaseModel`
#: слишком широк, а `CatalogEntryMixin` — примесь, а не отображаемая таблица.
type CatalogEntry = Status | IssueType | Resolution


@dataclass(frozen=True, slots=True)
class CatalogSpec:
    """Что отличает один справочник от другого: модель и собственные коды ошибок."""

    kind: CatalogKind
    model: type[Status] | type[IssueType] | type[Resolution]
    not_found: type[AppError]
    key_taken: type[AppError]
    in_use: type[AppError]


SPECS: dict[CatalogKind, CatalogSpec] = {
    CatalogKind.STATUS: CatalogSpec(
        kind=CatalogKind.STATUS,
        model=Status,
        not_found=StatusNotFoundError,
        key_taken=StatusKeyTakenError,
        in_use=StatusInUseError,
    ),
    CatalogKind.ISSUE_TYPE: CatalogSpec(
        kind=CatalogKind.ISSUE_TYPE,
        model=IssueType,
        not_found=IssueTypeNotFoundError,
        key_taken=IssueTypeKeyTakenError,
        in_use=IssueTypeInUseError,
    ),
    CatalogKind.RESOLUTION: CatalogSpec(
        kind=CatalogKind.RESOLUTION,
        model=Resolution,
        not_found=ResolutionNotFoundError,
        key_taken=ResolutionKeyTakenError,
        in_use=ResolutionInUseError,
    ),
}


def spec_for(kind: CatalogKind) -> CatalogSpec:
    return SPECS[kind]


def entry_ref(entry: CatalogEntry) -> CatalogRef:
    """Ссылка на запись: `open` для глобальной, `TRK.open` для локальной.

    Ключ очереди берётся из самой записи, а не из контекста вызова. Это осознанно:
    контекст можно перепутать и выдать локальную запись одной очереди под именем
    другой, а связь ошибиться не может. Связь загружается стратегией `selectin`,
    поэтому у глобальной записи (`queue_id IS NULL`) обращения к базе не будет вовсе.
    """
    queue_key = entry.queue.key if entry.queue_id is not None else None
    return CatalogRef(key=entry.key, queue_key=queue_key)


def format_entry_ref(entry: CatalogEntry) -> str:
    return format_catalog_ref(entry.key, queue_key=entry_ref(entry).queue_key)


def ensure_available_in_queue(entry: CatalogEntry, *, kind: CatalogKind, queue: Queue) -> None:
    """Проверяет, что записью можно пользоваться в этой очереди.

    Две причины отказа, и обе одинаково опасны, если их пропустить: запись принадлежит
    другой очереди (тогда конфигурация ссылается наружу своей области) или отключена
    (тогда очередь получает значение по умолчанию, которого нет в её конфигурации).
    """
    if entry.queue_id is not None and entry.queue_id != queue.id:
        raise CatalogEntryUnavailableError(
            details={
                "kind": kind.value,
                "ref": format_entry_ref(entry),
                "queue": queue.key,
                "reason": "belongs_to_another_queue",
            },
        )
    if not entry.is_active:
        raise CatalogEntryUnavailableError(
            details={
                "kind": kind.value,
                "ref": format_entry_ref(entry),
                "queue": queue.key,
                "reason": "inactive",
            },
        )


async def count_usage(session: AsyncSession, kind: CatalogKind, entry_id: uuid.UUID) -> int:
    """Сколько задач ссылается на запись.

    Диспетчеризация по виду справочника, а не таблица функций в `CatalogSpec`:
    функции должны разрешаться в момент вызова. Замена их в тестах и наполнение
    настоящими запросами в задаче 05 не должны требовать правки этого файла.
    """
    match kind:
        case CatalogKind.STATUS:
            return await issue_usage.count_issues_with_status(session, entry_id)
        case CatalogKind.ISSUE_TYPE:
            return await issue_usage.count_issues_with_issue_type(session, entry_id)
        case CatalogKind.RESOLUTION:
            return await issue_usage.count_issues_with_resolution(session, entry_id)


async def get_entry(
    session: AsyncSession,
    kind: CatalogKind,
    *,
    key: str,
    queue: Queue | None,
) -> CatalogEntry:
    """Запись справочника в указанной области или `<kind>_not_found`.

    Область задаётся объектом очереди, а не ключом: так этот модуль не зависит от
    сценариев очередей. Точка входа интерфейса — `resolve_catalog_ref` в
    `app/services/queues.py`: она разбирает ссылку `TRK.open` и проверяет права.
    """
    spec = spec_for(kind)
    normalized = validate_catalog_key(key, kind=kind)
    repository = CatalogRepository(session, spec.model)
    entry = await repository.get(normalized, None if queue is None else queue.id)
    if entry is None:
        raise spec.not_found(
            details={
                "kind": kind.value,
                "ref": format_catalog_ref(
                    normalized, queue_key=None if queue is None else queue.key
                ),
            },
        )
    return entry


async def list_entries(
    session: AsyncSession,
    kind: CatalogKind,
    *,
    initiator: Actor,
    queue: Queue | None = None,
    include_global: bool = True,
    is_active: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[CatalogEntry]:
    """Страница справочника.

    Без очереди отдаются только глобальные записи, с очередью — доступные в ней:
    глобальные плюс её собственные. Локальная запись вне своей очереди не показывается
    никогда — её ключ имеет смысл только внутри этой очереди.
    """
    ensure_allowed(initiator, f"{kind.value}.list")
    repository = CatalogRepository(session, spec_for(kind).model)
    return await repository.list_page(
        queue_id=None if queue is None else queue.id,
        include_global=include_global,
        is_active=is_active,
        limit=limit,
        cursor=cursor,
    )


async def create_entry(
    session: AsyncSession,
    kind: CatalogKind,
    *,
    initiator: Actor,
    key: str,
    name: str,
    queue: Queue | None = None,
    category: StatusCategory | None = None,
    icon: str = "",
) -> CatalogEntry:
    """Заводит запись справочника — глобальную или локальную для очереди.

    Категория обязательна для статуса и бессмысленна для остальных: справочники
    редактируемые, и статус без категории был бы невидим для досок, прогресса
    проектов и автоматики, которые опираются на неё, а не на ключ.
    """
    spec = spec_for(kind)
    ensure_allowed(initiator, f"{kind.value}.create")
    normalized = validate_catalog_key(key, kind=kind)

    if kind is CatalogKind.STATUS and category is None:
        raise CatalogEntryUnavailableError(
            code="validation_error",
            message="Status category is required",
            details={
                "kind": kind.value,
                "field": "category",
                "reason": "required",
                "allowed": [item.value for item in StatusCategory],
            },
        )

    repository = CatalogRepository(session, spec.model)
    queue_id = None if queue is None else queue.id
    if await repository.get(normalized, queue_id) is not None:
        raise spec.key_taken(
            details={
                "kind": kind.value,
                "key": normalized,
                "queue": None if queue is None else queue.key,
            },
        )

    # Связь `queue`, а не `queue_id`: объект должен знать свою очередь сразу, иначе
    # сборка ссылки `TRK.open` в ответе полезет за ней в базу вне async-контекста.
    entry: CatalogEntry
    match kind:
        case CatalogKind.STATUS:
            entry = Status(key=normalized, name=name.strip(), queue=queue, category=category)
        case CatalogKind.ISSUE_TYPE:
            entry = IssueType(key=normalized, name=name.strip(), queue=queue, icon=icon.strip())
        case CatalogKind.RESOLUTION:
            entry = Resolution(key=normalized, name=name.strip(), queue=queue)
    return await repository.add(entry)


async def update_entry(
    session: AsyncSession,
    entry: CatalogEntry,
    kind: CatalogKind,
    *,
    initiator: Actor,
    name: str | None = None,
    is_active: bool | None = None,
    category: StatusCategory | None = None,
    icon: str | None = None,
) -> CatalogEntry:
    """Меняет название, активность, категорию статуса и иконку типа.

    `None` означает «поле не передано»: схемы `PATCH` отвергают явный `null`, поэтому
    склеить эти два случая здесь невозможно.

    Ключ записи не меняется никогда. На ключи ссылаются воркфлоу, фильтры и сохранённые
    запросы, и переименование ключа тихо порвало бы все эти ссылки; для человека
    существует отображаемое название, которое менять можно сколько угодно.
    """
    ensure_allowed(initiator, f"{kind.value}.update", target=entry)

    if is_active is False and entry.is_active:
        await _ensure_not_queue_default(session, entry, kind, reason="cannot_deactivate")

    if category is not None and kind is CatalogKind.STATUS:
        await _apply_status_category(session, entry, category)

    if name is not None:
        entry.name = name.strip()
    if is_active is not None:
        entry.is_active = is_active
    if icon is not None and kind is CatalogKind.ISSUE_TYPE:
        entry.icon = icon.strip()

    await session.flush()
    return entry


async def delete_entry(
    session: AsyncSession,
    entry: CatalogEntry,
    kind: CatalogKind,
    *,
    initiator: Actor,
) -> None:
    """Удаляет запись справочника, если ею никто не пользуется.

    Удаление используемой записи запрещено, а не выполняется «с переносом»: задачи,
    оставшиеся со ссылкой в никуда, сломали бы доски и расчёт прогресса проектов, и
    заметили бы это далеко от места ошибки. Для статуса есть явный сценарий переноса
    задач (`move_issues`), после которого удаление проходит.

    Единственное, что удаление меняет молча, — привязки типа задачи к очередям: они
    исчезают каскадом. Это следствие самого удаления, а не отдельное решение: тип,
    которым пользуются задачи или который выбран в очереди по умолчанию, удалить и
    так нельзя, а разрешение «этот тип можно заводить в этой очереди» без самого типа
    ничего не значит.
    """
    ensure_allowed(initiator, f"{kind.value}.delete", target=entry)

    used_by = await count_usage(session, kind, entry.id)
    if used_by:
        raise spec_for(kind).in_use(
            details={
                "kind": kind.value,
                "ref": format_entry_ref(entry),
                "reason": "issues_exist",
                "issues": used_by,
            },
        )

    await _ensure_not_queue_default(session, entry, kind, reason="cannot_delete")
    await CatalogRepository(session, spec_for(kind).model).delete(entry)


@dataclass(frozen=True, slots=True)
class IssuesMoved:
    """Результат переноса задач между статусами."""

    source: Status
    target: Status
    moved: int


async def move_issues(
    session: AsyncSession,
    *,
    initiator: Actor,
    source: Status,
    target: Status,
    queue: Queue | None = None,
) -> IssuesMoved:
    """Переносит задачи из одного статуса в другой — явный сценарий, а не побочный эффект.

    Существует ради удаления непустого статуса: сначала задачи переезжают, потом статус
    удаляется. Два шага вместо одного намеренно — «удалить с переносом» слишком легко
    выполнить не глядя, а перенос сотни задач должен быть отдельным решением.

    Область переноса:

    - `queue` задан — переносятся задачи только этой очереди, целевой статус должен
      быть доступен в ней;
    - `queue` не задан, исходный статус локальный — переносятся задачи его очереди;
    - `queue` не задан, исходный статус глобальный — переносятся задачи всех очередей,
      и потому целевой статус обязан быть глобальным: локальный принял бы задачи
      чужих очередей.
    """
    ensure_allowed(initiator, f"{CatalogKind.STATUS.value}.move_issues", target=source)

    if source.id == target.id:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.STATUS.value,
                "ref": format_entry_ref(target),
                "reason": "same_status",
            },
        )

    scope_queue = queue
    if scope_queue is None and source.queue_id is not None:
        scope_queue = source.queue

    if scope_queue is None:
        if target.queue_id is not None:
            raise CatalogEntryUnavailableError(
                details={
                    "kind": CatalogKind.STATUS.value,
                    "ref": format_entry_ref(target),
                    "reason": "target_must_be_global",
                },
            )
        if not target.is_active:
            raise CatalogEntryUnavailableError(
                details={
                    "kind": CatalogKind.STATUS.value,
                    "ref": format_entry_ref(target),
                    "reason": "inactive",
                },
            )
    else:
        ensure_available_in_queue(source, kind=CatalogKind.STATUS, queue=scope_queue)
        ensure_available_in_queue(target, kind=CatalogKind.STATUS, queue=scope_queue)

    moved = await issue_usage.move_issues_to_status(
        session,
        from_status_id=source.id,
        to_status_id=target.id,
        queue_id=None if scope_queue is None else scope_queue.id,
    )
    return IssuesMoved(source=source, target=target, moved=moved)


async def _apply_status_category(
    session: AsyncSession,
    entry: Status,
    category: StatusCategory,
) -> None:
    """Меняет категорию статуса, если в нём нет задач.

    Категория — машинный смысл статуса. Сменить её у статуса с задачами значит задним
    числом переопределить, какие задачи считаются закрытыми: прогресс проектов и доски
    изменятся, хотя ни одна задача не двигалась.
    """
    if entry.category is category:
        return
    used_by = await count_usage(session, CatalogKind.STATUS, entry.id)
    if used_by:
        raise StatusCategoryLockedError(
            details={
                "ref": format_entry_ref(entry),
                "category": entry.category.value,
                "requested": category.value,
                "issues": used_by,
            },
        )
    entry.category = category


async def _ensure_not_queue_default(
    session: AsyncSession,
    entry: CatalogEntry,
    kind: CatalogKind,
    *,
    reason: str,
) -> None:
    """Запись, выбранную очередью по умолчанию, нельзя ни удалить, ни отключить.

    Иначе очередь осталась бы с настройкой, которой нельзя воспользоваться, а узналось
    бы это при создании первой же задачи — далеко от места, где сломали.
    """
    repository = QueueRepository(session)
    match kind:
        case CatalogKind.STATUS:
            queue_keys = await repository.keys_with_default_status(entry.id)
        case CatalogKind.ISSUE_TYPE:
            queue_keys = await repository.keys_with_default_issue_type(entry.id)
        case CatalogKind.RESOLUTION:
            return

    if queue_keys:
        raise spec_for(kind).in_use(
            details={
                "kind": kind.value,
                "ref": format_entry_ref(entry),
                "reason": f"{reason}_queue_default",
                "queues": queue_keys,
            },
        )
