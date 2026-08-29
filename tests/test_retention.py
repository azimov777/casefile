"""Срок хранения журналов: что удаляется, что неприкосновенно и где видна несогласованность.

Записи журналов здесь кладутся в базу напрямую, а не порождаются сценариями. Это тот
редкий случай, когда прямая вставка честнее: проверяется срок хранения, то есть
поведение, целиком зависящее от `created_at`, а сценарий ставит эту отметку сам и
всегда «сейчас». Породить событие месячной давности через API нечем.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule, AutomationRun
from app.db.models.event import OutboxEvent
from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.domain.automation import RunStatus, RunTrigger
from app.domain.errors import InvalidStreamCursorError
from app.domain.event_stream import StreamFilter
from app.domain.events import OutboxStatus
from app.domain.retention import RetentionPolicy, RetentionTarget
from app.domain.webhooks import DeliveryStatus
from app.services import event_stream as stream_service
from app.services import retention as retention_service
from app.services import webhooks as webhooks_service

#: Политика с большим окном и большими пачками: подходит всем тестам, кроме тех, что
#: проверяют сами границы. Сроки взяты короткими, чтобы «старое» и «свежее» в тестах
#: различались днями, а не месяцами.
BASE_POLICY = RetentionPolicy(
    outbox_days=10,
    automation_runs_days=10,
    orphan_runs_days=2,
    webhook_deliveries_days=10,
    batch_size=100,
    max_batches=10,
)

#: Окно переподключения для тестов, проверяющих срок хранения, а не само окно.
#: Ноль означает «клиент вправе продолжить только с самого свежего события», поэтому пол
#: окна держит ровно одну строку — и её роль в каждом таком тесте играет заведомо свежая
#: запись. Широкое окно здесь не годится и это не мелочь: пока событий в очереди меньше,
#: чем обещает окно, чистка не вправе удалить из неё ничего.
NARROW_WINDOW = 0


@pytest.fixture
def make_event(
    db_session: AsyncSession,
    owner: Actor,
) -> Callable[..., Awaitable[OutboxEvent]]:
    """Событие очереди с заданным возрастом и состоянием."""

    async def _make(
        *,
        age_days: float = 0,
        status: OutboxStatus = OutboxStatus.DELIVERED,
        event_type: str = "issue.updated",
    ) -> OutboxEvent:
        event = OutboxEvent(
            event_type=event_type,
            object_type="issue",
            object_id=uuid.uuid4(),
            object_key="TRK-1",
            actor_id=owner.id,
            actor_key=owner.key,
            payload={},
            status=status,
            created_at=datetime.now(UTC) - timedelta(days=age_days),
        )
        db_session.add(event)
        await db_session.flush()
        return event

    return _make


@pytest.fixture
def make_run(db_session: AsyncSession) -> Callable[..., Awaitable[AutomationRun]]:
    """Запись журнала срабатываний заданного возраста."""

    async def _make(*, rule: AutomationRule, age_days: float = 0) -> AutomationRun:
        run = AutomationRun(
            rule_id=rule.id,
            rule_key=rule.rule_key,
            trigger=RunTrigger.EVENT,
            status=RunStatus.SUCCESS,
            created_at=datetime.now(UTC) - timedelta(days=age_days),
        )
        db_session.add(run)
        await db_session.flush()
        return run

    return _make


@pytest.fixture
async def removed_rule(db_session: AsyncSession) -> AutomationRule:
    """Строка правила, которого больше нет в коде.

    Заводится вставкой, потому что иначе её не получить: синхронизация реестра заводит
    строки только под объявленные правила, а удалять чужие она не умеет намеренно —
    каскад унёс бы вместе со строкой весь журнал.
    """
    rule = AutomationRule(
        rule_key="rule_removed_from_code",
        params={},
        is_enabled=False,
    )
    db_session.add(rule)
    await db_session.flush()
    return rule


@pytest.fixture
async def subscription(db_session: AsyncSession, owner: Actor) -> WebhookSubscription:
    return await webhooks_service.create_subscription(
        db_session,
        initiator=owner,
        name="Приёмник",
        url="https://example.test/hook",
    )


@pytest.fixture
def make_delivery(db_session: AsyncSession) -> Callable[..., Awaitable[WebhookDelivery]]:
    """Доставка вебхука с заданным возрастом и состоянием."""

    async def _make(
        *,
        subscription: WebhookSubscription,
        age_days: float = 0,
        status: DeliveryStatus = DeliveryStatus.DELIVERED,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            subscription_id=subscription.id,
            event_type="issue.updated",
            object_type="issue",
            object_key="TRK-1",
            url=subscription.url,
            payload={},
            status=status,
            created_at=datetime.now(UTC) - timedelta(days=age_days),
        )
        db_session.add(delivery)
        await db_session.flush()
        return delivery

    return _make


async def _count(session: AsyncSession, model: Any) -> int:
    return int((await session.scalar(select(func.count()).select_from(model))) or 0)


async def _exists(session: AsyncSession, model: Any, row_id: uuid.UUID) -> bool:
    statement = select(func.count()).select_from(model).where(model.id == row_id)
    return bool(await session.scalar(statement))


# --- Срок хранения ------------------------------------------------------------------


async def test_expired_rows_go_and_fresh_ones_stay(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
    make_run: Callable[..., Awaitable[AutomationRun]],
    make_delivery: Callable[..., Awaitable[WebhookDelivery]],
    automation_rules: dict[str, AutomationRule],
    subscription: WebhookSubscription,
) -> None:
    """Все три таблицы чистятся по своему сроку, и свежие строки остаются на месте."""
    rule = automation_rules["close_children_with_parent"]
    old_event = await make_event(age_days=30)
    fresh_event = await make_event(age_days=1)
    old_run = await make_run(rule=rule, age_days=30)
    fresh_run = await make_run(rule=rule, age_days=1)
    old_delivery = await make_delivery(subscription=subscription, age_days=30)
    fresh_delivery = await make_delivery(subscription=subscription, age_days=1)

    report = await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=NARROW_WINDOW,
    )

    assert report.deleted == 3
    assert not await _exists(db_session, OutboxEvent, old_event.id)
    assert not await _exists(db_session, AutomationRun, old_run.id)
    assert not await _exists(db_session, WebhookDelivery, old_delivery.id)
    assert await _exists(db_session, OutboxEvent, fresh_event.id)
    assert await _exists(db_session, AutomationRun, fresh_run.id)
    assert await _exists(db_session, WebhookDelivery, fresh_delivery.id)


async def test_dry_run_counts_and_deletes_nothing(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Пробный проход отвечает числами, а базу не трогает."""
    await make_event(age_days=30)
    await make_event(age_days=1)

    report = await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=NARROW_WINDOW,
        dry_run=True,
    )

    assert report.dry_run
    assert report.deleted == 1
    assert await _count(db_session, OutboxEvent) == 2


# --- Неприкосновенность необработанного ---------------------------------------------


async def test_pending_rows_survive_any_age(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
    make_delivery: Callable[..., Awaitable[WebhookDelivery]],
    subscription: WebhookSubscription,
) -> None:
    """Событие, до которого не дошёл воркер, и доставка в очереди сроку не подчиняются.

    Это не история, а невыполненная работа: удалить её — значит потерять её. Возраст
    берётся заведомо больше любого срока, чтобы проверялось именно состояние.
    """
    # Свежее событие держит пол окна переподключения: без него самая новая строка
    # очереди неприкосновенна сама по себе, и проверялось бы не состояние, а пол.
    await make_event(age_days=0)
    waiting_event = await make_event(age_days=365, status=OutboxStatus.PENDING)
    waiting_delivery = await make_delivery(
        subscription=subscription,
        age_days=365,
        status=DeliveryStatus.PENDING,
    )
    failed_event = await make_event(age_days=365, status=OutboxStatus.FAILED)
    failed_delivery = await make_delivery(
        subscription=subscription,
        age_days=365,
        status=DeliveryStatus.FAILED,
    )

    await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=NARROW_WINDOW,
    )

    assert await _exists(db_session, OutboxEvent, waiting_event.id)
    assert await _exists(db_session, WebhookDelivery, waiting_delivery.id)
    # Исчерпавшая попытки строка — уже история, а не работа: её срок хранения касается.
    assert not await _exists(db_session, OutboxEvent, failed_event.id)
    assert not await _exists(db_session, WebhookDelivery, failed_delivery.id)


# --- Согласование с окном переподключения SSE ---------------------------------------


async def test_reconnect_window_holds_events_the_retention_would_delete(
    db_session: AsyncSession,
    owner: Actor,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Окно переподключения не сужается сроком хранения, и расхождение видно в отчёте.

    Три старых события при окне в два: удалить можно только самое старое — два
    остальных обязаны пережить чистку, иначе клиент, отставший на одно событие,
    получил бы отказ, положенный отставшему на тысячи.
    """
    oldest = await make_event(age_days=30)
    middle = await make_event(age_days=29)
    newest = await make_event(age_days=28)

    report = await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=1,
    )

    assert not await _exists(db_session, OutboxEvent, oldest.id)
    assert await _exists(db_session, OutboxEvent, middle.id)
    assert await _exists(db_session, OutboxEvent, newest.id)

    window = report.stream_window
    assert not window.is_consistent
    assert window.protected == 2
    assert "TRACKER_RETENTION_OUTBOX_DAYS" in window.message()

    # Обещание держится не на словах: курсор уцелевшего события по-прежнему разрешается
    # в позицию, а не в отказ.
    position = await stream_service.resolve_position(
        db_session,
        initiator=owner,
        last_event_id=middle.id,
        stream_filter=StreamFilter(),
    )
    assert position == (middle.created_at, middle.id)


async def test_window_check_is_quiet_when_retention_is_wider(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Пока срок хранения перекрывает окно, отчёт не поднимает шума."""
    await make_event(age_days=1)
    await make_event(age_days=2)

    report = await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=1,
    )

    assert report.stream_window.is_consistent
    assert report.stream_window.protected == 0


async def test_deleted_cursor_is_refused_not_silently_restarted(
    db_session: AsyncSession,
    owner: Actor,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Событие, вышедшее за окно и удалённое, даёт отказ — а не молчаливый старт с конца.

    Проверка сторожит ровно ту границу, ради которой чистка и окно решаются вместе:
    молчаливый старт означал бы клиента, считающего себя синхронизированным.
    """
    gone = await make_event(age_days=30)
    for _ in range(3):
        await make_event(age_days=29)

    await retention_service.cleanup(db_session, policy=BASE_POLICY, replay_limit=1)

    assert not await _exists(db_session, OutboxEvent, gone.id)
    with pytest.raises(InvalidStreamCursorError) as failure:
        await stream_service.resolve_position(
            db_session,
            initiator=owner,
            last_event_id=gone.id,
            stream_filter=StreamFilter(),
        )
    assert failure.value.details["reason"] == "unknown_event"


# --- Пачки --------------------------------------------------------------------------


async def test_pass_stops_at_its_ceiling_and_says_so(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Проход удаляет не больше `batch_size * max_batches` строк и сообщает об остатке."""
    await make_event(age_days=1)
    for _ in range(5):
        await make_event(age_days=30)

    policy = RetentionPolicy(
        outbox_days=10,
        automation_runs_days=10,
        orphan_runs_days=2,
        webhook_deliveries_days=10,
        batch_size=2,
        max_batches=1,
    )
    report = await retention_service.cleanup(
        db_session,
        policy=policy,
        replay_limit=NARROW_WINDOW,
    )

    outcome = report.outcome(RetentionTarget.OUTBOX_EVENTS)
    assert outcome is not None
    assert outcome.deleted == 2
    assert outcome.batches == 1
    assert outcome.capped
    assert report.capped
    assert await _count(db_session, OutboxEvent) == 4

    # Остаток забирает следующий запуск: работа отложена, а не потеряна.
    await retention_service.cleanup(db_session, policy=policy, replay_limit=NARROW_WINDOW)
    assert await _count(db_session, OutboxEvent) == 2
    await retention_service.cleanup(db_session, policy=policy, replay_limit=NARROW_WINDOW)
    # Осталось только свежее событие: срок хранения его не касается.
    assert await _count(db_session, OutboxEvent) == 1


async def test_several_batches_add_up(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Пачки идут одна за другой, пока подходящие строки не кончатся."""
    await make_event(age_days=1)
    for _ in range(5):
        await make_event(age_days=30)

    policy = RetentionPolicy(
        outbox_days=10,
        automation_runs_days=10,
        orphan_runs_days=2,
        webhook_deliveries_days=10,
        batch_size=2,
        max_batches=10,
    )
    report = await retention_service.cleanup(
        db_session,
        policy=policy,
        replay_limit=NARROW_WINDOW,
    )

    outcome = report.outcome(RetentionTarget.OUTBOX_EVENTS)
    assert outcome is not None
    assert outcome.deleted == 5
    assert outcome.batches == 3
    assert not outcome.capped
    assert await _count(db_session, OutboxEvent) == 1


# --- Журнал правила, удалённого из кода ---------------------------------------------


async def test_journal_of_a_removed_rule_has_its_own_shorter_term(
    db_session: AsyncSession,
    automation_rules: dict[str, AutomationRule],
    removed_rule: AutomationRule,
    make_run: Callable[..., Awaitable[AutomationRun]],
) -> None:
    """Срабатывания исчезнувшего правила уходят раньше, а строка самого правила остаётся.

    Возраст один и тот же у обеих записей: различает их не он, а наличие правила в
    реестре кода.
    """
    live_rule = automation_rules["close_children_with_parent"]
    live_run = await make_run(rule=live_rule, age_days=5)
    orphan_run = await make_run(rule=removed_rule, age_days=5)

    report = await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=NARROW_WINDOW,
    )

    assert await _exists(db_session, AutomationRun, live_run.id)
    assert not await _exists(db_session, AutomationRun, orphan_run.id)
    # Строка правила переживает чистку своего журнала: удалять её — отдельное решение.
    assert await _exists(db_session, AutomationRule, removed_rule.id)

    orphan = report.outcome(RetentionTarget.ORPHAN_AUTOMATION_RUNS)
    assert orphan is not None
    assert orphan.deleted == 1
    assert orphan.skipped is None


async def test_fresh_journal_of_a_removed_rule_still_readable(
    db_session: AsyncSession,
    removed_rule: AutomationRule,
    make_run: Callable[..., Awaitable[AutomationRun]],
) -> None:
    """Короткий срок — это срок, а не немедленное удаление."""
    recent = await make_run(rule=removed_rule, age_days=1)

    await retention_service.cleanup(db_session, policy=BASE_POLICY, replay_limit=NARROW_WINDOW)

    assert await _exists(db_session, AutomationRun, recent.id)


# --- Политика -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["outbox_days", "automation_runs_days", "orphan_runs_days", "batch_size", "max_batches"],
)
def test_policy_refuses_meaningless_values(field: str) -> None:
    """Нулевой срок или нулевая пачка отвергаются, а не выполняются буквально."""
    values = {
        "outbox_days": 10,
        "automation_runs_days": 10,
        "orphan_runs_days": 2,
        "webhook_deliveries_days": 10,
        "batch_size": 100,
        "max_batches": 10,
    }
    values[field] = 0
    with pytest.raises(ValueError, match=field):
        RetentionPolicy(**values)


async def test_report_names_every_target_and_the_window(
    db_session: AsyncSession,
    make_event: Callable[..., Awaitable[OutboxEvent]],
) -> None:
    """Отчёт читается без похода в базу: он и есть след того, что чистка удалила."""
    await make_event(age_days=1)
    await make_event(age_days=30)

    report = await retention_service.cleanup(
        db_session,
        policy=BASE_POLICY,
        replay_limit=NARROW_WINDOW,
    )
    text = "\n".join(report.lines())

    for target in RetentionTarget:
        assert target.value in text
    assert "stream window" in text
    assert BASE_POLICY.max_rows == BASE_POLICY.batch_size * BASE_POLICY.max_batches
