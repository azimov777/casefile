"""Сценарии уведомлений: маршрутизация по подпискам, схлопывание, ожидание, инбокс.

События здесь настоящие: тест меняет задачу сценарием, забирает событие из outbox и
отдаёт его подписчику — тем же путём, каким это делает воркер. Собирать конверт руками
можно было бы быстрее, но тогда проверялась бы адресация по выдуманной нагрузке, а не
по той, которую в самом деле кладёт `app/services/events.py`.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import OutboxEvent
from app.db.models.issue import Issue
from app.db.models.notification import Notification
from app.db.models.queue import Queue
from app.domain.actors import ActorType
from app.domain.catalogs import CatalogKind
from app.domain.errors import (
    InvalidWaitTimeoutError,
    NotificationNotFoundError,
    SubscriptionExistsError,
)
from app.domain.events import EventType
from app.domain.issues import IssuePriority
from app.domain.notifications import SubscriptionScope
from app.services import actors as actors_service
from app.services import comments as comments_service
from app.services import issues as issues_service
from app.services import notifications as service
from app.services import queues as queues_service
from app.services.event_bus import EventEnvelope


@pytest.fixture
def make_actor(db_session: AsyncSession) -> Callable[..., Awaitable[Actor]]:
    """Фабрика акторов: адресаты уведомлений в этих тестах разные, и их нужно много."""

    async def _make(key: str, actor_type: ActorType = ActorType.AGENT) -> Actor:
        actor, _ = await actors_service.ensure_actor(
            db_session,
            actor_type=actor_type,
            key=key,
            display_name=key.title(),
        )
        return actor

    return _make


async def deliver_new_events(session: AsyncSession, *, after: int = 0) -> list[Notification]:
    """Отдаёт подписчику уведомлений все события outbox, начиная с указанного номера.

    Тем же путём, что и воркер: конверт собирается из строки outbox, а не пишется
    руками. Иначе тест проверял бы адресацию по выдуманной нагрузке.
    """
    events = list(
        (
            await session.scalars(
                select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)
            )
        )
        .unique()
        .all()
    )
    created: list[Notification] = []
    for event in events[after:]:
        created.extend(
            await service.dispatch_event(
                session,
                EventEnvelope(
                    id=event.id,
                    event_type=event.event_type,
                    object_type=event.object_type,
                    object_id=event.object_id,
                    object_key=event.object_key,
                    actor_key=event.actor_key,
                    payload=dict(event.payload),
                    created_at=event.created_at,
                ),
            )
        )
    return created


async def outbox_size(session: AsyncSession) -> int:
    return len((await session.scalars(select(OutboxEvent.id))).all())


async def inbox_of(session: AsyncSession, actor: Actor) -> list[Notification]:
    page = await service.list_notifications(session, initiator=actor)
    return page.items


class TestRouting:
    async def test_being_assigned_reaches_the_new_assignee(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        bob = await make_actor("bob")
        issue = await make_issue()
        seen = await outbox_size(db_session)

        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, bob)
        assert [item.event_type for item in inbox] == [EventType.ISSUE_ASSIGNED]
        assert inbox[0].issue_key == issue.key
        assert inbox[0].details["assignee"] == "bob"

    async def test_a_mention_reaches_the_mentioned_actor(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        dave = await make_actor("dave")
        issue = await make_issue()
        seen = await outbox_size(db_session)

        await comments_service.add_comment(
            db_session,
            issue,
            initiator=owner,
            body="Посмотри, пожалуйста, @dave",
        )
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, dave)
        assert [item.event_type for item in inbox] == [EventType.COMMENT_CREATED]
        assert inbox[0].details["scope"] == SubscriptionScope.MENTION.value

    async def test_a_mention_outranks_being_the_assignee(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Причина в уведомлении записывается одна, и это должна быть самая адресная.

        «Меня позвали лично» и «изменилось что-то в моей задаче» — разные поводы
        вмешаться, и агент отличает их по этому полю, а не по тексту.
        """
        bob = await make_actor("bob")
        issue = await make_issue(assignee=bob)
        seen = await outbox_size(db_session)

        await comments_service.add_comment(
            db_session,
            issue,
            initiator=owner,
            body="Посмотри, пожалуйста, @bob",
        )
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, bob)
        assert inbox[0].details["scope"] == SubscriptionScope.MENTION.value

    async def test_a_status_change_reaches_the_follower(
        self,
        db_session: AsyncSession,
        owner: Actor,
        queue: Queue,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        carol = await make_actor("carol")
        issue = await make_issue()
        await issues_service.add_follower(db_session, issue, initiator=owner, actor=carol)
        seen = await outbox_size(db_session)

        # Настоящим переходом процесса, а не присваиванием статуса: событие
        # `issue.status_changed` рождается только на этом пути.
        await issues_service.apply_issue_changes(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(
                status=await _status(db_session, "in_progress", initiator=owner),
            ),
            action="issue.transition",
        )
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, carol)
        assert [item.event_type for item in inbox] == [EventType.ISSUE_STATUS_CHANGED]

    async def test_own_actions_do_not_notify_by_default(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
    ) -> None:
        """Иначе агент, обновивший задачу, немедленно разбудит сам себя своим изменением."""
        issue = await make_issue()
        seen = await outbox_size(db_session)

        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(summary="Другое название"),
        )
        await deliver_new_events(db_session, after=seen)

        assert await inbox_of(db_session, owner) == []

    async def test_own_actions_notify_when_the_subscription_says_so(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
    ) -> None:
        await service.create_subscription(
            db_session,
            initiator=owner,
            scope=SubscriptionScope.AUTHOR,
            notify_own_actions=True,
        )
        issue = await make_issue()
        seen = await outbox_size(db_session)

        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(summary="Другое название"),
        )
        await deliver_new_events(db_session, after=seen)

        assert [item.event_type for item in await inbox_of(db_session, owner)] == [
            EventType.ISSUE_UPDATED
        ]

    async def test_the_system_actor_never_gets_an_inbox(
        self,
        db_session: AsyncSession,
        system_actor: Actor,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Правила ходят от его имени, и без отсечения он собрал бы копию всего потока."""
        await service.create_subscription(
            db_session,
            initiator=system_actor,
            scope=SubscriptionScope.ALL,
        )
        issue = await make_issue()
        seen = await outbox_size(db_session)

        await issues_service.assign_issue(
            db_session,
            issue,
            initiator=owner,
            assignee=await make_actor("bob"),
        )
        await deliver_new_events(db_session, after=seen)

        assert await inbox_of(db_session, system_actor) == []

    async def test_a_comment_from_automation_reaches_people(
        self,
        db_session: AsyncSession,
        system_actor: Actor,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
    ) -> None:
        """Комментарий автоматики приходит обычным `comment.created` от системного актора.

        Правило «не уведомлять о собственных действиях» обязано глушить его только
        самому системному актору: иначе сообщения автоматики не дойдут ни до кого — а
        они и есть главный способ, которым она разговаривает с человеком.
        """
        issue = await make_issue(initiator=owner)
        seen = await outbox_size(db_session)

        await comments_service.add_comment(
            db_session,
            issue,
            initiator=system_actor,
            body="Задача закрыта правилом close_children_with_parent",
        )
        await deliver_new_events(db_session, after=seen)

        assert [item.event_type for item in await inbox_of(db_session, owner)] == [
            EventType.COMMENT_CREATED
        ]

    async def test_a_queue_subscription_catches_someone_elses_issue(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        watcher = await make_actor("watcher")
        await service.create_subscription(
            db_session,
            initiator=watcher,
            scope=SubscriptionScope.QUEUE,
            scope_key="TRK",
        )
        seen = await outbox_size(db_session)

        issue = await make_issue()
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, watcher)
        assert [item.issue_key for item in inbox] == [issue.key]
        assert inbox[0].details["scope"] == SubscriptionScope.QUEUE.value

    async def test_a_disabled_role_subscription_switches_the_default_off(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Выключенная подписка на роль — единственный способ отказаться от умолчания."""
        bob = await make_actor("bob")
        await service.create_subscription(
            db_session,
            initiator=bob,
            scope=SubscriptionScope.ASSIGNEE,
            is_enabled=False,
        )
        issue = await make_issue()
        seen = await outbox_size(db_session)

        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)

        assert await inbox_of(db_session, bob) == []

    async def test_a_subscription_narrowed_by_event_type_filters_the_rest(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        bob = await make_actor("bob")
        await service.create_subscription(
            db_session,
            initiator=bob,
            scope=SubscriptionScope.ASSIGNEE,
            event_types=[EventType.ISSUE_STATUS_CHANGED.value],
        )
        issue = await make_issue(assignee=bob)
        seen = await outbox_size(db_session)

        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(summary="Другое название"),
        )
        await deliver_new_events(db_session, after=seen)

        assert await inbox_of(db_session, bob) == []


class TestDigest:
    async def test_repeated_changes_of_one_issue_merge_into_one_record(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Десять правок за минуту не должны давать десять писем одному адресату."""
        bob = await make_actor("bob")
        issue = await make_issue(assignee=bob)
        seen = await outbox_size(db_session)

        for number in range(3):
            await issues_service.update_issue(
                db_session,
                issue,
                initiator=owner,
                changes=issues_service.IssueChanges(summary=f"Название {number}"),
            )
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, bob)
        assert len(inbox) == 1
        assert inbox[0].count == 3
        # Счётчик виден и агенту, читающему подробности, а не только в колонке.
        assert inbox[0].details["merged"] == 3

    async def test_a_read_notification_is_never_reopened(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Дописать событие в прочитанное значило бы изменить увиденное задним числом."""
        bob = await make_actor("bob")
        issue = await make_issue(assignee=bob)
        seen = await outbox_size(db_session)

        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(summary="Первое"),
        )
        await deliver_new_events(db_session, after=seen)
        await service.mark_read(db_session, initiator=bob)

        seen = await outbox_size(db_session)
        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(summary="Второе"),
        )
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, bob)
        assert [item.count for item in inbox] == [1, 1]
        assert [item.is_read for item in inbox] == [True, False]

    async def test_different_issues_stay_separate(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        bob = await make_actor("bob")
        first = await make_issue(assignee=bob, summary="Первая")
        second = await make_issue(assignee=bob, summary="Вторая")
        seen = await outbox_size(db_session)

        for issue in (first, second):
            await issues_service.update_issue(
                db_session,
                issue,
                initiator=owner,
                changes=issues_service.IssueChanges(priority=IssuePriority.MAJOR),
            )
        await deliver_new_events(db_session, after=seen)

        inbox = await inbox_of(db_session, bob)
        assert sorted(item.issue_key for item in inbox) == sorted([first.key, second.key])


class TestInbox:
    async def test_marking_the_whole_inbox_read_needs_no_identifiers(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        bob = await make_actor("bob")
        issue = await make_issue()
        seen = await outbox_size(db_session)
        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)

        marked = await service.mark_read(db_session, initiator=bob)

        assert marked == 1
        assert await service.count_unread(db_session, initiator=bob) == 0

    async def test_marking_read_twice_is_not_an_error(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Клиент, не получивший ответ и повторивший запрос, не должен получать отказ."""
        bob = await make_actor("bob")
        issue = await make_issue()
        seen = await outbox_size(db_session)
        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)

        assert await service.mark_read(db_session, initiator=bob) == 1
        assert await service.mark_read(db_session, initiator=bob) == 0

    async def test_marking_someone_elses_notification_is_not_found(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        bob = await make_actor("bob")
        issue = await make_issue()
        seen = await outbox_size(db_session)
        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)
        theirs = (await inbox_of(db_session, bob))[0]

        with pytest.raises(NotificationNotFoundError):
            await service.mark_read(db_session, initiator=owner, notification_ids=[theirs.id])

    async def test_an_unknown_identifier_is_not_found(
        self,
        db_session: AsyncSession,
        owner: Actor,
    ) -> None:
        with pytest.raises(NotificationNotFoundError):
            await service.mark_read(
                db_session,
                initiator=owner,
                notification_ids=[uuid.uuid4()],
            )


class TestDirectNotification:
    async def test_an_addressed_message_lands_in_the_inbox(
        self,
        db_session: AsyncSession,
        make_actor: Callable[..., Awaitable[Actor]],
        make_issue: Callable[..., Awaitable[Issue]],
    ) -> None:
        bob = await make_actor("bob")
        issue = await make_issue()

        notification = await service.notify_actor(
            db_session,
            actor=bob,
            body="Deadline is tomorrow",
            issue=issue,
        )

        assert notification is not None
        assert notification.issue_key == issue.key
        assert [item.body for item in await inbox_of(db_session, bob)] == ["Deadline is tomorrow"]

    async def test_a_message_to_the_system_actor_is_refused(
        self,
        db_session: AsyncSession,
        system_actor: Actor,
    ) -> None:
        """Не молча: вызывающий код обязан показать этот исход, а не потерять сообщение."""
        assert await service.notify_actor(db_session, actor=system_actor, body="hi") is None
        assert await inbox_of(db_session, system_actor) == []


class TestSubscriptions:
    async def test_a_duplicate_scope_is_a_conflict(
        self,
        db_session: AsyncSession,
        owner: Actor,
    ) -> None:
        await service.create_subscription(
            db_session,
            initiator=owner,
            scope=SubscriptionScope.QUEUE,
            scope_key="TRK",
        )

        with pytest.raises(SubscriptionExistsError):
            await service.create_subscription(
                db_session,
                initiator=owner,
                scope=SubscriptionScope.QUEUE,
                scope_key="TRK",
            )

    async def test_two_role_subscriptions_do_not_collide_on_null_keys(
        self,
        db_session: AsyncSession,
        owner: Actor,
    ) -> None:
        """`NULLS NOT DISTINCT` держит уникальность, но только внутри одной области.

        Без него две подписки «я исполнитель» прошли бы обе; с ним — но без учёта
        области — не прошла бы вторая роль вовсе.
        """
        await service.create_subscription(
            db_session,
            initiator=owner,
            scope=SubscriptionScope.ASSIGNEE,
        )
        await service.create_subscription(
            db_session,
            initiator=owner,
            scope=SubscriptionScope.FOLLOWER,
        )

        page = await service.list_subscriptions(db_session, initiator=owner)
        assert sorted(item.scope for item in page.items) == [
            SubscriptionScope.ASSIGNEE,
            SubscriptionScope.FOLLOWER,
        ]

    async def test_a_new_actor_has_no_rows_but_still_gets_notified(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Правила по умолчанию живут в коде: пустой список — это «всё как обычно»."""
        bob = await make_actor("bob")
        assert (await service.list_subscriptions(db_session, initiator=bob)).items == []

        issue = await make_issue()
        seen = await outbox_size(db_session)
        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)

        assert len(await inbox_of(db_session, bob)) == 1


class TestWait:
    async def test_it_returns_at_once_when_the_inbox_is_not_empty(
        self,
        db_session: AsyncSession,
        owner: Actor,
        make_issue: Callable[..., Awaitable[Issue]],
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        bob = await make_actor("bob")
        issue = await make_issue()
        seen = await outbox_size(db_session)
        await issues_service.assign_issue(db_session, issue, initiator=owner, assignee=bob)
        await deliver_new_events(db_session, after=seen)

        outcome = await service.wait_for_notifications(db_session, initiator=bob, timeout=5)

        assert not outcome.timed_out
        assert len(outcome.notifications) == 1

    async def test_it_gives_up_by_timeout_with_an_empty_result(
        self,
        db_session: AsyncSession,
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Пустой ответ по таймауту — нормальный исход, а не ошибка."""
        bob = await make_actor("bob")

        outcome = await service.wait_for_notifications(db_session, initiator=bob, timeout=1)

        assert outcome.timed_out
        assert outcome.notifications == []
        assert outcome.waited >= 1

    async def test_it_wakes_up_as_soon_as_a_notification_appears(
        self,
        db_session: AsyncSession,
        make_actor: Callable[..., Awaitable[Actor]],
    ) -> None:
        """Ожидание возвращает управление по оповещению, а не по истечении паузы.

        Таймаут здесь заведомо больше, чем нужно, поэтому возврат раньше него и есть
        доказательство: сработал сигнал, а не опрос до конца отведённого времени.
        """
        import asyncio

        bob = await make_actor("bob")

        async def deliver_later() -> None:
            await asyncio.sleep(0.2)
            await service.notify_actor(db_session, actor=bob, body="Woke you up")

        waiting = asyncio.create_task(
            service.wait_for_notifications(db_session, initiator=bob, timeout=30)
        )
        await deliver_later()
        outcome = await waiting

        assert not outcome.timed_out
        assert [item.body for item in outcome.notifications] == ["Woke you up"]
        assert outcome.waited < 30

    async def test_a_timeout_beyond_the_ceiling_is_an_error(
        self,
        db_session: AsyncSession,
        owner: Actor,
    ) -> None:
        """Не тихое срезание: клиент решил бы, что уведомлений не было, а его не ждали."""
        with pytest.raises(InvalidWaitTimeoutError):
            await service.wait_for_notifications(db_session, initiator=owner, timeout=100_000)


async def _status(session: AsyncSession, ref: str, *, initiator: Actor) -> Any:
    """Ссылка справочника в запись статуса — тем же разрешением, что и в API."""
    return await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.STATUS,
        ref,
        initiator=initiator,
    )
