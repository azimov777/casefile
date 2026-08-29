"""Поставочные правила: по одному на каждую форму, на настоящих задачах и процессах.

Это не проверка движка — она в `test_automation_engine.py`, — а проверка того, что
правила из репозитория действительно делают обещанное и делают это через сценарии
приложения. Отдельный файл, потому что правила меняются чаще движка.

Процесс по умолчанию у новой очереди — `open → in_progress → closed`, и закрывающий
переход требует резолюции. Отсюда два разных исхода у одного и того же правила: задачу
в работе оно закрывает, а задачу в `open` — нет, потому что прямого ребра туда в графе
нет. Второй случай и есть та ситуация, ради которой правило не обходит воркфлоу.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation import engine
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule, AutomationRun
from app.db.models.issue import Issue
from app.domain.automation import RunStatus
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.issues import IssuePriority
from app.domain.links import LinkType
from app.services import automation as automation_service
from app.services import checklists as checklists_service
from app.services import comments as comments_service
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import links as links_service
from app.services import queues as queues_service
from app.services.event_bus import EventEnvelope, SubscriberRegistry
from app.services.issues import IssueChanges

MakeIssue = Callable[..., Awaitable[Issue]]
EnableRule = Callable[..., Awaitable[AutomationRule]]


# --- Вспомогательное ----------------------------------------------------------------


async def _drain(session: AsyncSession, *, limit: int = 200) -> None:
    """Прогоняет очередь событий через движок автоматики до пустоты."""
    registry = SubscriberRegistry()

    async def dispatch(inner: AsyncSession, event: EventEnvelope) -> None:
        await engine.dispatch_event(inner, event)

    registry.register(dispatch, name="automation")
    for _ in range(limit):
        if await events_service.process_next_event(session, registry=registry) is None:
            return
    raise AssertionError(f"event queue did not drain within {limit} events")


async def _status(session: AsyncSession, ref: str, *, initiator: Actor) -> Any:
    return await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.STATUS,
        ref,
        initiator=initiator,
    )


async def _resolution(session: AsyncSession, ref: str, *, initiator: Actor) -> Any:
    return await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.RESOLUTION,
        ref,
        initiator=initiator,
    )


async def _start(session: AsyncSession, issue: Issue, *, initiator: Actor) -> None:
    """Переводит задачу в работу настоящим переходом процесса."""
    await issues_service.apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(status=await _status(session, "in_progress", initiator=initiator)),
        action="issue.transition",
    )


async def _close(session: AsyncSession, issue: Issue, *, initiator: Actor) -> None:
    """Закрывает задачу с резолюцией — так же, как это сделал бы человек."""
    await issues_service.apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(
            status=await _status(session, "closed", initiator=initiator),
            resolution=await _resolution(session, "done", initiator=initiator),
        ),
        action="issue.transition",
    )


async def _comments(session: AsyncSession, issue: Issue, *, initiator: Actor) -> list[str]:
    page = await comments_service.list_comments(session, issue, initiator=initiator)
    return [comment.body for comment in page.items]


async def _runs(session: AsyncSession, rule_key: str) -> list[AutomationRun]:
    """Журнал срабатываний правила по порядку. Он и показывает дефект целиком."""
    statement = (
        select(AutomationRun)
        .where(AutomationRun.rule_key == rule_key)
        .order_by(AutomationRun.created_at, AutomationRun.id)
    )
    return list((await session.scalars(statement)).unique())


# --- Триггер: закрытие родителя ------------------------------------------------------


async def test_announce_mode_names_the_open_subtasks(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Режим по умолчанию ничего не закрывает, а говорит вслух: подзадачи ещё открыты."""
    await enable_rule("close_children_with_parent")
    parent = await make_issue(summary="Родитель")
    child = await make_issue(summary="Подзадача")
    await links_service.create_link(
        db_session,
        initiator=owner,
        source=child,
        link_type=LinkType.SUBTASK_OF,
        target=parent,
    )

    await _start(db_session, parent, initiator=owner)
    await _close(db_session, parent, initiator=owner)
    await _drain(db_session)

    assert child.status.category is not StatusCategory.DONE
    assert any(child.key in body for body in await _comments(db_session, parent, initiator=owner))


async def test_close_mode_closes_subtasks_through_the_workflow(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Режим `close` закрывает подзадачу переходом процесса и с переданной резолюцией."""
    await enable_rule(
        "close_children_with_parent",
        params={"mode": "close", "resolution": "done"},
    )
    parent = await make_issue(summary="Родитель")
    child = await make_issue(summary="Подзадача")
    await links_service.create_link(
        db_session,
        initiator=owner,
        source=child,
        link_type=LinkType.SUBTASK_OF,
        target=parent,
    )
    # Подзадача в работе: из `open` прямого ребра в закрывающий статус нет, и правило
    # честно ничего бы не сделало — этот случай проверяется отдельно ниже.
    await _start(db_session, child, initiator=owner)

    await _start(db_session, parent, initiator=owner)
    await _close(db_session, parent, initiator=owner)
    await _drain(db_session)

    assert child.status.category is StatusCategory.DONE
    assert child.resolution is not None and child.resolution.key == "done"


async def test_a_subtask_without_a_closing_transition_is_named_out_loud(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Правило не обходит воркфлоу и не молчит о том, чего не смогло сделать.

    Молчаливый пропуск оставил бы человека в уверенности, что закрыто всё.
    """
    await enable_rule(
        "close_children_with_parent",
        params={"mode": "close", "resolution": "done"},
    )
    parent = await make_issue(summary="Родитель")
    stuck = await make_issue(summary="Подзадача в открытом статусе")
    await links_service.create_link(
        db_session,
        initiator=owner,
        source=stuck,
        link_type=LinkType.SUBTASK_OF,
        target=parent,
    )

    await _start(db_session, parent, initiator=owner)
    await _close(db_session, parent, initiator=owner)
    await _drain(db_session)

    assert stuck.status.category is not StatusCategory.DONE
    assert any(stuck.key in body for body in await _comments(db_session, parent, initiator=owner))


async def test_an_accumulated_queue_of_events_fires_the_trigger_once(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Очередь, накопленная до разбора, даёт одно срабатывание, а не по одному на событие.

    Это и есть проверка контракта «условие — по событию, действие — по строке». Задача
    проходит весь путь до конечного состояния, и **только потом** очередь разбирается —
    так ведёт себя воркер, который отстал или стартовал позже первых изменений. Условие,
    написанное по `ctx.target`, к этому моменту истинно для **каждого** накопленного
    события: правило отработает столько раз, сколько их накопилось, и оставит столько же
    одинаковых комментариев.

    Тест, разбирающий события по одному сразу, зелёный и на сломанном коде: там строка
    задачи ещё совпадает со снимком в событии, и разницы между двумя источниками нет.
    """
    await enable_rule("close_children_with_parent")
    parent = await make_issue(summary="Эпик")
    child = await make_issue(summary="Подзадача")
    await links_service.create_link(
        db_session,
        initiator=owner,
        source=child,
        link_type=LinkType.SUBTASK_OF,
        target=parent,
    )

    # Два перехода подряд, очередь при этом не разбирается: оба события ждут воркера, и
    # к моменту разбора родитель уже закрыт.
    await _start(db_session, parent, initiator=owner)
    await _close(db_session, parent, initiator=owner)

    await _drain(db_session)

    bodies = await _comments(db_session, parent, initiator=owner)
    assert len(bodies) == 1
    assert child.key in bodies[0]

    # Журнал показывает механику, а не только её последствие: рассмотрены оба события,
    # но условию отвечает ровно то, которое привело родителя в закрывающий статус.
    runs = await _runs(db_session, "close_children_with_parent")
    assert [(run.status, run.reason) for run in runs] == [
        (RunStatus.SKIPPED, "parent_not_done"),
        (RunStatus.SUCCESS, None),
    ]


async def test_a_status_change_inside_work_does_not_touch_subtasks(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Правило смотрит на категорию, а не на факт смены статуса."""
    await enable_rule("close_children_with_parent")
    parent = await make_issue(summary="Родитель")
    child = await make_issue(summary="Подзадача")
    await links_service.create_link(
        db_session,
        initiator=owner,
        source=child,
        link_type=LinkType.SUBTASK_OF,
        target=parent,
    )

    await _start(db_session, parent, initiator=owner)
    await _drain(db_session)

    assert await _comments(db_session, parent, initiator=owner) == []


# --- Автодействие: зависшие задачи -----------------------------------------------------


async def test_the_scheduled_rule_nudges_and_then_stays_silent(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    make_saved_filter: Callable[..., Awaitable[Any]],
) -> None:
    """Правило комментирует зависшую задачу один раз и молчит, пока не выйдет срок.

    Отбор подменён сохранённым фильтром — это и есть штатный способ поменять набор
    задач без правки кода. Заодно проверяется, что ссылка на фильтр действительно
    вытесняет объявленную в коде строку: в ней стоит «без движения семь дней», и на
    свежей задаче она ничего бы не нашла.

    Второе молчание держится не на строке задачи: комментарий не двигает `updated_at`,
    и фильтр остался бы истинным. Держится оно на журнале срабатываний.
    """
    stale = await make_saved_filter(name="Задачи в работе", query="status_category: in_progress")
    await enable_rule("nudge_stale_issues", saved_filter=stale, params={"silence_days": 7})
    issue = await make_issue(summary="Зависшая задача")
    await _start(db_session, issue, initiator=owner)

    first = await engine.run_scheduled_rule(db_session, "nudge_stale_issues")

    assert [outcome.status for outcome in first] == [RunStatus.SUCCESS]
    assert len(await _comments(db_session, issue, initiator=owner)) == 1

    # Следующий тик расписания: срок молчания ещё не вышел.
    later = datetime.now(UTC) + timedelta(hours=7)
    second = await engine.run_scheduled_rule(db_session, "nudge_stale_issues", now=later)

    assert [outcome.status for outcome in second] == [RunStatus.SKIPPED]
    assert second[0].reason == "still_silent"
    assert len(await _comments(db_session, issue, initiator=owner)) == 1


async def test_the_scheduled_rule_can_also_drop_the_assignee(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    make_saved_filter: Callable[..., Awaitable[Any]],
) -> None:
    """Второе действие правила включается параметром, а не правкой кода."""
    stale = await make_saved_filter(name="Задачи в работе", query="status_category: in_progress")
    await enable_rule(
        "nudge_stale_issues",
        saved_filter=stale,
        params={"silence_days": 7, "unassign": True},
    )
    issue = await make_issue(summary="Зависшая задача", assignee=owner)
    await _start(db_session, issue, initiator=owner)

    outcomes = await engine.run_scheduled_rule(db_session, "nudge_stale_issues")

    assert outcomes[0].status is RunStatus.SUCCESS
    assert issue.assignee is None
    assert {action["action"] for action in outcomes[0].run.actions} == {"comment", "assign"}


# --- Макрос: оформить как релизную ------------------------------------------------------


async def test_the_macro_prepares_the_issue_in_one_call(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Макрос делает за один вызов то, что иначе было бы четырьмя запросами."""
    await enable_rule("prepare_release")
    issue = await make_issue(summary="Релиз 1.4", tags=["backend"])

    outcome = await automation_service.run_macro(
        db_session,
        "prepare_release",
        issue=issue,
        initiator=owner,
        params={"tags": ["release"], "priority": "blocker", "checklist": ["Собрать список"]},
    )

    assert outcome.status is RunStatus.SUCCESS
    # Теги дописываются, а не заменяются: макрос оформляет задачу, а не переписывает её.
    assert set(issue.tags) == {"backend", "release"}
    assert issue.priority is IssuePriority.BLOCKER
    items = await checklists_service.list_items(db_session, issue, initiator=owner)
    assert [item.text for item in items] == ["Собрать список"]


async def test_running_the_macro_twice_does_not_double_the_checklist(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Повтор — обычное дело у ручного действия, и удваивать чеклист он не должен.

    У пункта чеклиста нет ключа, поэтому различить «добавили второй раз» и «так и было»
    задним числом уже нечем — защита обязана стоять в самом правиле.
    """
    await enable_rule("prepare_release")
    issue = await make_issue(summary="Релиз 1.4")
    params = {"tags": [], "priority": None, "checklist": ["Прогнать регресс"]}  # noqa: RUF001

    await automation_service.run_macro(
        db_session, "prepare_release", issue=issue, initiator=owner, params=params
    )
    second = await automation_service.run_macro(
        db_session, "prepare_release", issue=issue, initiator=owner, params=params
    )

    items = await checklists_service.list_items(db_session, issue, initiator=owner)
    assert len(items) == 1
    # Второй заход ничего не сделал — и это видно в журнале как пропуск, а не как успех.
    assert second.status is RunStatus.SKIPPED
    assert second.reason == "nothing_to_do"
