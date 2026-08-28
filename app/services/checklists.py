"""Сценарии чеклиста: добавить пункт, изменить, отметить, переставить, удалить.

## Перемещение меняет одну строку

Порядок держится на разреженных позициях (`app/domain/checklists.py`): новая позиция
вычисляется между соседями по месту вставки, и в базу уходит один UPDATE. Перенумерация
всего списка случается только тогда, когда зазор между соседями исчерпан, — и это
единственная операция чеклиста, которая трогает больше одной строки.

Перенумерация не молчаливая: она видна в событии `checklist.item_moved` тем, что
позиции соседей в нём отличаются от прежних. Полагаться на конкретные числа позиций
клиенту нельзя — только на порядок, в котором приезжают пункты.

## Изменение считается фактическим

Отметка уже отмеченного пункта, правка текста на тот же текст и перемещение на то же
место не пишут ни журнала, ни события. Правило общее с единой точкой изменения задачи:
иначе история задачи заполнялась бы строками ни о чём, а автоматика срабатывала бы на
изменение, которого не было.

Транзакцию сценарии не фиксируют: границу держит вход в приложение.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.checklist import ChecklistItem
from app.db.models.issue import Issue
from app.db.repositories import ChecklistRepository
from app.domain.checklists import (
    ensure_capacity,
    next_position,
    position_between,
    rebalanced_positions,
    validate_item_deadline,
    validate_text,
)
from app.domain.errors import ActorInactiveError, ChecklistItemNotFoundError
from app.services import events as events_service
from app.services.permissions import ensure_allowed


async def get_item(session: AsyncSession, issue: Issue, item_id: uuid.UUID) -> ChecklistItem:
    """Пункт чеклиста этой задачи или `checklist_item_not_found`.

    Принадлежность проверяется здесь, а не в роутере: пункт адресуется в пути своей
    задачей, и чужой пункт для клиента то же самое, что несуществующий.
    """
    item = await ChecklistRepository(session).get_by_id(item_id)
    if item is None or item.issue_id != issue.id:
        raise ChecklistItemNotFoundError(details={"item": str(item_id), "issue": issue.key})
    return item


async def list_items(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
) -> list[ChecklistItem]:
    """Чеклист задачи целиком, по порядку.

    Без пагинации: число пунктов ограничено доменом, поэтому список всегда помещается
    в один ответ. Курсор посреди списка, порядок в котором задаётся перетаскиванием,
    указывал бы на позицию, которой после следующего перемещения уже нет.
    """
    ensure_allowed(initiator, "issue.checklist", target=issue)
    return await ChecklistRepository(session).list_for_issue(issue.id)


async def add_item(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    text: str,
    assignee: Actor | None = None,
    deadline: datetime | None = None,
) -> ChecklistItem:
    """Добавляет пункт в конец чеклиста."""
    ensure_allowed(initiator, "checklist.item_add", target=issue)
    if assignee is not None:
        _require_active(assignee)

    repository = ChecklistRepository(session)
    items = await repository.list_for_issue(issue.id)
    ensure_capacity(len(items))

    item = ChecklistItem(
        issue_id=issue.id,
        text=validate_text(text),
        position=next_position(items[-1].position if items else None),
        assignee=assignee,
        deadline=validate_item_deadline(deadline),
    )
    await repository.add(item)
    # Журнал задачи и событие — в той же транзакции, что и сам пункт.
    await events_service.record_checklist_change(
        session,
        item,
        issue=issue,
        initiator=initiator,
        action="checklist.item_add",
        before=None,
    )
    return item


async def update_item(
    session: AsyncSession,
    item: ChecklistItem,
    *,
    issue: Issue,
    initiator: Actor,
    text: str = UNSET,
    assignee: Actor | None = UNSET,
    deadline: datetime | None = UNSET,
) -> ChecklistItem:
    """Меняет текст, исполнителя и дедлайн пункта; применяются только переданные поля.

    Отметка о выполнении сюда не входит: у неё своё событие
    (`checklist.item_checked`), на которое подписывается автоматика, и складывать её в
    общий `item_updated` значило бы заставить каждый триггер разбирать нагрузку.
    """
    ensure_allowed(initiator, "checklist.item_update", target=item)
    before = events_service.checklist_value(item)

    changed = False
    if is_set(text):
        stored = validate_text(text)
        if stored != item.text:
            item.text = stored
            changed = True
    if is_set(assignee):
        if assignee is not None:
            _require_active(assignee)
        after_id = None if assignee is None else assignee.id
        if after_id != item.assignee_id:
            item.assignee = assignee
            changed = True
    if is_set(deadline):
        stored_deadline = validate_item_deadline(deadline)
        if stored_deadline != item.deadline:
            item.deadline = stored_deadline
            changed = True

    if not changed:
        return item

    await ChecklistRepository(session).flush()
    await events_service.record_checklist_change(
        session,
        item,
        issue=issue,
        initiator=initiator,
        action="checklist.item_update",
        before=before,
    )
    return item


async def set_item_done(
    session: AsyncSession,
    item: ChecklistItem,
    *,
    issue: Issue,
    initiator: Actor,
    is_done: bool,
) -> ChecklistItem:
    """Отмечает пункт выполненным или снимает отметку.

    Кто и когда отметил, проставляется и снимается вместе с самой отметкой: «отметил
    без времени» и «время без отметившего» — состояния, которых не бывает, и раздельные
    присваивания по месту рано или поздно одно из них создали бы.

    Повторная отметка уже отмеченного пункта ничего не меняет и события не даёт, но и
    ошибкой не считается: клиент, не получивший ответ и повторивший запрос, не должен
    получать отказ на выполненное действие.
    """
    action = "checklist.item_check" if is_done else "checklist.item_uncheck"
    ensure_allowed(initiator, action, target=item)
    if item.is_done == is_done:
        return item

    before = events_service.checklist_value(item)
    item.is_done = is_done
    item.checked_by = initiator if is_done else None
    item.checked_at = datetime.now(UTC) if is_done else None
    await ChecklistRepository(session).flush()

    await events_service.record_checklist_change(
        session,
        item,
        issue=issue,
        initiator=initiator,
        action=action,
        before=before,
    )
    return item


async def move_item(
    session: AsyncSession,
    item: ChecklistItem,
    *,
    issue: Issue,
    initiator: Actor,
    after: ChecklistItem | None,
) -> ChecklistItem:
    """Ставит пункт сразу после `after`; `after is None` означает «в начало списка».

    Место задаётся соседом, а не индексом или позицией. Индекс разошёлся бы с
    состоянием списка, который тем временем изменил кто-то ещё, а позиция — внутреннее
    число разреженной шкалы, и клиенту знать её незачем.

    Обычный случай меняет одну строку. Если зазор между соседями исчерпан
    (`position_between` вернул `None`), список перенумеровывается целиком — редкая
    операция, ради которой шкала и разрежена.
    """
    ensure_allowed(initiator, "checklist.item_move", target=item)
    repository = ChecklistRepository(session)
    items = await repository.list_for_issue(issue.id)
    if after is not None and after.id == item.id:
        # Пункт после самого себя — не перемещение, а опечатка клиента. Молчаливое
        # выполнение оставило бы его на месте, и клиент решил бы, что порядок другой.
        return item

    ordered = [existing for existing in items if existing.id != item.id]
    index = 0 if after is None else _index_after(ordered, after)
    if _already_there(items, item, index):
        return item

    before_snapshot = events_service.checklist_value(item)
    previous = ordered[index - 1].position if index > 0 else None
    following = ordered[index].position if index < len(ordered) else None

    position = position_between(previous, following)
    if position is None:
        # Зазор исчерпан: перенумеровываем список целиком, поставив пункт на новое
        # место. Это и есть плата за разреженные позиции — редкая, но настоящая.
        ordered.insert(index, item)
        for existing, fresh in zip(ordered, rebalanced_positions(len(ordered)), strict=True):
            existing.position = fresh
    else:
        item.position = position

    await repository.flush()
    await events_service.record_checklist_change(
        session,
        item,
        issue=issue,
        initiator=initiator,
        action="checklist.item_move",
        before=before_snapshot,
    )
    return item


async def delete_item(
    session: AsyncSession,
    item: ChecklistItem,
    *,
    issue: Issue,
    initiator: Actor,
) -> None:
    """Удаляет пункт насовсем.

    Удаление жёсткое, в отличие от комментария: у пункта нет ни адресата, ни ответов,
    ни ушедшего уведомления, на которые могла бы сослаться плашка «удалён». Факт
    удаления остаётся записью в истории задачи и событием.
    """
    ensure_allowed(initiator, "checklist.item_remove", target=item)
    before = events_service.checklist_value(item)
    # Запись собирается **до** удаления: после него снимок строить уже не из чего.
    await events_service.record_checklist_change(
        session,
        item,
        issue=issue,
        initiator=initiator,
        action="checklist.item_remove",
        before=before,
        removed=True,
    )
    await ChecklistRepository(session).delete(item)


def _index_after(ordered: list[ChecklistItem], after: ChecklistItem) -> int:
    """Место вставки сразу за указанным пунктом.

    Соседа в списке может не оказаться, только если его удалили в этой же транзакции;
    тогда пункт встаёт в конец — это ближе к намерению «после последнего известного»,
    чем отказ на операцию, которую клиент считает выполнимой.
    """
    for index, existing in enumerate(ordered):
        if existing.id == after.id:
            return index + 1
    return len(ordered)


def _already_there(items: list[ChecklistItem], item: ChecklistItem, index: int) -> bool:
    """Стоит ли пункт уже на нужном месте: тогда перемещения не было."""
    current = [existing.id for existing in items].index(item.id)
    return current == index


def _require_active(actor: Actor) -> None:
    """Отключённый актор не может стать исполнителем пункта.

    То же правило, что у исполнителя задачи: уже записанные ссылки на отключённого
    актора остаются, назначать его заново нельзя.
    """
    if not actor.is_active:
        raise ActorInactiveError(
            details={"key": actor.key, "reason": "cannot_be_checklist_assignee"},
        )
