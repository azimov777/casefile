"""Сценарии чеклиста: порядок, отметки, перемещение, перенумерация, события.

Главное здесь — обещание разреженных позиций: обычное перемещение меняет **одну**
строку. Проверяется это не намерением, а счётом изменённых позиций; отдельно
проверяется случай, ради которого шкала и разрежена, — исчерпанный зазор, при котором
список перенумеровывается целиком и порядок обязан сохраниться.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.checklist import ChecklistItem
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.issue import Issue
from app.db.repositories import OutboxRepository
from app.domain.actors import ActorType
from app.domain.checklists import CHECKLIST_CHANGE_FIELD, MAX_CHECKLIST_ITEMS
from app.domain.errors import (
    ActorInactiveError,
    ChecklistItemNotFoundError,
    InvalidChecklistItemError,
)
from app.domain.events import EventType, ObjectType
from app.services import actors as actors_service
from app.services import checklists as service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _texts(session: AsyncSession, issue: Issue, owner: Actor) -> list[str]:
    return [item.text for item in await service.list_items(session, issue, initiator=owner)]


async def _positions(session: AsyncSession, issue: Issue) -> dict[str, int]:
    statement = select(ChecklistItem).where(ChecklistItem.issue_id == issue.id)
    return {item.text: item.position for item in (await session.scalars(statement)).all()}


async def _history(session: AsyncSession, issue: Issue) -> list[ChangelogEntry]:
    statement = (
        select(ChangelogEntry)
        .where(ChangelogEntry.issue_id == issue.id)
        .order_by(ChangelogEntry.created_at, ChangelogEntry.id)
    )
    return list((await session.scalars(statement)).all())


async def _item_events(session: AsyncSession, item: ChecklistItem) -> list[OutboxEvent]:
    return await OutboxRepository(session).list_by_object(
        object_type=ObjectType.CHECKLIST_ITEM.value,
        object_id=item.id,
    )


# --- Список и порядок -------------------------------------------------------------


async def test_items_are_added_to_the_end_in_order(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    for text in ("Первый", "Второй", "Третий"):
        await service.add_item(db_session, issue, initiator=owner, text=text)

    assert await _texts(db_session, issue, owner) == ["Первый", "Второй", "Третий"]


async def test_the_item_limit_stops_the_hundred_and_first(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Потолок нужен потому, что чеклист отдаётся целиком, без пагинации."""
    issue = await make_issue()
    db_session.add_all(
        ChecklistItem(issue_id=issue.id, text=f"Пункт {number}", position=number + 1)
        for number in range(MAX_CHECKLIST_ITEMS)
    )
    await db_session.flush()

    with pytest.raises(InvalidChecklistItemError) as error:
        await service.add_item(db_session, issue, initiator=owner, text="Лишний")
    assert error.value.details["reason"] == "too_many_items"


async def test_an_item_of_another_issue_is_invisible(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    item = await service.add_item(db_session, first, initiator=owner, text="Пункт")

    with pytest.raises(ChecklistItemNotFoundError):
        await service.get_item(db_session, second, item.id)


# --- Отметка ----------------------------------------------------------------------


async def test_checking_records_who_and_when_and_unchecking_clears_both(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """«Кто отметил» и «когда» живут вместе: состояния с одним из них не бывает."""
    issue = await make_issue()
    item = await service.add_item(db_session, issue, initiator=owner, text="Прогнать тесты")

    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=True)
    assert item.is_done
    assert item.checked_by is not None and item.checked_by.key == "owner"
    assert item.checked_at is not None

    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=False)
    assert not item.is_done
    assert item.checked_by is None
    assert item.checked_at is None


async def test_checking_an_already_checked_item_is_a_no_op(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Повтор не ошибка и не событие: клиент, повторивший запрос, не должен видеть отказ."""
    issue = await make_issue()
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")
    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=True)

    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=True)

    events = [event.event_type for event in await _item_events(db_session, item)]
    assert events == [
        EventType.CHECKLIST_ITEM_ADDED.value,
        EventType.CHECKLIST_ITEM_CHECKED.value,
    ]


async def test_checking_and_unchecking_are_separate_event_types(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Два типа, а не один с флагом: автоматика подписывается на «пункт выполнен»."""
    issue = await make_issue()
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")

    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=True)
    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=False)

    events = [event.event_type for event in await _item_events(db_session, item)]
    assert events[-2:] == [
        EventType.CHECKLIST_ITEM_CHECKED.value,
        EventType.CHECKLIST_ITEM_UNCHECKED.value,
    ]


# --- Правка -----------------------------------------------------------------------


async def test_updating_applies_only_the_given_fields(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    agent, _ = await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="release_bot",
        display_name="Release bot",
    )
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")

    await service.update_item(
        db_session,
        item,
        issue=issue,
        initiator=owner,
        assignee=agent,
    )

    assert item.text == "Пункт"
    assert item.assignee is not None and item.assignee.key == "release_bot"

    await service.update_item(db_session, item, issue=issue, initiator=owner, assignee=None)
    assert item.assignee is None


async def test_an_update_that_changes_nothing_writes_nothing(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")

    await service.update_item(db_session, item, issue=issue, initiator=owner, text="  Пункт  ")

    assert len(await _item_events(db_session, item)) == 1


async def test_a_disabled_actor_cannot_be_assigned_to_an_item(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """То же правило, что у исполнителя задачи: отключённого назначать нельзя."""
    issue = await make_issue()
    retired, _ = await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="retired_bot",
        display_name="Retired",
    )
    retired.is_active = False
    await db_session.flush()
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")

    with pytest.raises(ActorInactiveError):
        await service.update_item(db_session, item, issue=issue, initiator=owner, assignee=retired)


# --- Перемещение ------------------------------------------------------------------


async def test_moving_an_item_touches_a_single_row(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Обещание разреженных позиций: перестановка меняет позицию одного пункта.

    Проверяется счётом, а не намерением: сплошная нумерация переписала бы половину
    списка, и тест это увидел бы.
    """
    issue = await make_issue()
    for text in ("Первый", "Второй", "Третий"):
        await service.add_item(db_session, issue, initiator=owner, text=text)
    before = await _positions(db_session, issue)

    moved = next(
        item
        for item in await service.list_items(db_session, issue, initiator=owner)
        if item.text == "Третий"
    )
    await service.move_item(db_session, moved, issue=issue, initiator=owner, after=None)

    after = await _positions(db_session, issue)
    changed = [text for text, position in after.items() if before[text] != position]
    assert changed == ["Третий"]
    assert await _texts(db_session, issue, owner) == ["Третий", "Первый", "Второй"]


async def test_moving_after_a_neighbour_puts_the_item_right_behind_it(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    for text in ("Первый", "Второй", "Третий"):
        await service.add_item(db_session, issue, initiator=owner, text=text)
    items = {
        item.text: item for item in await service.list_items(db_session, issue, initiator=owner)
    }

    await service.move_item(
        db_session,
        items["Первый"],
        issue=issue,
        initiator=owner,
        after=items["Второй"],
    )

    assert await _texts(db_session, issue, owner) == ["Второй", "Первый", "Третий"]


async def test_moving_an_item_to_where_it_already_is_changes_nothing(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    first = await service.add_item(db_session, issue, initiator=owner, text="Первый")
    second = await service.add_item(db_session, issue, initiator=owner, text="Второй")

    await service.move_item(db_session, second, issue=issue, initiator=owner, after=first)

    assert len(await _item_events(db_session, second)) == 1


async def test_an_exhausted_gap_renumbers_the_list_and_keeps_the_order(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Случай, ради которого шкала разрежена: между соседями больше нет места.

    Позиции ставятся вплотную руками, потом пункт переносится в середину. Обычный путь
    здесь невозможен, поэтому список перенумеровывается целиком — и порядок обязан
    остаться тем, который попросил клиент.
    """
    issue = await make_issue()
    first = await service.add_item(db_session, issue, initiator=owner, text="Первый")
    second = await service.add_item(db_session, issue, initiator=owner, text="Второй")
    third = await service.add_item(db_session, issue, initiator=owner, text="Третий")
    first.position, second.position, third.position = 10, 11, 12
    await db_session.flush()

    await service.move_item(db_session, third, issue=issue, initiator=owner, after=first)

    assert await _texts(db_session, issue, owner) == ["Первый", "Третий", "Второй"]
    positions = await _positions(db_session, issue)
    # Зазоры восстановлены: следующая вставка снова уложится в одну строку.
    assert len(set(positions.values())) == 3
    assert min(positions.values()) > 0


# --- Удаление и события -----------------------------------------------------------


async def test_removing_an_item_is_hard_and_leaves_a_history_entry(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """У пункта нет ни адресата, ни ушедшего уведомления — плашка ему не нужна."""
    issue = await make_issue()
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")

    await service.delete_item(db_session, item, issue=issue, initiator=owner)

    assert await service.list_items(db_session, issue, initiator=owner) == []
    entry = (await _history(db_session, issue))[-1]
    assert entry.event_type == EventType.CHECKLIST_ITEM_REMOVED.value
    assert entry.changes[0]["field"] == CHECKLIST_CHANGE_FIELD
    assert entry.changes[0]["before"]["text"] == "Пункт"
    assert entry.changes[0]["after"] is None


async def test_the_event_carries_both_states_of_the_item(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Подписчику нужен переход «не выполнен → выполнен», а не только текущее состояние.

    Иначе за прежним состоянием он пошёл бы в базу и прочитал бы то, что там лежит на
    момент доставки, а не на момент события.
    """
    issue = await make_issue()
    item = await service.add_item(db_session, issue, initiator=owner, text="Пункт")
    await service.set_item_done(db_session, item, issue=issue, initiator=owner, is_done=True)

    checked = (await _item_events(db_session, item))[-1]
    assert checked.event_type == EventType.CHECKLIST_ITEM_CHECKED.value
    assert checked.payload["previous"]["done"] is False
    assert checked.payload["item"]["is_done"] is True
    assert checked.payload["item"]["checked_by"] == "owner"
    assert checked.payload["issue"]["key"] == issue.key


async def test_deleting_an_issue_takes_its_checklist_with_it(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    from app.services import issues as issues_service

    issue = await make_issue()
    await service.add_item(db_session, issue, initiator=owner, text="Пункт")

    await issues_service.delete_issue(db_session, issue, initiator=owner)
    await db_session.flush()

    remaining = await db_session.scalars(
        select(ChecklistItem).where(ChecklistItem.issue_id == issue.id)
    )
    assert list(remaining) == []
