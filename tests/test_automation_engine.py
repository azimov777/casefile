"""Движок автоматики: три формы правил, защита от циклов, изоляция ошибки, журнал.

Правила для тестов объявляются прямо здесь, обычным декоратором. Реестр глобальный на
процесс, поэтому ключи начинаются с `t13_` — так они не столкнутся ни с поставочными
правилами, ни с правилами других тестовых модулей. Сработать они не могут: движок
запускает только правило, у которого включена строка в базе, а включает её тест внутри
своей транзакции.

Проверяется прицельно то, что ломается молча.

Первое: цепочка «правило → событие → правило» обязана гаснуть. Второе: волна событий
(массовый перенос сотни задач) не должна размножаться. Третье: ошибка правила не
роняет ни соседей, ни запись о себе в журнале. Четвёртое: автодействие отбирает задачи
тем же поиском, что и API, — иначе правило работает не на том наборе задач, который
видит человек.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.automation import engine
from app.automation.context import RuleContext
from app.automation.registry import rule
from app.core.errors import AppError
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule, AutomationRun
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.repositories import AutomationRunRepository
from app.domain.automation import (
    AUTOMATION_PAYLOAD_KEY,
    RuleKind,
    RunStatus,
    RunTrigger,
    SkipReason,
)
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.events import EventType, OutboxStatus
from app.services import automation as automation_service
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services.event_bus import EventEnvelope, SubscriberRegistry
from app.services.issues import IssueChanges

MakeIssue = Callable[..., Awaitable[Issue]]
EnableRule = Callable[..., Awaitable[AutomationRule]]


# --- Правила, объявленные ради тестов -----------------------------------------------


class TagParams(BaseModel):
    model_config = {"extra": "forbid"}

    tag: str = "touched"


@rule(
    key="t13_tagger",
    name="Test tagger",
    kind=RuleKind.TRIGGER,
    events=(EventType.ISSUE_UPDATED, EventType.ISSUE_STATUS_CHANGED),
    params=TagParams,
)
async def t13_tagger(ctx: RuleContext) -> None:
    """Дописывает тег. Меняет задачу, поэтому годится и для проверки цепочек."""
    params = ctx.params
    assert isinstance(params, TagParams)
    if params.tag in ctx.target.tags:
        ctx.skip("already_tagged")
    await ctx.update(tags=[*ctx.target.tags, params.tag])


# Пара взаимно провоцирующих правил. Оба подписаны на `issue.updated` и оба **всегда**
# что-то меняют: в значение уходит идентификатор срабатывания, поэтому оно на каждом
# витке новое и единая точка изменений не схлопывает его в «изменений нет». Это не
# украшение теста: правило, записавшее то же самое значение, изменения не даёт, события
# не порождает и цепочки не образует — проверять на нём защиту было бы нечего.
#
# Реакции на себя тут нет: событие каждого ловит другой. Поэтому без потолка глубины эта
# пара не останавливается никогда — ровно то, что задача требует проверить тестом.
@rule(
    key="t13_ping",
    name="Test ping",
    kind=RuleKind.TRIGGER,
    events=(EventType.ISSUE_UPDATED,),
)
async def t13_ping(ctx: RuleContext) -> None:
    """Пишет описание, провоцируя `t13_pong`."""
    await ctx.update(description=f"ping {ctx.depth} {ctx.run_id}")


@rule(
    key="t13_pong",
    name="Test pong",
    kind=RuleKind.TRIGGER,
    events=(EventType.ISSUE_UPDATED,),
)
async def t13_pong(ctx: RuleContext) -> None:
    """Пишет название, провоцируя `t13_ping`."""
    await ctx.update(summary=f"pong {ctx.depth} {ctx.run_id}")


@rule(
    key="t13_breaker",
    name="Test breaker",
    kind=RuleKind.TRIGGER,
    events=(EventType.ISSUE_UPDATED,),
)
async def t13_breaker(ctx: RuleContext) -> None:
    """Всегда падает. Нужен проверке изоляции и записи ошибки в журнал."""
    raise RuntimeError("rule exploded on purpose")


@rule(
    key="t13_closer",
    name="Test closer",
    kind=RuleKind.TRIGGER,
    events=(EventType.ISSUE_UPDATED,),
)
async def t13_closer(ctx: RuleContext) -> None:
    """Пытается закрыть задачу без резолюции — переход воркфлоу этого не позволит."""
    closed = await ctx.status("closed")
    await ctx.set_status(closed)


@rule(
    key="t13_commenter",
    name="Test scheduled commenter",
    kind=RuleKind.SCHEDULED,
    schedule=timedelta(hours=1),
    query="status_category: new",
)
async def t13_commenter(ctx: RuleContext) -> None:
    """Комментирует задачу. Автодействие: отбор идёт строкой языка запросов."""
    await ctx.comment(f"scheduled visit to {ctx.target.key}")


@rule(
    key="t13_macro",
    name="Test macro",
    kind=RuleKind.MACRO,
    params=TagParams,
)
async def t13_macro(ctx: RuleContext) -> None:
    """Дописывает тег по ручному вызову."""
    params = ctx.params
    assert isinstance(params, TagParams)
    await ctx.update(tags=[*ctx.target.tags, params.tag])


@rule(
    key="t13_broken_macro",
    name="Test broken macro",
    kind=RuleKind.MACRO,
)
async def t13_broken_macro(ctx: RuleContext) -> None:
    """Всегда падает. Нужен проверке того, что неудача макроса приходит записью журнала."""
    raise RuntimeError("macro exploded on purpose")


# --- Вспомогательное ----------------------------------------------------------------


def _automation_registry() -> SubscriberRegistry:
    """Реестр подписчиков ровно с движком автоматики.

    Свой, а не глобальный: глобальный общий на процесс, и тест, полагающийся на его
    состав, зависел бы от того, какие модули успели импортироваться.
    """
    registry = SubscriberRegistry()

    async def dispatch(session: AsyncSession, event: EventEnvelope) -> None:
        await engine.dispatch_event(session, event)

    registry.register(dispatch, name="automation")
    return registry


async def _drain(session: AsyncSession, *, limit: int = 200) -> int:
    """Прогоняет очередь событий до пустоты. Возвращает число обработанных событий.

    Потолок обязателен: незатухающая цепочка правил без него повесила бы тест намертво
    вместо того, чтобы упасть с внятным числом.
    """
    registry = _automation_registry()
    processed = 0
    while processed < limit:
        outcome = await events_service.process_next_event(session, registry=registry)
        if outcome is None:
            return processed
        processed += 1
    raise AssertionError(f"event queue did not drain within {limit} events")


async def _runs(session: AsyncSession, rule_key: str) -> list[AutomationRun]:
    statement = (
        select(AutomationRun)
        .where(AutomationRun.rule_key == rule_key)
        .order_by(AutomationRun.created_at, AutomationRun.id)
    )
    return list((await session.scalars(statement)).unique())


async def _events(session: AsyncSession, event_type: str) -> list[Any]:
    from app.db.models.event import OutboxEvent

    statement = (
        select(OutboxEvent)
        .where(OutboxEvent.event_type == event_type)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
    )
    return list((await session.scalars(statement)).unique())


async def _start_progress(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
) -> None:
    """Переводит задачу в работу настоящим переходом воркфлоу."""
    in_progress = await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.STATUS,
        "in_progress",
        initiator=initiator,
    )
    await issues_service.apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(status=in_progress),
        action="issue.transition",
    )


# --- Синхронизация реестра -----------------------------------------------------------


async def test_new_rules_arrive_disabled(db_session: AsyncSession) -> None:
    """Правило, приехавшее с выкладкой, не должно менять задачи до того, как его включат."""
    created = await automation_service.sync_rules(db_session)

    assert "t13_tagger" in created
    rule_row = await automation_service.get_rule(db_session, "t13_tagger")
    assert rule_row.is_enabled is False
    # Параметры заполнены умолчаниями схемы, а не пустым словарём: правило, включённое
    # без настройки, обязано работать.
    assert rule_row.params == {"tag": "touched"}


async def test_synchronisation_is_idempotent(db_session: AsyncSession) -> None:
    """Повторный старт процесса не заводит вторую строку и не сбрасывает настройки."""
    await automation_service.sync_rules(db_session)
    rule_row = await automation_service.get_rule(db_session, "t13_tagger")
    rule_row.is_enabled = True

    created = await automation_service.sync_rules(db_session)

    assert created == []
    assert (await automation_service.get_rule(db_session, "t13_tagger")).is_enabled is True


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий на отдельных соединениях, с настоящим коммитом.

    Гонку на уникальном ключе нельзя поставить обычной `db_session`: она живёт внутри
    одной транзакции теста, которая в конце откатывается, а конфликт виден только между
    разными транзакциями, каждая со своим коммитом. Плата за это — убирать за собой
    приходится руками: откат теста сюда не достаёт.
    """
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def test_parallel_synchronisation_survives_the_race(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Три процесса, стартовавшие на пустой базе одновременно, не падают и не двоят строки.

    Ровно то, что происходит при подъёме контура с нуля: API в lifespan, воркер и
    планировщик заводят строки правил в одну и ту же секунду.
    """
    keys = sorted(definition.key for definition in automation_service.definitions())
    # Барьер, а не надежда на планировщик задач: без него первый вызов успевал бы
    # закоммитить строки до того, как второй начнёт вставку, и тест проверял бы
    # последовательный запуск под видом одновременного.
    barrier = asyncio.Barrier(3)

    async def sync() -> list[str]:
        async with committing_sessions() as session:
            await barrier.wait()
            created = await automation_service.sync_rules(session)
            await session.commit()
            return created

    try:
        results = await asyncio.gather(sync(), sync(), sync())

        # Ключ заводит ровно один из трёх, и он же его возвращает: остальные двое
        # получают пустой список, а не тот, который собирались завести.
        assert sorted(key for created in results for key in created) == keys
        async with committing_sessions() as session:
            rows = await session.execute(
                select(AutomationRule.rule_key, func.count())
                .where(AutomationRule.rule_key.in_(keys))
                .group_by(AutomationRule.rule_key)
            )
            assert sorted(rows.all()) == [(key, 1) for key in keys]
    finally:
        async with committing_sessions() as session:
            await session.execute(delete(AutomationRule).where(AutomationRule.rule_key.in_(keys)))
            await session.commit()


# --- Триггеры -------------------------------------------------------------------------


async def test_a_trigger_reacts_to_its_event(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Правило срабатывает на событие и меняет задачу теми же сценариями, что и человек."""
    await enable_rule("t13_tagger")
    issue = await make_issue()
    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Переписанное название"),
    )

    await _drain(db_session)

    assert "touched" in issue.tags
    runs = await _runs(db_session, "t13_tagger")
    assert [run.status for run in runs][:1] == [RunStatus.SUCCESS]
    assert runs[0].trigger is RunTrigger.EVENT
    assert runs[0].issue_key == issue.key
    # Настоящий инициатор виден рядом с системным исполнителем: без него связку
    # «правило X, запущено из-за действия актора Y» восстановить нечем.
    assert runs[0].initiator_key == owner.key
    assert runs[0].actions[0]["action"] == "update"


async def test_a_disabled_rule_does_not_run(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Выключенное правило не срабатывает и не оставляет следа в журнале."""
    issue = await make_issue()
    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Другое название"),
    )

    await _drain(db_session)

    assert "touched" not in issue.tags
    assert await _runs(db_session, "t13_tagger") == []


async def test_a_rule_bound_to_a_queue_ignores_other_queues(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Привязка отсекает задачу до вызова правила, а не внутри него."""
    other = await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="OPS",
        name="Эксплуатация",
    )
    await enable_rule("t13_tagger", queue=other)

    mine = await make_issue(queue=queue)
    await issues_service.update_issue(
        db_session,
        mine,
        initiator=owner,
        changes=IssueChanges(summary="Название из чужой очереди"),
    )

    await _drain(db_session)

    assert "touched" not in mine.tags
    assert await _runs(db_session, "t13_tagger") == []


async def test_the_event_of_a_rule_change_carries_the_automation_trace(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Изменение правила помечено в событии: правило, срабатывание и глубина цепочки.

    На этой отметке держится вся защита от циклов: между изменением и следующим
    срабатыванием стоит outbox, и передать глубину больше нечем.
    """
    await enable_rule("t13_tagger")
    issue = await make_issue()
    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Название"),
    )

    await _drain(db_session)

    events = await _events(db_session, EventType.ISSUE_UPDATED)
    human, automatic = events[0], events[-1]
    assert AUTOMATION_PAYLOAD_KEY not in human.payload
    trace = automatic.payload[AUTOMATION_PAYLOAD_KEY]
    assert trace["rule"] == "t13_tagger"
    assert trace["depth"] == 1
    runs = await _runs(db_session, "t13_tagger")
    # Идентификатор срабатывания в событии равен идентификатору записи журнала: по нему
    # цепочка «срабатывание → изменение → событие» проходится в обе стороны.
    assert trace["run"] == str(runs[0].id)


# --- Защита от циклов -----------------------------------------------------------------


async def test_a_rule_does_not_react_to_its_own_change(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Самый короткий цикл: правило меняет задачу и ловит собственное событие."""
    await enable_rule("t13_tagger", params={"tag": "first"})
    issue = await make_issue()
    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Название"),
    )

    await _drain(db_session)

    runs = await _runs(db_session, "t13_tagger")
    assert [run.status for run in runs] == [RunStatus.SUCCESS, RunStatus.SKIPPED]
    assert runs[1].reason == SkipReason.SELF_TRIGGERED.value
    assert issue.tags.count("first") == 1


async def test_mutually_provoking_rules_are_stopped_by_the_chain_guard(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Два правила, провоцирующие друг друга, обязаны погаснуть.

    `t13_ping` пишет описание, `t13_pong` — название, оба подписаны на `issue.updated`
    и оба всегда что-то меняют. Реакции на себя здесь нет: событие каждого ловит
    **другой**, и первая защита молчит. Гасит цепочку потолок глубины.

    Тест обязателен по условию задачи: без него первая же пара взаимных правил положит
    систему, и обнаружится это в проде.
    """
    await enable_rule("t13_ping")
    await enable_rule("t13_pong")
    issue = await make_issue()

    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Название"),
    )

    # Само по себе завершение `_drain` и есть проверка: незатухающая цепочка упёрлась бы
    # в его потолок и уронила тест.
    await _drain(db_session)

    depth_limit = engine.Guards.from_settings().max_chain_depth
    runs = [*await _runs(db_session, "t13_ping"), *await _runs(db_session, "t13_pong")]
    assert runs, "the rules must have run at least once"
    assert max(run.chain_depth for run in runs) <= depth_limit + 1
    stopped = [run for run in runs if run.reason == SkipReason.CHAIN_DEPTH_EXCEEDED.value]
    assert stopped, "the chain guard must have stopped the pair"
    # И ни одно событие не осталось необработанным: цепочка закончилась, а не упёрлась
    # в потолок повторов доставки.
    assert await _pending_events(db_session) == 0


async def _pending_events(session: AsyncSession) -> int:
    from sqlalchemy import func

    from app.db.models.event import OutboxEvent

    statement = (
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
    )
    return (await session.scalar(statement)) or 0


async def test_a_wave_of_events_does_not_multiply(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Волна событий по разным задачам обрабатывается один раз, а не размножается.

    Массовая правка даёт по событию `issue.updated` на каждую затронутую задачу.
    Каждое законно, каждое первого уровня — ни реакции на себя, ни роста глубины тут
    нет. Проверяется, что число срабатываний равно числу задач, а не растёт кратно.
    """
    await enable_rule("t13_tagger")
    issues = [await make_issue(summary=f"Задача {index}") for index in range(5)]

    for issue in issues:
        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=IssueChanges(deadline=None, description=f"Волна {issue.key}"),
        )

    await _drain(db_session)

    runs = await _runs(db_session, "t13_tagger")
    successful = [run for run in runs if run.status is RunStatus.SUCCESS]
    assert len(successful) == len(issues)
    assert {run.issue_key for run in successful} == {issue.key for issue in issues}


async def test_the_rate_limit_stops_a_rule_hammering_one_issue(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Лимит срабатываний на задачу за окно: третья правка подряд правило не запускает.

    Настоящие пороги (десять за минуту) проверялись бы двенадцатью правками; для теста
    порог занижен до двух — механика от этого не меняется.

    Правило взято такое, которое **всегда** что-то меняет: правило, отвечающее «уже
    сделано», в лимит не попадает вовсе, и это тоже намеренно — пропуски задачу не
    меняют и цикла не образуют.
    """
    rule_row = await enable_rule("t13_ping")
    issue = await make_issue()
    guards = engine.Guards(max_chain_depth=5, rate_limit=2, rate_window=timedelta(minutes=1))
    monkeypatch.setattr(engine.Guards, "from_settings", classmethod(lambda cls: guards))

    for index in range(4):
        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=IssueChanges(summary=f"Название {index}"),
        )
        await _drain(db_session)

    runs = await _runs(db_session, "t13_ping")
    limited = [run for run in runs if run.reason == SkipReason.RATE_LIMITED.value]
    assert limited, "the rate limit must have stopped the rule"
    successes = await AutomationRunRepository(db_session).count_since(
        rule_id=rule_row.id,
        issue_id=issue.id,
        since=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert successes == guards.rate_limit


# --- Изоляция ошибки --------------------------------------------------------------------


async def test_a_failing_rule_lands_in_the_journal_and_spares_its_neighbours(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Падение правила — строка в журнале, а не потерянное срабатывание соседа.

    Изоляции шины для этого мало: её откат унёс бы и запись о падении. Поэтому движок
    ловит исключение сам, а журнал пишет уже снаружи вложенной транзакции правила.
    """
    await enable_rule("t13_breaker")
    await enable_rule("t13_tagger")
    issue = await make_issue()

    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Название"),
    )
    await _drain(db_session)

    broken = await _runs(db_session, "t13_breaker")
    assert broken[0].status is RunStatus.FAILED
    assert "rule exploded on purpose" in (broken[0].error or "")
    # Сосед отработал, несмотря на падение.
    assert "touched" in issue.tags


async def test_a_rule_cannot_bypass_the_workflow(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Действие правила идёт через те же проверки перехода, что и запрос человека.

    Из `open` в `closed` ребра в процессе по умолчанию нет. Правило не «тихо ничего не
    делает» и не проходит мимо графа — оно падает, и причина видна в журнале.
    """
    await enable_rule("t13_closer")
    issue = await make_issue()

    await issues_service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=IssueChanges(summary="Название"),
    )
    await _drain(db_session)

    runs = await _runs(db_session, "t13_closer")
    assert runs[0].status is RunStatus.FAILED
    assert "TransitionNotAllowedError" in (runs[0].error or "")
    assert issue.status.category is not StatusCategory.DONE


# --- Автодействия -----------------------------------------------------------------------


async def test_a_scheduled_rule_selects_issues_through_search(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Автодействие отбирает задачи тем же поиском, что и API, и сдвигает расписание."""
    rule_row = await enable_rule("t13_commenter")
    fresh = await make_issue(summary="Новая задача")
    working = await make_issue(summary="Задача в работе")
    await _start_progress(db_session, working, initiator=owner)

    outcomes = await engine.run_scheduled_rule(db_session, "t13_commenter")

    touched = {outcome.run.issue_key for outcome in outcomes}
    assert fresh.key in touched
    assert working.key not in touched
    assert all(outcome.run.trigger is RunTrigger.SCHEDULE for outcome in outcomes)
    assert rule_row.last_run_at is not None
    assert rule_row.next_run_at is not None and rule_row.next_run_at > rule_row.last_run_at


async def test_a_scheduled_rule_is_not_due_before_its_time(
    db_session: AsyncSession,
    enable_rule: EnableRule,
    make_issue: MakeIssue,
) -> None:
    """Второй заход до срока не выполняется: расписание считается от момента запуска."""
    await enable_rule("t13_commenter")
    await make_issue()
    await engine.run_scheduled_rule(db_session, "t13_commenter")

    assert await engine.due_rule_keys(db_session) == []
    assert await engine.run_scheduled_rule(db_session, "t13_commenter") == []


async def test_a_scheduled_rule_narrows_the_selection_by_its_queue(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Привязка к очереди складывается с отбором, а не дописывается в строку текстом."""
    other = await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="OPS",
        name="Эксплуатация",
    )
    await enable_rule("t13_commenter", queue=other)
    mine = await make_issue(queue=queue)

    outcomes = await engine.run_scheduled_rule(db_session, "t13_commenter")

    assert mine.key not in {outcome.run.issue_key for outcome in outcomes}


# --- Макросы ------------------------------------------------------------------------------


async def test_a_macro_runs_by_hand_with_per_call_params(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Макрос запускается вызовом; параметры вызова перекрывают сохранённые."""
    await enable_rule("t13_macro", params={"tag": "stored"})
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t13_macro",
        issue=issue,
        initiator=owner,
        params={"tag": "per_call"},
    )

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.run.trigger is RunTrigger.MANUAL
    assert "per_call" in issue.tags
    assert "stored" not in issue.tags
    # Инициатор ручного запуска — тот, кто его сделал, а исполняется правило от системы.
    assert outcome.run.initiator_key == owner.key


async def test_a_trigger_cannot_be_run_as_a_macro(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Форма правила проверяется до выполнения: триггеру нечем заменить событие."""
    await enable_rule("t13_tagger")
    issue = await make_issue()

    with pytest.raises(AppError) as error:
        await automation_service.run_macro(
            db_session,
            "t13_tagger",
            issue=issue,
            initiator=owner,
        )
    assert error.value.code == "automation_rule_kind_mismatch"


async def test_a_disabled_macro_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Выключатель работает для всех способов запуска, а не только для фоновых."""
    issue = await make_issue()

    with pytest.raises(AppError) as error:
        await automation_service.run_macro(db_session, "t13_macro", issue=issue, initiator=owner)
    assert error.value.code == "automation_rule_disabled"


async def test_a_macro_refuses_an_issue_from_another_queue(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Отбор по привязке идёт до вызова и у ручного запуска тоже."""
    other = await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="OPS",
        name="Эксплуатация",
    )
    await enable_rule("t13_macro", queue=other)
    issue = await make_issue(queue=queue)

    with pytest.raises(AppError) as error:
        await automation_service.run_macro(db_session, "t13_macro", issue=issue, initiator=owner)
    assert error.value.code == "automation_rule_out_of_scope"


async def test_a_failing_macro_answers_with_a_journal_entry(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Ошибка внутри макроса — это результат срабатывания, а не отказ в запросе.

    Проброс исключения откатил бы транзакцию вместе с записью журнала, и единственный
    след неудачного запуска пропал бы ровно тогда, когда он нужен.
    """
    await enable_rule("t13_broken_macro")
    issue = await make_issue()

    outcome = await automation_service.run_macro(
        db_session,
        "t13_broken_macro",
        issue=issue,
        initiator=owner,
    )

    assert outcome.status is RunStatus.FAILED
    assert "macro exploded on purpose" in (outcome.run.error or "")
    assert (await _runs(db_session, "t13_broken_macro"))[0].id == outcome.run.id


# --- Параметры ------------------------------------------------------------------------------


async def test_parameters_are_validated_when_saved(
    db_session: AsyncSession,
    owner: Actor,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Мусор в параметрах — отказ при сохранении, а не падение в фоне через неделю."""
    with pytest.raises(AppError) as error:
        await automation_service.update_rule(
            db_session,
            automation_rules["t13_tagger"],
            initiator=owner,
            params={"unknown": 1},
        )
    assert error.value.code == "automation_params_invalid"


async def test_a_saved_filter_belongs_only_to_scheduled_rules(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    automation_rules: dict[str, AutomationRule],
    make_saved_filter: Callable[..., Awaitable[Any]],
) -> None:
    """Фильтр у триггера молча ни на что не влиял бы — поэтому он отвергается."""
    saved = await make_saved_filter()

    with pytest.raises(AppError) as error:
        await automation_service.update_rule(
            db_session,
            automation_rules["t13_tagger"],
            initiator=owner,
            saved_filter=saved,
        )
    assert error.value.code == "invalid_automation_rule"
