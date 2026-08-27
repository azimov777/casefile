"""Шина событий: реестр подписчиков, доставка, изоляция и повторы.

Три свойства проверяются прицельно, потому что каждое из них ломается молча.

Первое: падение одного подписчика не мешает остальным — ни вызвать их, ни зафиксировать
их работу. Второе: повтор идёт только по тем, кто ещё не отработал, иначе упавший вебхук
заставил бы автоматику сработать дважды. Третье: событие, обработка которого не
зафиксировалась, снова становится необработанным — на этом держится переживание
перезапуска.

Реестр в тестах всегда свой: глобальный общий на процесс, и тесты, чистящие его,
зависели бы друг от друга.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import OutboxEvent
from app.db.models.issue import Issue
from app.domain.actors import ActorType
from app.domain.events import EventType, OutboxStatus
from app.services import actors as actors_service
from app.services import events as events_service
from app.services import issues as issues_service
from app.services.event_bus import EventEnvelope, SubscriberRegistry
from app.services.events import RetryPolicy
from app.services.issues import IssueChanges

MakeIssue = Callable[..., Awaitable[Issue]]

#: Короткая политика: два подхода и пауза в секунду. Настоящая (пять попыток, пауза от
#: десяти секунд) проверялась бы часами.
FAST_RETRY = RetryPolicy(
    max_attempts=2,
    base_delay=timedelta(seconds=1),
    max_delay=timedelta(seconds=4),
)


def _collector(
    seen: list[EventEnvelope],
) -> Callable[[AsyncSession, EventEnvelope], Awaitable[None]]:
    async def handler(session: AsyncSession, event: EventEnvelope) -> None:
        seen.append(event)

    return handler


def _breaker(message: str) -> Callable[[AsyncSession, EventEnvelope], Awaitable[None]]:
    async def handler(session: AsyncSession, event: EventEnvelope) -> None:
        raise RuntimeError(message)

    return handler


async def _process(
    session: AsyncSession,
    registry: SubscriberRegistry,
    *,
    now: datetime | None = None,
) -> events_service.ProcessedEvent | None:
    return await events_service.process_next_event(
        session, registry=registry, policy=FAST_RETRY, now=now
    )


async def _pending(session: AsyncSession) -> int:
    statement = (
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
    )
    return (await session.scalar(statement)) or 0


# --- Реестр -----------------------------------------------------------------------


def test_a_subscriber_only_gets_the_types_it_asked_for() -> None:
    """Подписка без указания типов означает «все»: так подписываются SSE и вебхуки."""
    registry = SubscriberRegistry()
    registry.register(_collector([]), name="only_status", events=[EventType.ISSUE_STATUS_CHANGED])
    registry.register(_collector([]), name="everything")

    assert [item.name for item in registry.matching(EventType.ISSUE_CREATED)] == ["everything"]
    assert sorted(item.name for item in registry.matching(EventType.ISSUE_STATUS_CHANGED)) == [
        "everything",
        "only_status",
    ]


def test_a_duplicate_name_is_refused() -> None:
    """Молчаливая замена подписчика — худший исход: он просто исчезнет из обработки."""
    registry = SubscriberRegistry()
    registry.register(_collector([]), name="notifications")

    try:
        registry.register(_collector([]), name="notifications")
    except ValueError as error:
        assert "notifications" in str(error)
    else:
        raise AssertionError("duplicate subscriber name must be refused")


def test_the_retry_delay_grows_and_stops_at_the_ceiling() -> None:
    """Пауза удваивается с каждой попыткой и упирается в потолок."""
    policy = RetryPolicy(
        max_attempts=10,
        base_delay=timedelta(seconds=10),
        max_delay=timedelta(seconds=40),
    )

    assert policy.delay_after(1) == timedelta(seconds=10)
    assert policy.delay_after(2) == timedelta(seconds=20)
    assert policy.delay_after(3) == timedelta(seconds=40)
    assert policy.delay_after(9) == timedelta(seconds=40)


# --- Доставка ---------------------------------------------------------------------


async def test_the_worker_delivers_an_event_and_marks_it_done(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Событие уходит подписчику и помечается доставленным вместе с его именем."""
    registry = SubscriberRegistry()
    seen: list[EventEnvelope] = []
    registry.register(_collector(seen), name="automation")

    issue = await make_issue()
    processed = await _process(db_session, registry)

    assert processed is not None
    assert processed.status is OutboxStatus.DELIVERED
    assert processed.outcome.delivered == ("automation",)
    assert [event.event_type for event in seen] == [EventType.ISSUE_CREATED]
    assert seen[0].object_key == issue.key
    assert seen[0].payload["issue"]["key"] == issue.key


async def test_an_event_without_subscribers_is_still_processed(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Пустой реестр — не повод копить события: доставлять их некому."""
    await make_issue()

    processed = await _process(db_session, SubscriberRegistry())

    assert processed is not None
    assert processed.status is OutboxStatus.DELIVERED


async def test_there_is_nothing_to_process_on_an_empty_outbox(db_session: AsyncSession) -> None:
    """Пустая очередь возвращает `None` — по этому признаку воркер уходит спать."""
    assert await _process(db_session, SubscriberRegistry()) is None


async def test_events_are_processed_in_the_order_they_happened(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Порядок доставки — порядок появления, а не случайный порядок UUID."""
    registry = SubscriberRegistry()
    seen: list[EventEnvelope] = []
    registry.register(_collector(seen), name="stream")

    issue = await make_issue()
    await issues_service.update_issue(
        db_session, issue, initiator=owner, changes=IssueChanges(summary="Второе")
    )

    while await _process(db_session, registry) is not None:
        pass

    assert [event.event_type for event in seen] == [
        EventType.ISSUE_CREATED,
        EventType.ISSUE_UPDATED,
    ]


# --- Изоляция подписчиков ---------------------------------------------------------


async def test_a_failing_subscriber_does_not_stop_the_others(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Падение вебхука не должно останавливать автоматику — буквально это и проверяется."""
    registry = SubscriberRegistry()
    seen: list[EventEnvelope] = []
    registry.register(_breaker("webhook is dead"), name="webhooks")
    registry.register(_collector(seen), name="automation")

    await make_issue()
    processed = await _process(db_session, registry)

    assert processed is not None
    assert len(seen) == 1, "подписчик после упавшего обязан отработать"
    assert processed.outcome.delivered == ("automation",)
    assert [failure.name for failure in processed.outcome.failures] == ["webhooks"]
    assert processed.status is OutboxStatus.PENDING
    assert processed.attempts == 1


async def test_a_failing_subscriber_rolls_back_only_its_own_writes(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Вложенная транзакция вокруг подписчика: упавший не уносит чужую работу.

    Без неё запись упавшего подписчика оставила бы транзакцию в состоянии, где падает
    любой следующий запрос, — и вместе с ней откатилась бы и работа соседа, и отметка
    об обработке события.
    """
    registry = SubscriberRegistry()

    async def writes_then_fails(session: AsyncSession, event: EventEnvelope) -> None:
        await actors_service.ensure_actor(
            session, actor_type=ActorType.AGENT, key="ghost", display_name="Ghost"
        )
        raise RuntimeError("failed after writing")

    async def writes_and_succeeds(session: AsyncSession, event: EventEnvelope) -> None:
        await actors_service.ensure_actor(
            session, actor_type=ActorType.AGENT, key="survivor", display_name="Survivor"
        )

    registry.register(writes_then_fails, name="doomed")
    registry.register(writes_and_succeeds, name="lucky")

    await make_issue()
    processed = await _process(db_session, registry)

    assert processed is not None
    assert processed.outcome.delivered == ("lucky",)

    keys = set(
        await db_session.scalars(select(Actor.key).where(Actor.key.in_(["ghost", "survivor"])))
    )
    assert keys == {"survivor"}


# --- Повторы ----------------------------------------------------------------------


async def test_a_retry_only_calls_the_subscriber_that_failed(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Отработавший подписчик не вызывается заново из-за соседа, который упал.

    Иначе одно падение вебхука заставляло бы автоматику срабатывать столько раз,
    сколько было попыток доставки.
    """
    registry = SubscriberRegistry()
    seen: list[EventEnvelope] = []
    failures = {"count": 0}

    async def fails_once(session: AsyncSession, event: EventEnvelope) -> None:
        failures["count"] += 1
        if failures["count"] == 1:
            raise RuntimeError("temporary outage")

    registry.register(fails_once, name="webhooks")
    registry.register(_collector(seen), name="automation")

    await make_issue()
    first = await _process(db_session, registry)
    assert first is not None
    assert first.status is OutboxStatus.PENDING

    # Время сдвинуто вперёд: до истечения паузы событие брать нельзя.
    later = datetime.now(UTC) + FAST_RETRY.max_delay + timedelta(seconds=1)
    second = await _process(db_session, registry, now=later)

    assert second is not None
    assert second.status is OutboxStatus.DELIVERED
    assert second.outcome.delivered == ("webhooks",)
    assert len(seen) == 1, "уже отработавший подписчик не должен вызываться повторно"


async def test_an_event_waits_out_its_pause_before_the_next_attempt(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Повтор не мгновенный: иначе воркер крутил бы мёртвого подписчика без передышки."""
    registry = SubscriberRegistry()
    registry.register(_breaker("still dead"), name="webhooks")

    await make_issue()
    assert await _process(db_session, registry) is not None

    # Тот же момент времени: пауза ещё не прошла, брать нечего.
    assert await _process(db_session, registry) is None
    assert await _pending(db_session) == 1


async def test_attempts_run_out_and_the_event_is_marked_undelivered(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Мёртвый подписчик не занимает воркера вечно: попытки кончаются, событие гаснет."""
    registry = SubscriberRegistry()
    registry.register(_breaker("permanently broken"), name="webhooks")

    await make_issue()
    moment = datetime.now(UTC)
    for attempt in range(FAST_RETRY.max_attempts):
        processed = await _process(db_session, registry, now=moment)
        assert processed is not None, f"попытка {attempt + 1} не состоялась"
        moment += FAST_RETRY.max_delay + timedelta(seconds=1)

    assert processed.status is OutboxStatus.FAILED
    assert processed.attempts == FAST_RETRY.max_attempts
    assert "webhooks: RuntimeError: permanently broken" in (
        await db_session.scalar(select(OutboxEvent.last_error).limit(1))
    )
    # Погашенное событие больше не берётся: иначе «не доставлено» ничего не значило бы.
    assert await _process(db_session, registry, now=moment) is None


# --- Перезапуск -------------------------------------------------------------------


async def test_an_event_survives_an_attempt_that_was_not_committed(
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Убитый посреди работы воркер не теряет событие: транзакция откатывается целиком.

    Обработка и отметка о ней — одно целое, поэтому откат возвращает событие в очередь
    ровно в том виде, в каком оно там лежало.
    """
    registry = SubscriberRegistry()
    seen: list[EventEnvelope] = []
    registry.register(_collector(seen), name="automation")

    await make_issue()

    savepoint = await db_session.begin_nested()
    processed = await _process(db_session, registry)
    assert processed is not None
    assert processed.status is OutboxStatus.DELIVERED
    await savepoint.rollback()

    assert await _pending(db_session) == 1
    again = await _process(db_session, registry)
    assert again is not None
    assert again.status is OutboxStatus.DELIVERED
    assert len(seen) == 2, "после отката событие обрабатывается заново"
