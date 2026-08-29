"""Сценарии вебхуков: отбор адресов, постановка заданий, повторы, отключение мёртвого.

События здесь настоящие: тест меняет задачу сценарием, забирает событие из outbox и
отдаёт его подписчику — тем же путём, каким это делает воркер. Конверт, собранный
руками, проверял бы отбор по выдуманной нагрузке, а не по той, которую в самом деле
кладёт `app/services/events.py`.

Сеть не участвует: транспорт передаётся сценарию параметром, и тест подсовывает свой.
Именно ради этого он и параметр — HTTP-клиент живёт в процессе доставщика.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import OutboxEvent
from app.db.models.issue import Issue
from app.db.models.project import Project
from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.domain.errors import (
    WebhookDeliveryNotRetryableError,
    WebhookSubscriptionDisabledError,
    WebhookSubscriptionNameTakenError,
)
from app.domain.events import EventType
from app.domain.webhooks import (
    DELIVERY_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    DeliveryStatus,
    WebhookScope,
    verify,
)
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services import webhooks as service
from app.services.event_bus import EventEnvelope
from app.services.events import RetryPolicy
from app.services.issues import IssueChanges
from app.services.webhooks import DeliveryAttempt

MakeIssue = Callable[..., Awaitable[Issue]]
MakeProject = Callable[..., Awaitable[Project]]

#: Политика повторов теста: три попытки, чтобы исчерпание было видно на третьей.
POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=timedelta(seconds=10),
    max_delay=timedelta(seconds=60),
)


@pytest.fixture
def make_webhook(
    db_session: AsyncSession,
    owner: Actor,
) -> Callable[..., Awaitable[WebhookSubscription]]:
    """Фабрика подписок: адрес и имя по умолчанию, остальное — как попросят."""

    async def _make(**kwargs: object) -> WebhookSubscription:
        return await service.create_subscription(
            db_session,
            initiator=kwargs.pop("initiator", owner),
            name=kwargs.pop("name", "release-bot"),
            url=kwargs.pop("url", "https://ci.example.test/hooks/tracker"),
            **kwargs,
        )

    return _make


async def dispatch_new_events(session: AsyncSession, *, after: int = 0) -> list[WebhookDelivery]:
    """Отдаёт подписчику вебхуков события outbox, начиная с указанного номера.

    Тем же путём, что и воркер: конверт собирается из строки outbox, а не пишется
    руками.
    """
    statement = select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)
    events = list((await session.scalars(statement)).unique().all())
    created: list[WebhookDelivery] = []
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
                    payload=event.payload,
                    created_at=event.created_at,
                ),
            )
        )
    return created


def accepting(status_code: int = 200) -> Callable:
    """Транспорт, отвечающий заданным кодом и запоминающий, что ему передали."""
    calls: list[tuple[str, dict[str, str], bytes]] = []

    async def _send(url: str, headers: dict[str, str], body: bytes) -> DeliveryAttempt:
        calls.append((url, headers, body))
        ok = 200 <= status_code < 300
        return DeliveryAttempt(
            ok=ok,
            response_status=status_code,
            error=None if ok else f"HTTP {status_code}",
        )

    _send.calls = calls  # type: ignore[attr-defined]
    return _send


async def unreachable(url: str, headers: dict[str, str], body: bytes) -> DeliveryAttempt:
    """Адрес, который не отвечает вовсе: таймаут, а не код ответа."""
    return DeliveryAttempt(ok=False, response_status=None, error="ConnectTimeout: timed out")


# --- Отбор адресов ------------------------------------------------------------------


async def test_an_event_is_queued_for_every_matching_address(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Одно событие — по заданию на каждый адрес, у каждого свой идентификатор доставки."""
    await make_webhook(name="first")
    await make_webhook(name="second", url="https://bot.example.test/hook")
    await make_issue()

    deliveries = await dispatch_new_events(db_session)

    assert {delivery.subscription.name for delivery in deliveries} == {"first", "second"}
    assert len({delivery.payload["delivery"] for delivery in deliveries}) == len(deliveries)


async def test_a_queue_subscription_ignores_other_queues(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    await make_webhook(scope=WebhookScope.QUEUE, scope_key="OPS")
    other = await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="OPS",
        name="Эксплуатация",
    )
    await make_issue()
    await make_issue(queue=other, summary="Поднять контур")

    deliveries = await dispatch_new_events(db_session)

    assert [delivery.object_key for delivery in deliveries] == ["OPS-1"]


async def test_a_project_subscription_follows_the_issue_out_of_the_project(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Уход из проекта — тоже событие проекта: в наборе лежат и прежний ключ, и новый."""
    project = await make_project()
    await make_webhook(scope=WebhookScope.PROJECT, scope_key=project.key)
    issue = await make_issue(project=project)
    seen = len(await dispatch_new_events(db_session))

    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(project=None),
    )
    deliveries = await dispatch_new_events(db_session, after=seen)

    assert [delivery.event_type for delivery in deliveries] == [EventType.ISSUE_UPDATED]


async def test_a_type_filter_narrows_the_stream(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    await make_webhook(event_types=[EventType.ISSUE_STATUS_CHANGED])
    issue = await make_issue()
    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Другое"),
    )

    assert await dispatch_new_events(db_session) == []


async def test_a_disabled_subscription_gets_nothing_queued(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Задание выключенной подписке копило бы работу, которую никто не заберёт."""
    await make_webhook(is_enabled=False)
    await make_issue()

    assert await dispatch_new_events(db_session) == []


async def test_a_name_is_unique_because_rules_address_a_subscription_by_it(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
) -> None:
    await make_webhook(name="release-bot")

    with pytest.raises(WebhookSubscriptionNameTakenError):
        await make_webhook(name="release-bot", url="https://other.example.test/hook")


# --- Доставка -----------------------------------------------------------------------


async def test_a_successful_delivery_is_signed_with_the_subscription_secret(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Подпись считается по тем самым байтам, которые уходят в сеть, и покрывает время."""
    subscription = await make_webhook()
    await make_issue()
    await dispatch_new_events(db_session)
    send = accepting()

    processed = await service.process_next_delivery(db_session, send=send, policy=POLICY)

    assert processed is not None
    assert processed.status is DeliveryStatus.DELIVERED
    (url, headers, body) = send.calls[0]
    assert url == subscription.url
    assert headers[DELIVERY_HEADER] == str(processed.delivery.id)
    assert verify(
        subscription.secret,
        int(headers[TIMESTAMP_HEADER]),
        body,
        headers[SIGNATURE_HEADER],
    )


async def test_a_failed_attempt_is_retried_later_with_a_growing_delay(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Задание остаётся ожидающим, но недоступным до срока: иначе повтор ушёл бы немедленно."""
    await make_webhook()
    await make_issue()
    await dispatch_new_events(db_session)
    moment = datetime.now(UTC)

    processed = await service.process_next_delivery(
        db_session,
        send=unreachable,
        policy=POLICY,
        now=moment,
    )

    assert processed is not None
    assert processed.status is DeliveryStatus.PENDING
    assert processed.attempts == 1
    assert processed.delivery.available_at > moment
    # Ответа не было вовсе — это не то же самое, что «получатель ответил 500».
    assert processed.delivery.response_status is None
    assert await service.process_next_delivery(db_session, send=unreachable, now=moment) is None


async def test_attempts_run_out_and_the_delivery_is_marked_failed(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Бесконечный повтор занимал бы доставщик мёртвым адресом навсегда."""
    await make_webhook()
    await make_issue()
    await dispatch_new_events(db_session)

    moment = datetime.now(UTC)
    for attempt in range(POLICY.max_attempts):
        moment += timedelta(minutes=5)
        processed = await service.process_next_delivery(
            db_session,
            send=unreachable,
            policy=POLICY,
            now=moment,
        )
        assert processed is not None
        assert processed.attempts == attempt + 1

    assert processed.status is DeliveryStatus.FAILED
    assert "timed out" in (processed.delivery.last_error or "")


async def test_a_receiver_answering_with_an_error_code_is_told_apart_from_silence(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """«500 от получателя» и «адрес не отвечает» чинятся в разных местах."""
    await make_webhook()
    await make_issue()
    await dispatch_new_events(db_session)

    processed = await service.process_next_delivery(
        db_session,
        send=accepting(500),
        policy=POLICY,
    )

    assert processed is not None
    assert processed.delivery.response_status == 500


# --- Мёртвый адрес ------------------------------------------------------------------


async def test_a_dead_address_switches_its_subscription_off_and_says_why(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Иначе мёртвый адрес занимал бы доставщик таймаутами до скончания века."""
    settings = service.get_settings()
    monkeypatch.setattr(settings, "webhook_failure_threshold", 2, raising=False)
    subscription = await make_webhook()
    await make_issue()
    await dispatch_new_events(db_session)

    moment = datetime.now(UTC)
    for _ in range(2):
        moment += timedelta(minutes=5)
        await service.process_next_delivery(
            db_session,
            send=unreachable,
            policy=POLICY,
            now=moment,
        )

    assert subscription.is_enabled is False
    assert subscription.disabled_reason == service.DISABLED_BY_FAILURES
    assert subscription.disabled_at is not None


async def test_switching_a_subscription_off_cancels_its_queued_deliveries(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Оставленные задания продолжали бы жечь таймауты на признанном мёртвым адресе."""
    settings = service.get_settings()
    monkeypatch.setattr(settings, "webhook_failure_threshold", 1, raising=False)
    await make_webhook()
    await make_issue()
    await make_issue(summary="Вторая задача")
    queued = await dispatch_new_events(db_session)
    assert len(queued) == 2

    await service.process_next_delivery(db_session, send=unreachable, policy=POLICY)

    page = await service.list_deliveries(db_session, initiator=owner)
    assert {item.status for item in page.items} == {DeliveryStatus.FAILED}
    assert service.CANCELLED_BY_DISABLE in {item.last_error for item in page.items}


async def test_a_success_resets_the_failure_counter(
    db_session: AsyncSession,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Получатель, теряющий каждую вторую доставку, работает — гасить его нельзя."""
    subscription = await make_webhook()
    await make_issue()
    await make_issue(summary="Вторая задача")
    await dispatch_new_events(db_session)

    await service.process_next_delivery(db_session, send=unreachable, policy=POLICY)
    assert subscription.consecutive_failures == 1

    await service.process_next_delivery(db_session, send=accepting(), policy=POLICY)
    assert subscription.consecutive_failures == 0


async def test_enabling_a_subscription_by_hand_clears_the_automatic_shutdown(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Иначе включённая после починки подписка погасла бы на первой же неудаче."""
    settings = service.get_settings()
    monkeypatch.setattr(settings, "webhook_failure_threshold", 1, raising=False)
    subscription = await make_webhook()
    await make_issue()
    await dispatch_new_events(db_session)
    await service.process_next_delivery(db_session, send=unreachable, policy=POLICY)

    await service.update_subscription(
        db_session,
        subscription,
        initiator=owner,
        is_enabled=True,
    )

    assert subscription.consecutive_failures == 0
    assert subscription.disabled_at is None
    assert subscription.disabled_reason is None


# --- Переотправка --------------------------------------------------------------------


async def test_a_retry_is_a_new_delivery_with_a_new_id(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Отправив то же тело второй раз, мы получили бы вызов, законно отброшенный как дубль."""
    await make_webhook()
    await make_issue()
    (original,) = await dispatch_new_events(db_session)
    await service.process_next_delivery(db_session, send=accepting(500), policy=POLICY)
    original.status = DeliveryStatus.FAILED

    repeated = await service.retry_delivery(db_session, original, initiator=owner)

    assert repeated.id != original.id
    assert repeated.payload["delivery"] == str(repeated.id)
    assert repeated.event_id == original.event_id
    assert repeated.status is DeliveryStatus.PENDING


async def test_a_pending_delivery_cannot_be_retried(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Вторая постановка удвоила бы вызов у получателя."""
    await make_webhook()
    await make_issue()
    (delivery,) = await dispatch_new_events(db_session)

    with pytest.raises(WebhookDeliveryNotRetryableError):
        await service.retry_delivery(db_session, delivery, initiator=owner)


async def test_a_retry_on_a_disabled_subscription_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
    make_issue: MakeIssue,
) -> None:
    """Сначала адрес чинят и включают подписку, потом переотправляют."""
    subscription = await make_webhook()
    await make_issue()
    (delivery,) = await dispatch_new_events(db_session)
    await service.process_next_delivery(db_session, send=accepting(500), policy=POLICY)
    delivery.status = DeliveryStatus.FAILED
    await service.update_subscription(db_session, subscription, initiator=owner, is_enabled=False)

    with pytest.raises(WebhookSubscriptionDisabledError):
        await service.retry_delivery(db_session, delivery, initiator=owner)
