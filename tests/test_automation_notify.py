"""Действие `notify` в контексте правила автоматики.

Отдельный модуль, а не дописка в `test_automation_engine.py`: правила объявляются в
самом тестовом файле, реестр глобальный на процесс, и ключи здесь начинаются с `t14_` —
так они не столкнутся ни с поставочными правилами, ни с правилами задачи 13.

Проверяется то, что ломается молча: сообщение правила обязано доходить до человека, а
уведомление, адресованное системному актору, обязано быть **видимым отказом**, а не
записью, которую никто не прочитает.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.context import RuleContext
from app.automation.registry import rule
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule
from app.db.models.issue import Issue
from app.domain.automation import RuleKind, RunStatus
from app.domain.notifications import DIRECT_EVENT_TYPE
from app.services import automation as automation_service
from app.services import notifications as notifications_service

MakeIssue = Callable[..., Awaitable[Issue]]
EnableRule = Callable[..., Awaitable[AutomationRule]]


@rule(
    key="t14_notifier",
    name="Test notifier",
    kind=RuleKind.MACRO,
)
async def t14_notifier(ctx: RuleContext) -> None:
    """Пишет исполнителю задачи в инбокс. Если исполнителя нет — автору."""
    target = ctx.target.assignee or ctx.target.author
    await ctx.notify(target, "Deadline is tomorrow", reason="deadline")


@rule(
    key="t14_notifies_system",
    name="Test notifier addressing the system actor",
    kind=RuleKind.MACRO,
)
async def t14_notifies_system(ctx: RuleContext) -> None:
    """Адресует уведомление системному актору — тому, от чьего имени сам и работает."""
    await ctx.notify(ctx.actor, "Nobody will read this")


async def test_a_rule_can_write_into_an_inbox(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Второй способ правила заговорить с человеком, кроме комментария."""
    await enable_rule("t14_notifier")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t14_notifier",
        issue=issue,
        initiator=owner,
    )

    assert outcome.status is RunStatus.SUCCESS
    page = await notifications_service.list_notifications(db_session, initiator=owner)
    (notification,) = page.items
    assert notification.body == "Deadline is tomorrow"
    assert notification.event_type == DIRECT_EVENT_TYPE
    assert notification.issue_key == issue.key
    assert notification.details["reason"] == "deadline"


async def test_the_sent_notification_is_visible_in_the_run_log(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Иначе журнал отвечает «сработало», но не «что именно сделало»."""
    await enable_rule("t14_notifier")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t14_notifier",
        issue=issue,
        initiator=owner,
    )

    # Подробности действия разворачиваются в журнале плоско, рядом с `action` и
    # `target` (`RuleAction.to_payload`), а не вложенным словарём.
    (action,) = outcome.run.actions
    assert action["action"] == "notify"
    assert action["target"] == owner.key
    assert "notification" in action


async def test_a_notification_to_the_system_actor_is_refused_visibly(
    db_session: AsyncSession,
    owner: Actor,
    system_actor: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Правила ходят от имени системного актора, и его инбокс никто не читает.

    Без отсечения он собрал бы копию всего потока событий установки. Отказ при этом
    обязан быть виден в журнале: пропущенное молча выглядело бы как отправленное.
    """
    await enable_rule("t14_notifies_system")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t14_notifies_system",
        issue=issue,
        initiator=owner,
    )

    (action,) = outcome.run.actions
    assert action["skipped"] == "system_actor"
    assert "notification" not in action
    page = await notifications_service.list_notifications(db_session, initiator=system_actor)
    assert page.items == []
