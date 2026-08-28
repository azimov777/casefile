"""Сценарии по задачам: создание, чтение, изменение, наблюдатели, удаление.

## Единая точка применения изменений

Всё, что меняет задачу, проходит через `apply_issue_changes`. Она принимает «что
меняем» (`IssueChanges`) и «кто меняет» (`initiator`), а возвращает список фактических
изменений — поле, было, стало. К этой точке уже подключены журнал изменений и outbox
(задача 06) и проверка переходов (задача 07); задача 13 подключит автоматику. Если бы
мутации были размазаны по эндпоинтам, каждая из этих задач превращалась бы в обход
всех мест, где что-то меняется, а забытое место обнаруживалось бы как пропавшая
история.

Создание, изменение и удаление задачи пишут журнал и событие **в той же транзакции**,
что и сама правка. Мутация, сделанная мимо этих трёх функций, не попадёт ни в историю,
ни в шину событий.

«Фактических» — не формальность. Поле, переданное со значением, равным текущему,
записи не даёт и версию не увеличивает: иначе журнал заполнился бы пустыми строками, а
автоматика срабатывала бы на изменение, которого не было.

## Что не передано и что передано как null

Признак «не передано» — общий на проект (`app/core/sentinels.py`). У задачи это не
украшение: `assignee`, `deadline` и `resolution` очищаются именно передачей `null`, и
склеить «очистить» с «не трогать» значило бы либо не дать очистить поле, либо затирать
его при каждом частичном обновлении.

## Оптимистичная блокировка

У задачи есть `version`. Клиент присылает ту, которую видел; расхождение — `409
version_conflict`. Проверка стоит в единой точке, а не в эндпоинте: тот же сценарий
зовут MCP и автоматика, и там гонка ровно та же.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import IssueRepository, QueueRepository
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.errors import (
    ActorInactiveError,
    CatalogEntryUnavailableError,
    IssueNotFoundError,
    IssueReferencedError,
    IssueResolutionNotAllowedError,
    IssueResolutionRequiredError,
    IssueVersionConflictError,
)
from app.domain.fields import apply_value_changes
from app.domain.issues import (
    DEFAULT_PRIORITY,
    IssueChange,
    IssueField,
    IssuePriority,
    normalize_tags,
    tags_differ,
    validate_deadline,
    validate_description,
    validate_summary,
)
from app.domain.queues import format_issue_key, parse_issue_key
from app.domain.workflows import filled_field_names
from app.services import catalogs as catalogs_service
from app.services import events as events_service
from app.services import fields as fields_service
from app.services import queues as queues_service
from app.services import workflow as workflow_service
from app.services.permissions import ensure_allowed


@dataclass(frozen=True, slots=True)
class IssueChanges:
    """Что меняем в задаче. Не переданное поле остаётся `UNSET` и не трогается.

    Поля, у которых `null` осмыслен, объявлены как `T | None`: `assignee`, `deadline` и
    `resolution` очищаются именно им. У остальных `null` смысла не имеет, и передавать
    его нельзя — тип этого не позволяет.

    `values` — **частичное** изменение кастомных полей: `null` снимает значение,
    отсутствующий ключ не трогает поле. Склейка с текущим состоянием и проверка
    результата целиком делаются внутри, потому что валидатор проверяет полный набор.

    `followers` — наоборот, **весь** набор наблюдателей: добавление и удаление
    выражаются через него, чтобы у изменения был один вид и в журнале, и в событии.
    Сценарии `add_follower` и `remove_follower` — обёртки, считающие новый набор.
    """

    summary: str = UNSET
    description: str = UNSET
    issue_type: IssueType = UNSET
    status: Status = UNSET
    resolution: Resolution | None = UNSET
    priority: IssuePriority = UNSET
    assignee: Actor | None = UNSET
    deadline: datetime | None = UNSET
    tags: Sequence[str] = UNSET
    values: Mapping[str, Any] = UNSET
    followers: Sequence[Actor] = UNSET


@dataclass(frozen=True, slots=True)
class IssueMutation:
    """Результат применения изменений: сама задача и список того, что реально изменилось.

    Пустой список — законный результат: клиент прислал то, что уже стоит. Версия при
    этом не растёт, и повторный запрос с той же версией не упрётся в конфликт.
    """

    issue: Issue
    changes: tuple[IssueChange, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.changes)


# --- Чтение ----------------------------------------------------------------------


async def get_issue_by_key(session: AsyncSession, key: str) -> Issue:
    """Задача по ключу или `issue_not_found`.

    Ключ разбирается доменной функцией, а не сравнивается как строка: `trk-1` и
    `TRK-1` — одна задача (адресация в проекте мягкая), а `TRK-007` и `TRK-1-2` —
    не ключи вовсе, и молча искать по ним нечего.

    Прав не проверяет: точка входа интерфейса — `read_issue`.
    """
    queue_key, number = parse_issue_key(key)
    normalized = format_issue_key(queue_key, number)
    issue = await IssueRepository(session).get_by_key(normalized)
    if issue is None:
        raise IssueNotFoundError(details={"key": normalized})
    return issue


async def read_issue(session: AsyncSession, key: str, *, initiator: Actor) -> Issue:
    ensure_allowed(initiator, "issue.read")
    return await get_issue_by_key(session, key)


async def list_issues(
    session: AsyncSession,
    *,
    initiator: Actor,
    queue: Queue | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Issue]:
    """Страница задач: без очереди — все, с очередью — только её.

    Простое перечисление, а не поиск: отбор по статусу, исполнителю, значениям полей и
    язык запросов строит задача 12. Заводить сейчас половину её параметров значило бы
    получить в одном API два разных набора фильтров.
    """
    ensure_allowed(initiator, "issue.list")
    return await IssueRepository(session).list_page(
        queue_id=None if queue is None else queue.id,
        limit=limit,
        cursor=cursor,
    )


# --- Создание --------------------------------------------------------------------


async def create_issue(
    session: AsyncSession,
    *,
    initiator: Actor,
    queue: Queue,
    summary: str,
    description: str = "",
    issue_type: IssueType | None = None,
    status: Status | None = None,
    resolution: Resolution | None = None,
    priority: IssuePriority = DEFAULT_PRIORITY,
    author: Actor | None = None,
    assignee: Actor | None = None,
    followers: Sequence[Actor] = (),
    deadline: datetime | None = None,
    tags: Sequence[str] = (),
    values: Mapping[str, Any] | None = None,
) -> Issue:
    """Заводит задачу в очереди.

    Тип и статус берутся из настроек очереди, если не указаны, — ради этого очередь и
    не может существовать без них. Автор по умолчанию — инициатор: у задачи,
    заведённой агентом, автором должен быть агент, а не владелец установки.

    Порядок шагов важен и выбран сознательно: сначала проверяется всё, что может
    отказать, и только потом выдаётся номер. Номер выдаётся атомарным `UPDATE ...
    RETURNING` и при откате транзакции теряется (см. `docs/notes/db.md`), поэтому
    сжигать его на запросе, который всё равно не пройдёт валидацию, не нужно.
    """
    ensure_allowed(initiator, "issue.create", target=queue)

    issue_author = author or initiator
    _require_active(issue_author, "cannot_author_issue")
    if assignee is not None:
        _require_active(assignee, "cannot_be_assignee")
    watchers = _unique_actors(followers)
    for watcher in watchers:
        _require_active(watcher, "cannot_follow_issue")

    target_type = issue_type or queue.default_issue_type
    await _ensure_issue_type_allowed(session, queue, target_type)
    target_status = status or queue.default_status
    catalogs_service.ensure_available_in_queue(target_status, kind=CatalogKind.STATUS, queue=queue)
    await workflow_service.ensure_status_in_assigned_workflow(
        session,
        queue=queue,
        issue_type=target_type,
        status=target_status,
    )
    if resolution is not None:
        catalogs_service.ensure_available_in_queue(
            resolution, kind=CatalogKind.RESOLUTION, queue=queue
        )
    _ensure_resolution_state(target_status, resolution)

    # Все проверки — до выдачи номера. Порядок здесь и есть та самая экономия ключей:
    # доменные проверки дешёвые, но отказывают чаще всего, а номер, взятый и потерянный
    # на откате, обратно не возвращается.
    stored_summary = validate_summary(summary)
    stored_description = validate_description(description)
    stored_deadline = validate_deadline(deadline)
    stored_tags = normalize_tags(tags)
    stored_values = await fields_service.validate_issue_values(
        session,
        queue=queue,
        issue_type=target_type,
        values=dict(values or {}),
    )

    # Ключ выдаётся последним и только через сценарий очередей: там же стоит запрет на
    # архивную очередь, и второй счётчик номеров дал бы дубли ключей.
    key = await queues_service.allocate_issue_key(session, queue)

    # Связи передаются объектами, а не идентификаторами: у только что созданной задачи
    # они иначе не загружены, и сборка ответа полезла бы за ними в базу вне
    # async-контекста — падение `MissingGreenlet` далеко от места ошибки.
    issue = Issue(
        key=key,
        queue=queue,
        issue_type=target_type,
        status=target_status,
        resolution=resolution,
        priority=priority,
        summary=stored_summary,
        description=stored_description,
        author=issue_author,
        assignee=assignee,
        followers=watchers,
        deadline=stored_deadline,
        tags=stored_tags,
        values=stored_values,
        version=1,
    )
    await IssueRepository(session).add(issue)
    # Журнал и событие — в той же транзакции, что и сама задача: откат уносит всё
    # трое разом, и подписчик никогда не узнает о задаче, которой не появилось.
    await events_service.record_issue_created(session, issue, initiator=initiator)
    return issue


# --- Изменение -------------------------------------------------------------------


async def apply_issue_changes(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    changes: IssueChanges,
    action: str = "issue.update",
    expected_version: int | None = None,
) -> IssueMutation:
    """Единая точка изменения задачи. Возвращает список фактических изменений.

    Проверка прав, оптимистичная блокировка, проверка перехода и увеличение версии
    стоят здесь, а не в вызывающих сценариях: любой обход этой функции означал бы
    задачу, изменённую мимо истории, событий и правил процесса.

    `action` — имя действия для проверки прав (`issue.update`, `issue.assign`, ...).
    В v1 разрешено всё, но действие уже различается: когда появятся роли, наполнять
    придётся `app/services/permissions.py`, а не искать пропущенные проверки.
    """
    ensure_allowed(initiator, action, target=issue)
    _ensure_version(issue, expected_version)

    queue = issue.queue
    target_type = changes.issue_type if is_set(changes.issue_type) else issue.issue_type
    # Решение «тип поменялся» принимается до применения изменений: присваивание связи
    # обновляет внешний ключ только на flush, и проверка после присваивания читала бы
    # то старое, то новое значение в зависимости от того, был ли flush между ними.
    type_changed = is_set(changes.issue_type) and changes.issue_type.id != issue.issue_type_id
    if is_set(changes.issue_type):
        await _ensure_issue_type_allowed(session, queue, target_type)
        target_status = changes.status if is_set(changes.status) else issue.status
        await workflow_service.ensure_status_in_assigned_workflow(
            session,
            queue=queue,
            issue_type=target_type,
            status=target_status,
        )
    status_changed = is_set(changes.status) and changes.status.id != issue.status_id
    if is_set(changes.status):
        catalogs_service.ensure_available_in_queue(
            changes.status, kind=CatalogKind.STATUS, queue=queue
        )
        if status_changed:
            await workflow_service.ensure_transition_allowed(
                session, issue, target_status=changes.status, initiator=initiator
            )
    changes = _normalize_resolution_changes(issue, changes)
    if status_changed:
        await workflow_service.ensure_transition_requirements(
            session,
            issue,
            target_status=changes.status,
            filled_fields=filled_fields_for(issue, changes),
        )
    if is_set(changes.resolution) and changes.resolution is not None:
        catalogs_service.ensure_available_in_queue(
            changes.resolution, kind=CatalogKind.RESOLUTION, queue=queue
        )
    if is_set(changes.assignee) and changes.assignee is not None:
        _require_active(changes.assignee, "cannot_be_assignee")

    recorded: list[IssueChange] = []
    _apply_scalars(issue, changes, recorded)
    _apply_tags(issue, changes, recorded)
    _apply_followers(issue, changes, recorded)
    await _apply_values(session, issue, changes, target_type, type_changed, recorded)

    if not recorded:
        # Нечего записывать — значит, нечего и рассылать: клиент прислал то, что уже
        # стоит. Версия не растёт, журнал не пополняется, событие не рождается.
        return IssueMutation(issue=issue)

    issue.version += 1
    await session.flush()
    # Порядок важен: сначала flush изменений, потом запись журнала и события. Снимок
    # задачи в полезной нагрузке обязан быть состоянием **после** изменения, включая
    # новую версию и `updated_at`, который проставляет база.
    changes = tuple(recorded)
    await events_service.record_issue_changed(
        session,
        issue,
        initiator=initiator,
        action=action,
        changes=changes,
    )
    return IssueMutation(issue=issue, changes=changes)


async def transition_issue(
    session: AsyncSession,
    issue: Issue,
    transition_id: uuid.UUID,
    *,
    initiator: Actor,
    changes: IssueChanges | None = None,
    expected_version: int | None = None,
) -> IssueMutation:
    """Выполняет выбранное ребро и дополнительные поля одной мутацией.

    `resolution` и `values`, переданные вместе с действием, проверяются в целевом
    состоянии. Поэтому закрытие не требует предварительного PATCH и всё равно даёт
    одну версию, одну запись истории и одно событие.
    """
    requested = changes or IssueChanges()
    if is_set(requested.status) or is_set(requested.issue_type):
        raise ValueError("transition_issue chooses status and issue type itself")

    # Сначала проверяем выбранное ребро и права, затем добавляем его цель в будущие
    # изменения и проверяем требования уже с переданными полями.
    transition = await workflow_service.selected_transition(
        session,
        issue,
        transition_id,
        initiator=initiator,
    )

    combined = replace(requested, status=transition.to_status)
    normalized = _normalize_resolution_changes(issue, combined)
    workflow_service.ensure_transition_fields(
        issue,
        transition,
        filled_fields=filled_fields_for(issue, normalized),
    )
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=normalized,
        action="issue.transition",
        expected_version=expected_version,
    )


def filled_fields_for(issue: Issue, changes: IssueChanges | None = None) -> frozenset[str]:
    """Заполненные поля текущего или будущего состояния для условий перехода."""
    changes = changes or IssueChanges()

    def chosen(name: str, current: Any) -> Any:
        value = getattr(changes, name)
        return value if is_set(value) else current

    values = (
        apply_value_changes(issue.values, changes.values)
        if is_set(changes.values)
        else issue.values
    )
    return filled_field_names(
        values,
        system_values={
            IssueField.SUMMARY.value: chosen("summary", issue.summary),
            IssueField.DESCRIPTION.value: chosen("description", issue.description),
            IssueField.RESOLUTION.value: chosen("resolution", issue.resolution),
            IssueField.PRIORITY.value: chosen("priority", issue.priority),
            IssueField.ASSIGNEE.value: chosen("assignee", issue.assignee),
            IssueField.FOLLOWERS.value: chosen("followers", issue.followers),
            IssueField.DEADLINE.value: chosen("deadline", issue.deadline),
            IssueField.TAGS.value: chosen("tags", issue.tags),
        },
    )


async def update_issue(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    changes: IssueChanges,
    expected_version: int | None = None,
) -> IssueMutation:
    """Частичное обновление задачи: применяются только переданные поля.

    Ключ задачи в изменения не входит и не меняется никогда — в том числе если задачу
    научатся переносить между очередями: на ключ ссылаются внешние системы, переписка
    и история изменений.
    """
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=changes,
        expected_version=expected_version,
    )


async def assign_issue(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    assignee: Actor | None,
    expected_version: int | None = None,
) -> IssueMutation:
    """Назначает исполнителя или снимает его, если передан `None`.

    Отдельный сценарий, а не только поле в частичном обновлении: назначение — самое
    частое действие агента и автоматики, у него своё действие для проверки прав и своё
    событие в задаче 06.
    """
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(assignee=assignee),
        action="issue.assign",
        expected_version=expected_version,
    )


async def add_follower(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    actor: Actor,
) -> IssueMutation:
    """Добавляет наблюдателя. Повторный вызов ничего не меняет и ошибкой не считается.

    Идемпотентность по той же причине, что у отзыва токена и архивации очереди: клиент,
    не получивший ответ и повторивший запрос, не должен получать ошибку на выполненное
    действие.
    """
    _require_active(actor, "cannot_follow_issue")
    if any(follower.id == actor.id for follower in issue.followers):
        ensure_allowed(initiator, "issue.follow", target=issue)
        return IssueMutation(issue=issue)
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(followers=[*issue.followers, actor]),
        action="issue.follow",
    )


async def remove_follower(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    actor: Actor,
) -> IssueMutation:
    """Убирает наблюдателя. Тоже идемпотентно."""
    remaining = [follower for follower in issue.followers if follower.id != actor.id]
    if len(remaining) == len(issue.followers):
        ensure_allowed(initiator, "issue.unfollow", target=issue)
        return IssueMutation(issue=issue)
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(followers=remaining),
        action="issue.unfollow",
    )


async def delete_issue(session: AsyncSession, issue: Issue, *, initiator: Actor) -> None:
    """Удаляет задачу насовсем, если на неё никто не ссылается.

    Номер задачи при этом не освобождается: счётчик очереди только растёт, и ключ
    удалённой задачи никогда не достанется другой. Иначе ссылка `TRK-42` в переписке,
    во внешней системе и в значении кастомного поля однажды указала бы на чужую задачу.

    Ссылки из кастомных полей проверяются отдельно, и удаление отклоняется: валидатор
    не пропускает ссылку на несуществующую задачу при записи, и было бы странно
    получать такое состояние удалением. Тихая же дыра здесь неотличима от опечатки —
    форма показала бы пустое поле, а фильтр не нашёл бы ничего.
    """
    ensure_allowed(initiator, "issue.delete", target=issue)
    await _ensure_not_referenced(session, issue)
    # Событие собирается **до** удаления: после него снимок строить уже не из чего.
    # Записи журнала у удаления нет — история уезжает вместе с задачей каскадом, и
    # запись, сделанная сейчас, была бы удалена в этой же транзакции.
    await events_service.record_issue_deleted(session, issue, initiator=initiator)
    await IssueRepository(session).delete(issue)


async def _ensure_not_referenced(session: AsyncSession, issue: Issue) -> None:
    """Задача, на которую ссылаются кастомные поля других задач, не удаляется.

    Запрос идёт только по полям типа «ссылка на задачу»: их обычно единицы, а выражение
    `values @> :fragment` по каждому ложится на GIN-индекс. Сама задача из ответа
    исключается — поле, ссылающееся на собственную задачу, удалению не мешает.
    """
    refs = await fields_service.issue_reference_refs(session)
    referencing = [
        key
        for key in await IssueRepository(session).keys_referencing(refs, issue.key)
        if key != issue.key
    ]
    if referencing:
        raise IssueReferencedError(
            details={
                "key": issue.key,
                "reason": "referenced_by_issues",
                "issues": referencing,
                "hint": "clear the references first",
            },
        )


# --- Внутреннее ------------------------------------------------------------------


def _normalize_resolution_changes(issue: Issue, changes: IssueChanges) -> IssueChanges:
    """Приводит резолюцию к инварианту целевой категории статуса.

    Выход из `done` добавляет явное `resolution=None` в тот же набор изменений. Поэтому
    сброс виден в журнале и событии рядом со сменой статуса, а не происходит вторым
    скрытым UPDATE. Явная попытка поставить резолюцию незавершённой задаче отвергается:
    успешный ответ с молча отброшенным полем был бы ложью клиенту.
    """
    target_status = changes.status if is_set(changes.status) else issue.status
    target_resolution = changes.resolution if is_set(changes.resolution) else issue.resolution

    if target_status.category is not StatusCategory.DONE:
        if is_set(changes.resolution) and changes.resolution is not None:
            raise IssueResolutionNotAllowedError(
                details={
                    "status": target_status.ref,
                    "category": target_status.category.value,
                }
            )
        if target_resolution is not None:
            changes = replace(changes, resolution=None)
            target_resolution = None

    _ensure_resolution_state(target_status, target_resolution)
    return changes


def _ensure_resolution_state(status: Status, resolution: Resolution | None) -> None:
    if status.category is StatusCategory.DONE and resolution is None:
        raise IssueResolutionRequiredError(
            details={"status": status.ref, "category": status.category.value}
        )
    if status.category is not StatusCategory.DONE and resolution is not None:
        raise IssueResolutionNotAllowedError(
            details={"status": status.ref, "category": status.category.value}
        )


def _ensure_version(issue: Issue, expected_version: int | None) -> None:
    """Оптимистичная блокировка. `None` означает «клиент версию не прислал».

    Отсутствие версии — не молчаливое согласие на перезапись, а осознанный режим для
    вызовов, где гонки нет: автоматика, миграции данных, инструменты MCP, работающие с
    только что прочитанной задачей. HTTP-клиент версию присылает.
    """
    if expected_version is not None and expected_version != issue.version:
        raise IssueVersionConflictError(
            details={
                "key": issue.key,
                "expected": expected_version,
                "actual": issue.version,
                "hint": "re-read the issue and retry",
            },
        )


def _require_active(actor: Actor, reason: str) -> None:
    """Отключённый актор не может быть автором, исполнителем и наблюдателем.

    Уже записанные ссылки на него остаются: отключение — способ убрать агента, не
    ломая историю. Запрещено только назначать его заново.
    """
    if not actor.is_active:
        raise ActorInactiveError(details={"key": actor.key, "reason": reason})


def _unique_actors(actors: Sequence[Actor]) -> list[Actor]:
    """Убирает повторы, сохраняя порядок: тот же актор дважды — не ошибка запроса."""
    unique: list[Actor] = []
    seen: set[Any] = set()
    for actor in actors:
        if actor.id in seen:
            continue
        seen.add(actor.id)
        unique.append(actor)
    return unique


async def _ensure_issue_type_allowed(
    session: AsyncSession,
    queue: Queue,
    issue_type: IssueType,
) -> None:
    """Тип задачи доступен в очереди и явно в ней разрешён.

    Две разные проверки: `ensure_available_in_queue` отсекает локальный тип чужой
    очереди и отключённый тип, а список `queue_issue_types` — тип, который в этой
    очереди заводить не разрешали. Без второй задача получила бы тип, которого нет ни в
    конфигурации очереди, ни в форме создания.
    """
    catalogs_service.ensure_available_in_queue(issue_type, kind=CatalogKind.ISSUE_TYPE, queue=queue)
    if not await QueueRepository(session).has_issue_type(queue.id, issue_type.id):
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.ISSUE_TYPE.value,
                "ref": catalogs_service.format_entry_ref(issue_type),
                "queue": queue.key,
                "reason": "not_allowed_in_queue",
            },
        )


def _apply_scalars(issue: Issue, changes: IssueChanges, recorded: list[IssueChange]) -> None:
    """Простые поля: сравнить, записать изменение, присвоить.

    «Было» и «стало» сразу в том виде, в каком уедут в журнал и в событие: запись
    справочника — ссылкой, актор — ключом, время — строкой ISO 8601. ORM-объект туда
    класть нельзя: событие переживает транзакцию, а объект — нет.
    """
    if is_set(changes.summary):
        summary = validate_summary(changes.summary)
        if summary != issue.summary:
            _record(recorded, IssueField.SUMMARY, issue.summary, summary)
            issue.summary = summary
    if is_set(changes.description):
        description = validate_description(changes.description)
        if description != issue.description:
            _record(recorded, IssueField.DESCRIPTION, issue.description, description)
            issue.description = description
    if is_set(changes.issue_type) and changes.issue_type.id != issue.issue_type_id:
        _record(
            recorded,
            IssueField.ISSUE_TYPE,
            catalogs_service.format_entry_ref(issue.issue_type),
            catalogs_service.format_entry_ref(changes.issue_type),
        )
        issue.issue_type = changes.issue_type
    if is_set(changes.status) and changes.status.id != issue.status_id:
        _record(
            recorded,
            IssueField.STATUS,
            catalogs_service.format_entry_ref(issue.status),
            catalogs_service.format_entry_ref(changes.status),
        )
        issue.status = changes.status
    if is_set(changes.resolution):
        after_id = None if changes.resolution is None else changes.resolution.id
        if after_id != issue.resolution_id:
            _record(
                recorded,
                IssueField.RESOLUTION,
                _entry_ref(issue.resolution),
                _entry_ref(changes.resolution),
            )
            issue.resolution = changes.resolution
    if is_set(changes.priority) and changes.priority is not issue.priority:
        _record(recorded, IssueField.PRIORITY, issue.priority.value, changes.priority.value)
        issue.priority = changes.priority
    if is_set(changes.assignee):
        after_id = None if changes.assignee is None else changes.assignee.id
        if after_id != issue.assignee_id:
            _record(
                recorded,
                IssueField.ASSIGNEE,
                _actor_key(issue.assignee),
                _actor_key(changes.assignee),
            )
            issue.assignee = changes.assignee
    if is_set(changes.deadline):
        after = validate_deadline(changes.deadline)
        if after != issue.deadline:
            _record(recorded, IssueField.DEADLINE, _moment(issue.deadline), _moment(after))
            issue.deadline = after


def _apply_tags(issue: Issue, changes: IssueChanges, recorded: list[IssueChange]) -> None:
    """Теги заменяются набором целиком: точечное добавление дало бы гонку на списке."""
    if not is_set(changes.tags):
        return
    after = normalize_tags(changes.tags)
    if not tags_differ(issue.tags, after):
        return
    _record(recorded, IssueField.TAGS, list(issue.tags), after, force=True)
    # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации внутри
    # значения, и UPDATE просто не уйдёт. Присваивается всегда новый список.
    issue.tags = after


def _apply_followers(issue: Issue, changes: IssueChanges, recorded: list[IssueChange]) -> None:
    if not is_set(changes.followers):
        return
    after = _unique_actors(list(changes.followers))
    for watcher in after:
        _require_active(watcher, "cannot_follow_issue")
    before_keys = sorted(follower.key for follower in issue.followers)
    after_keys = sorted(follower.key for follower in after)
    if before_keys == after_keys:
        return
    _record(recorded, IssueField.FOLLOWERS, before_keys, after_keys, force=True)
    issue.followers = after


async def _apply_values(
    session: AsyncSession,
    issue: Issue,
    changes: IssueChanges,
    target_type: IssueType,
    type_changed: bool,
    recorded: list[IssueChange],
) -> None:
    """Кастомные поля: склеить, проверить полный набор, записать разницу по каждому полю.

    Порядок именно такой. Валидатор проверяет полный набор — обязательность иначе не
    проверить, — поэтому сначала текущие значения склеиваются с изменениями
    (`apply_value_changes`: `null` снимает, отсутствующий ключ не трогает), и только
    потом результат уходит в проверку. Обратный порядок позволил бы частичным
    обновлением оставить задачу без обязательного поля.

    Проверка запускается ещё и при смене типа задачи, даже если значений не присылали:
    у нового типа другой набор применимых полей, и старые значения могут стать
    неприменимыми, а новые обязательные — незаполненными. Молча оставить как есть
    нельзя: задача осталась бы в состоянии, которого её собственная форма не допускает.
    """
    if not is_set(changes.values) and not type_changed:
        return

    merged = (
        apply_value_changes(issue.values, changes.values)
        if is_set(changes.values)
        else dict(issue.values)
    )
    stored = await fields_service.validate_issue_values(
        session,
        queue=issue.queue,
        issue_type=target_type,
        values=merged,
    )

    before = dict(issue.values)
    if before == stored:
        return
    for ref in sorted(set(before) | set(stored)):
        if before.get(ref) != stored.get(ref):
            recorded.append(IssueChange(field=ref, before=before.get(ref), after=stored.get(ref)))
    # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации внутри
    # значения, и UPDATE просто не уйдёт. Присваивается всегда новый словарь.
    issue.values = stored


def _record(
    recorded: list[IssueChange],
    field: IssueField,
    before: Any,
    after: Any,
    *,
    force: bool = False,
) -> None:
    """Записывает изменение, если оно есть. `force` — для уже сравненных значений."""
    if not force and before == after:
        return
    recorded.append(IssueChange(field=field.value, before=before, after=after))


def _entry_ref(entry: Resolution | None) -> str | None:
    return None if entry is None else catalogs_service.format_entry_ref(entry)


def _actor_key(actor: Actor | None) -> str | None:
    return None if actor is None else actor.key


def _moment(value: datetime | None) -> str | None:
    """Время в журнале — строка ISO 8601 в UTC: тот же формат, что в API и в `values`."""
    return None if value is None else value.astimezone(UTC).isoformat()
