"""Журнал изменений и outbox: запись в одной транзакции с самим изменением.

Главное свойство, ради которого всё построено, проверяется прямо: откат транзакции не
оставляет ни записи истории, ни события. Если бы рассылка шла из обработчика запроса,
подписчик уже знал бы об изменении, которого не случилось.

Второе по важности — самодостаточность полезной нагрузки: в ней снимок задачи **после**
изменения и список «было → стало», и она обязана быть обычным JSON, потому что переживёт
транзакцию, в которой родилась.
"""

import json
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.repositories import OutboxRepository
from app.domain.actors import ActorType
from app.domain.catalogs import CatalogKind
from app.domain.events import EventType, ObjectType, OutboxStatus
from app.domain.issues import IssueField, IssuePriority
from app.services import actors as actors_service
from app.services import catalogs as catalogs_service
from app.services import events as events_service
from app.services import issue_usage
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services.issues import IssueChanges

MakeIssue = Callable[..., Awaitable[Issue]]


async def _status(session: AsyncSession, owner: Actor, ref: str):
    return await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, ref, initiator=owner
    )


async def _history(session: AsyncSession, issue: Issue) -> list[ChangelogEntry]:
    statement = (
        select(ChangelogEntry)
        .where(ChangelogEntry.issue_id == issue.id)
        .order_by(ChangelogEntry.created_at, ChangelogEntry.id)
    )
    return list((await session.scalars(statement)).all())


async def _events(session: AsyncSession, issue: Issue) -> list[OutboxEvent]:
    return await OutboxRepository(session).list_by_object(
        object_type=ObjectType.ISSUE.value,
        object_id=issue.id,
    )


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.scalar(select(func.count()).select_from(model))) or 0


# --- Создание ---------------------------------------------------------------------


async def test_creating_an_issue_starts_its_history_and_emits_an_event(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """У новой задачи в истории одна запись, а в outbox — одно событие `issue.created`."""
    issue = await make_issue(summary="Починить выдачу ключей")

    history = await _history(db_session, issue)
    events = await _events(db_session, issue)

    assert [entry.event_type for entry in history] == [EventType.ISSUE_CREATED]
    # У создания нет «было»: состояние новой задачи целиком уезжает в событие, а
    # псевдоизменения по каждому полю удвоили бы карточку задачи в её же истории.
    assert history[0].changes == []
    assert [event.event_type for event in events] == [EventType.ISSUE_CREATED]


async def test_the_payload_carries_the_whole_issue_and_is_plain_json(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Нагрузка самодостаточна и сериализуема: подписчику не нужно идти в базу."""
    issue = await make_issue(summary="Починить выдачу ключей", tags=["release"])

    event = (await _events(db_session, issue))[0]
    snapshot = event.payload["issue"]

    assert snapshot["key"] == issue.key
    assert snapshot["queue"] == "TRK"
    assert snapshot["status"] == "open"
    assert snapshot["author"] == owner.key
    assert snapshot["tags"] == ["release"]
    assert snapshot["version"] == 1
    assert event.actor_key == owner.key
    assert event.object_key == issue.key
    # Событие переживает транзакцию, поэтому в нагрузке не должно быть ни ORM-объектов,
    # ни `datetime`: и то и другое не кладётся в JSONB и не доедет до подписчика.
    assert json.loads(json.dumps(event.payload)) == event.payload


# --- Изменение --------------------------------------------------------------------


async def test_an_update_records_every_field_that_actually_changed(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Одна мутация — одна запись истории со всеми изменёнными полями внутри."""
    issue = await make_issue(summary="Было")

    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Стало", priority=IssuePriority.BLOCKER),
    )

    history = await _history(db_session, issue)
    assert len(history) == 2
    entry = history[-1]
    assert entry.event_type == EventType.ISSUE_UPDATED
    assert entry.actor_id == owner.id
    assert {change["field"] for change in entry.changes} == {"summary", "priority"}
    assert {"field": "summary", "before": "Было", "after": "Стало"} in entry.changes

    event = (await _events(db_session, issue))[-1]
    assert event.event_type == EventType.ISSUE_UPDATED
    assert sorted(event.payload["fields"]) == ["priority", "summary"]
    assert event.payload["issue"]["summary"] == "Стало"


async def test_a_status_change_gets_its_own_event_type(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Смена статуса — отдельный тип события: на него подписано почти всё."""
    issue = await make_issue()
    target = await _status(db_session, owner, "in_progress")

    await issues_service.update_issue(
        db_session, issue, initiator=owner, changes=IssueChanges(status=target)
    )

    event = (await _events(db_session, issue))[-1]
    assert event.event_type == EventType.ISSUE_STATUS_CHANGED
    assert event.payload["changes"] == [
        {"field": IssueField.STATUS.value, "before": "open", "after": "in_progress"}
    ]


async def test_assigning_and_following_get_the_types_of_their_actions(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """У назначения свой тип события, у подписки — общий `issue.updated`."""
    issue = await make_issue()
    agent, _ = await actors_service.ensure_actor(
        db_session, actor_type=ActorType.AGENT, key="release_bot", display_name="Release bot"
    )

    await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=agent)
    await issues_service.add_follower(db_session, issue, initiator=owner, actor=agent)

    types = [event.event_type for event in await _events(db_session, issue)]
    assert types == [
        EventType.ISSUE_CREATED,
        EventType.ISSUE_ASSIGNED,
        EventType.ISSUE_UPDATED,
    ]


async def test_a_change_that_changes_nothing_leaves_no_trace(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Клиент прислал то, что уже стоит: ни записи истории, ни события.

    Иначе журнал заполнился бы строками «сменил приоритет с normal на normal», а
    правило автоматики срабатывало бы на изменение, которого не было.
    """
    issue = await make_issue(summary="Было")

    mutation = await issues_service.update_issue(
        db_session, issue, initiator=owner, changes=IssueChanges(summary="Было")
    )

    assert not mutation.changed
    assert len(await _history(db_session, issue)) == 1
    assert len(await _events(db_session, issue)) == 1


# --- Удаление ---------------------------------------------------------------------


async def test_deleting_keeps_the_event_and_takes_the_history_along(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """История уезжает вместе с задачей, событие об удалении остаётся.

    Ссылки на задачу у события нет намеренно: внешний ключ унёс бы каскадом ровно то
    событие, ради которого подписчик и нужен.
    """
    issue = await make_issue(summary="Удаляемая")
    issue_id = issue.id
    issue_key = issue.key

    await issues_service.delete_issue(db_session, issue, initiator=owner)

    remaining = await db_session.scalar(
        select(func.count()).select_from(ChangelogEntry).where(ChangelogEntry.issue_id == issue_id)
    )
    assert remaining == 0

    events = await OutboxRepository(db_session).list_by_object(
        object_type=ObjectType.ISSUE.value, object_id=issue_id
    )
    assert events[-1].event_type == EventType.ISSUE_DELETED
    assert events[-1].payload["issue"]["key"] == issue_key
    assert events[-1].payload["issue"]["summary"] == "Удаляемая"


# --- Атомарность ------------------------------------------------------------------


async def test_a_rollback_leaves_neither_the_entry_nor_the_event(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Ради этого outbox и существует: откат уносит изменение вместе со следами.

    Проверяется вложенной транзакцией — тем же механизмом, которым откатывается
    неудавшийся HTTP-запрос: сначала изменение и его следы появляются, потом откат
    убирает всё разом.
    """
    issue = await make_issue()
    history_before = await _count(db_session, ChangelogEntry)
    events_before = await _count(db_session, OutboxEvent)

    savepoint = await db_session.begin_nested()
    await issues_service.update_issue(
        db_session, issue, initiator=owner, changes=IssueChanges(summary="Откатится назад")
    )
    assert await _count(db_session, ChangelogEntry) == history_before + 1
    assert await _count(db_session, OutboxEvent) == events_before + 1
    await savepoint.rollback()

    assert await _count(db_session, ChangelogEntry) == history_before
    assert await _count(db_session, OutboxEvent) == events_before


# --- Массовый перенос -------------------------------------------------------------


async def test_a_mass_move_writes_history_per_issue_and_one_event_for_all(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    """Осознанная асимметрия: журнал — по задаче, событие — одно на весь перенос.

    История ведётся по задаче, и дыра в ней недопустима. Шина же кормит автоматику и
    уведомления, где сотня одинаковых `issue.status_changed` означала бы сотню
    уведомлений об административной операции.
    """
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    source = await _status(db_session, owner, "open")
    target = await _status(db_session, owner, "in_progress")

    moved = await catalogs_service.move_issues(
        db_session, initiator=owner, source=source, target=target, queue=queue
    )

    assert moved.moved == 2
    for issue in (first, second):
        entry = (await _history(db_session, issue))[-1]
        assert entry.event_type == EventType.ISSUE_STATUS_CHANGED
        assert entry.changes == [{"field": "status", "before": "open", "after": "in_progress"}]
        # Событий на задачу перенос не порождает — только запись в её истории.
        assert [event.event_type for event in await _events(db_session, issue)] == [
            EventType.ISSUE_CREATED
        ]

    aggregate = await OutboxRepository(db_session).list_by_object(
        object_type=ObjectType.STATUS.value, object_id=source.id
    )
    assert len(aggregate) == 1
    assert aggregate[0].event_type == EventType.STATUS_ISSUES_MOVED
    assert aggregate[0].payload["count"] == 2
    assert sorted(aggregate[0].payload["issues"]) == sorted([first.key, second.key])
    assert aggregate[0].payload["status"] == {"from": "open", "to": "in_progress"}
    assert aggregate[0].payload["queue"] == "TRK"


async def test_a_move_that_touches_nothing_writes_nothing(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    """Перенос без задач не должен оставлять пустого события."""
    source = await _status(db_session, owner, "closed")
    target = await _status(db_session, owner, "open")
    events_before = await _count(db_session, OutboxEvent)

    moved = await issue_usage.move_issues_to_status(
        db_session, initiator=owner, source=source, target=target, queue=queue
    )

    assert moved == 0
    assert await _count(db_session, OutboxEvent) == events_before


# --- Чтение истории ---------------------------------------------------------------


async def test_history_is_read_from_oldest_to_newest(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Порядок хронологический и устойчивый внутри одной транзакции.

    Внутри транзакции `now()` одинаков для всех строк, поэтому у записей истории время
    ставит `clock_timestamp()`. Без него две записи одной транзакции сортировались бы
    по случайным UUID, и история показывалась бы задом наперёд примерно в половине
    случаев.
    """
    issue = await make_issue()
    for summary in ("Второе", "Третье"):
        await issues_service.update_issue(
            db_session, issue, initiator=owner, changes=IssueChanges(summary=summary)
        )

    page = await events_service.list_changelog(db_session, issue, initiator=owner)

    assert [entry.event_type for entry in page.items] == [
        EventType.ISSUE_CREATED,
        EventType.ISSUE_UPDATED,
        EventType.ISSUE_UPDATED,
    ]
    assert [entry.changes[0]["after"] for entry in page.items[1:]] == ["Второе", "Третье"]


async def test_history_is_paginated_by_cursor(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """История листается тем же курсором, что и всё остальное в проекте."""
    issue = await make_issue()
    await issues_service.update_issue(
        db_session, issue, initiator=owner, changes=IssueChanges(summary="Второе")
    )

    first = await events_service.list_changelog(db_session, issue, initiator=owner, limit=1)
    assert len(first.items) == 1
    assert first.next_cursor is not None

    second = await events_service.list_changelog(
        db_session, issue, initiator=owner, limit=1, cursor=first.next_cursor
    )
    assert len(second.items) == 1
    assert second.items[0].id != first.items[0].id
    assert second.next_cursor is None


async def test_the_status_of_a_fresh_event_is_pending(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Новое событие ждёт воркера: попыток нет, никому не доставлено."""
    issue = await make_issue()

    event = (await _events(db_session, issue))[0]

    assert event.status is OutboxStatus.PENDING
    assert event.attempts == 0
    assert event.delivered_to == []
    assert event.processed_at is None
