"""Действие `webhook` в контексте правила автоматики.

Отдельный модуль, а не дописка в `test_automation_engine.py`: правила объявляются в
самом тестовом файле, реестр глобальный на процесс, и ключи здесь начинаются с `t15_` —
так они не столкнутся ни с поставочными правилами, ни с правилами задач 13 и 14.

Проверяется то, что ломается молча: вызов обязан **ставиться в очередь**, а не уходить
по сети из правила, и обязан быть виден в журнале срабатываний — иначе по нему нельзя
отличить отправленный вызов от пропущенного.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.context import RuleContext
from app.automation.registry import rule
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule
from app.db.models.issue import Issue
from app.db.models.webhook import WebhookSubscription
from app.domain.automation import RuleKind, RunStatus
from app.domain.webhooks import DIRECT_EVENT_TYPE, DeliveryStatus
from app.services import automation as automation_service
from app.services import webhooks as webhooks_service

MakeIssue = Callable[..., Awaitable[Issue]]
EnableRule = Callable[..., Awaitable[AutomationRule]]


@rule(
    key="t15_release_call",
    name="Test release webhook",
    kind=RuleKind.MACRO,
)
async def t15_release_call(ctx: RuleContext) -> None:
    """Дёргает внешнюю систему по имени подписки."""
    await ctx.webhook("release-bot", "Release is ready", version="1.2.3")


@rule(
    key="t15_unknown_call",
    name="Test webhook with a typo in the name",
    kind=RuleKind.MACRO,
)
async def t15_unknown_call(ctx: RuleContext) -> None:
    """Адресует подписку, которой нет: опечатка в параметрах правила."""
    await ctx.webhook("no-such-address", "Nobody is listening")


@pytest.fixture
def make_webhook(
    db_session: AsyncSession,
    owner: Actor,
) -> Callable[..., Awaitable[WebhookSubscription]]:
    async def _make(**kwargs: object) -> WebhookSubscription:
        return await webhooks_service.create_subscription(
            db_session,
            initiator=owner,
            name=kwargs.pop("name", "release-bot"),
            url=kwargs.pop("url", "https://ci.example.test/hooks/release"),
            **kwargs,
        )

    return _make


async def test_a_rule_queues_a_call_instead_of_making_it(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
) -> None:
    """Сетевой вызов из правила задержал бы обработку события на таймаут мёртвого адреса."""
    await make_webhook()
    await enable_rule("t15_release_call")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t15_release_call",
        issue=issue,
        initiator=owner,
    )

    assert outcome.status is RunStatus.SUCCESS
    page = await webhooks_service.list_deliveries(db_session, initiator=owner)
    (delivery,) = page.items
    assert delivery.status is DeliveryStatus.PENDING
    assert delivery.event_type == DIRECT_EVENT_TYPE
    assert delivery.event_id is None
    assert delivery.object_key == issue.key
    assert delivery.payload["summary"] == "Release is ready"
    assert delivery.payload["details"] == {"version": "1.2.3"}


async def test_the_queued_call_is_visible_in_the_run_log(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
) -> None:
    """Иначе журнал отвечает «сработало», но не «что именно сделало»."""
    await make_webhook()
    await enable_rule("t15_release_call")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t15_release_call",
        issue=issue,
        initiator=owner,
    )

    (action,) = outcome.run.actions
    assert action["action"] == "webhook"
    assert action["target"] == "release-bot"
    assert "delivery" in action


async def test_a_disabled_address_is_skipped_visibly_and_does_not_break_the_rule(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
) -> None:
    """Чужая настройка не должна ронять правило, но и теряться вызов не имеет права."""
    await make_webhook(is_enabled=False)
    await enable_rule("t15_release_call")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t15_release_call",
        issue=issue,
        initiator=owner,
    )

    assert outcome.status is RunStatus.SUCCESS
    (action,) = outcome.run.actions
    assert action["skipped"] == "subscription_disabled"
    page = await webhooks_service.list_deliveries(db_session, initiator=owner)
    assert page.items == []


async def test_an_address_that_filtered_direct_calls_out_is_skipped_visibly(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    make_webhook: Callable[..., Awaitable[WebhookSubscription]],
) -> None:
    """Подписка, сузившая набор типов, сказала это осознанно — правило её уважает."""
    await make_webhook(event_types=["issue.created"])
    await enable_rule("t15_release_call")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t15_release_call",
        issue=issue,
        initiator=owner,
    )

    (action,) = outcome.run.actions
    assert action["skipped"] == "event_type_filtered"


async def test_a_typo_in_the_address_name_fails_the_rule(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Несуществующее имя — ошибка настройки правила, и молчать о ней нельзя."""
    await enable_rule("t15_unknown_call")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t15_unknown_call",
        issue=issue,
        initiator=owner,
    )

    assert outcome.status is RunStatus.FAILED
    assert "WebhookSubscriptionNotFoundError" in (outcome.run.error or "")
