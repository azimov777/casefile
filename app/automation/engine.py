"""Движок автоматики: отбор правил, защита от циклов, выполнение и журнал.

Один вход на три формы. Триггер приходит из шины (`dispatch_event`), автодействие — из
планировщика (`run_scheduled_rule`), макрос — из API или MCP (`run_macro`). Все три
сходятся в `run_rule`, и это главное свойство модуля: защита от зацикливания, изоляция
ошибки и запись в журнал стоят в одном месте, а не в трёх похожих.

## Защита от циклов — это три независимых механизма, а не один

Каждый ловит свой случай, и ни один не заменяет остальные.

1. **Реакция на себя.** Правило изменило задачу → родилось событие → правило снова
   сработало. Самый короткий цикл, и ловится он сравнением ключа правила со следом в
   событии. Стоит первым, потому что срабатывает чаще прочих.
2. **Глубина цепочки.** Правило A изменило задачу, на это сработало правило B, на его
   изменение — снова A. Ключи разные, первый механизм молчит. Ловится счётчиком,
   который едет в полезной нагрузке события и растёт на каждом звене.
3. **Лимит срабатываний на задачу за окно.** Ловит то, что не ловят первые два: волну.
   Завершение спринта на двести задач даёт двести событий `issue.updated`, каждое
   законно, каждое первого уровня — глубина не растёт, реакции на себя нет. Без лимита
   правило отработает двести раз и породит двести новых событий.

Первые два дешёвые и стоят до всякой работы. Третий требует запроса в журнал, поэтому
идёт последним.

## Ошибка правила ловится здесь, а не оставляется шине

Шина уже изолирует подписчиков вложенной транзакцией, и этого достаточно, чтобы упавшее
правило не мешало соседям. Но откат вложенной транзакции унёс бы вместе с работой
правила и запись о том, что оно упало, — то есть ровно ту строку журнала, ради которой в
журнал и смотрят. Поэтому каждое правило выполняется в **своей** вложенной транзакции,
исключение ловится здесь, и запись журнала пишется уже снаружи неё.

## Что попадает в журнал, а что нет

Журнал пишется на **рассмотренное** срабатывание: правило подошло по типу события,
включено и не отсечено привязкой к очереди. Выключенное правило, чужая очередь и
отсутствующее объявление записи не дают — это не срабатывания, и журнал из них состоял
бы целиком.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.context import RuleContext, RuleSkipped, action_payload
from app.automation.registry import RuleDefinition, load_rules
from app.automation.registry import registry as rule_registry
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models.actor import Actor
from app.db.models.automation import MAX_ERROR_LENGTH, AutomationRule, AutomationRun
from app.db.models.issue import Issue
from app.db.repositories import AutomationRuleRepository, AutomationRunRepository
from app.domain.automation import (
    AutomationCause,
    RuleKind,
    RunStatus,
    RunTrigger,
    SkipReason,
    depth_of,
)
from app.domain.errors import (
    AutomationRuleDisabledError,
    AutomationRuleKindError,
    AutomationRuleNotFoundError,
    AutomationRuleOutOfScopeError,
    AutomationRuleUnavailableError,
    IssueNotFoundError,
)
from app.services import actors as actors_service
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import search as search_service
from app.services.event_bus import EventEnvelope

logger = get_logger("automation")


@dataclass(frozen=True, slots=True)
class Guards:
    """Пороги защиты от зацикливания. Настройки, а не константы: подбираются на живых правилах."""

    max_chain_depth: int
    rate_limit: int
    rate_window: timedelta

    @classmethod
    def from_settings(cls) -> Guards:
        settings = get_settings()
        return cls(
            max_chain_depth=settings.automation_max_chain_depth,
            rate_limit=settings.automation_rate_limit,
            rate_window=timedelta(seconds=settings.automation_rate_window),
        )


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Итог одного срабатывания: запись журнала и то, что в неё легло.

    Запись возвращается целиком, а не её идентификатор: и API ручного запуска, и тесты
    спрашивают у результата статус, причину и список действий, а второй поход в базу за
    только что записанной строкой был бы работой ради формы.
    """

    run: AutomationRun

    @property
    def status(self) -> RunStatus:
        return self.run.status

    @property
    def reason(self) -> str | None:
        return self.run.reason

    @property
    def succeeded(self) -> bool:
        return self.run.status is RunStatus.SUCCESS


# --- Триггеры ----------------------------------------------------------------------


async def dispatch_event(session: AsyncSession, event: EventEnvelope) -> list[RunOutcome]:
    """Раздаёт событие триггерам. Точка входа подписчика шины.

    Порядок отбора — от дешёвого к дорогому: тип события, состояние правила, привязка к
    очереди, и только потом загрузка задачи и защиты. Правил в реестре немного, а
    событий много, поэтому лишний запрос здесь — это лишний запрос на каждое изменение
    в трекере.
    """
    load_rules()
    definitions = rule_registry.for_event(event.event_type)
    if not definitions:
        return []

    rules = AutomationRuleRepository(session)
    selected: list[tuple[RuleDefinition, AutomationRule]] = []
    for definition in definitions:
        rule = await rules.get_by_key(definition.key)
        if rule is None or not rule.is_enabled:
            continue
        selected.append((definition, rule))
    if not selected:
        return []

    issue = await _issue_of(session, event)
    system = await actors_service.get_system_actor(session)
    initiator = await _initiator_of(session, event, fallback=system)
    guards = Guards.from_settings()

    outcomes: list[RunOutcome] = []
    for definition, rule in selected:
        if not _in_scope(rule, issue):
            continue
        outcomes.append(
            await run_rule(
                session,
                definition=definition,
                rule=rule,
                issue=issue,
                event=event,
                initiator=initiator,
                system=system,
                trigger=RunTrigger.EVENT,
                guards=guards,
            )
        )
    return outcomes


# --- Автодействия ------------------------------------------------------------------


async def due_rule_keys(session: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """Ключи автодействий, которым пришло время. Без блокировки строк.

    Отдельный дешёвый вопрос перед работой: планировщик берёт каждое правило в своей
    транзакции, и держать блокировку на всех сразу, пока выполняется первое, незачем.
    """
    load_rules()
    keys = [item.key for item in rule_registry.of_kind(RuleKind.SCHEDULED)]
    if not keys:
        return []
    moment = now or datetime.now(UTC)
    due = await AutomationRuleRepository(session).claim_due(now=moment, keys=keys)
    return [rule.rule_key for rule in due]


async def run_scheduled_rule(
    session: AsyncSession,
    rule_key: str,
    *,
    now: datetime | None = None,
    guards: Guards | None = None,
) -> list[RunOutcome]:
    """Выполняет одно автодействие: отбирает задачи фильтром и прогоняет по каждой.

    Отбор идёт **через сценарий поиска**, а не своим запросом. Иначе у фильтра появилось
    бы второе толкование: правило срабатывало бы не на том наборе задач, который
    показывает интерфейс по той же строке, и расхождение было бы молчаливым.

    Время всегда пересчитывается заново: `today() - 7d` в строке правила означает семь
    дней от момента запуска, а не от момента, когда правило сохранили. Ради этого отбор
    и хранится строкой.

    Строка правила берётся с блокировкой: планировщик обязан быть в единственном
    экземпляре, но если второй всё-таки поднимут, он пройдёт мимо занятой строки, а не
    выполнит то же автодействие второй раз.
    """
    load_rules()
    moment = now or datetime.now(UTC)
    settings = get_settings()
    rules = AutomationRuleRepository(session)

    claimed = await rules.claim_due(now=moment, keys=[rule_key])
    if not claimed:
        return []
    rule = claimed[0]

    definition = rule_registry.get(rule.rule_key)
    if definition is None or definition.kind is not RuleKind.SCHEDULED:
        # Правило пропало из кода между выборкой ключей и захватом строки. Расписание
        # всё равно сдвигаем: иначе планировщик будет брать эту строку каждый тик.
        _reschedule(rule, moment, definition)
        return []

    system = await actors_service.get_system_actor(session)
    outcome_guards = guards or Guards.from_settings()

    try:
        issues = await _scheduled_issues(session, rule, definition, initiator=system)
    except AppError as exc:
        # Протухший отбор — сломанный сохранённый фильтр, удалённое поле — не должен
        # останавливать планировщик и не должен молча повторяться каждый тик. Одна
        # запись в журнал с причиной, расписание сдвигается как обычно.
        logger.exception("Automation rule %s failed to select issues", rule.rule_key)
        run = await _write_run(
            session,
            definition=definition,
            rule=rule,
            issue=None,
            event=None,
            initiator=system,
            trigger=RunTrigger.SCHEDULE,
            status=RunStatus.FAILED,
            reason="filter_failed",
            actions=[],
            error=_short_error(exc),
            depth=1,
            duration_ms=0,
        )
        _reschedule(rule, moment, definition)
        return [RunOutcome(run=run)]

    outcomes: list[RunOutcome] = []
    for issue in issues[: settings.automation_batch_size]:
        outcomes.append(
            await run_rule(
                session,
                definition=definition,
                rule=rule,
                issue=issue,
                event=None,
                initiator=system,
                system=system,
                trigger=RunTrigger.SCHEDULE,
                guards=outcome_guards,
            )
        )
    if len(issues) > settings.automation_batch_size:
        # Молчаливое срезание выборки читалось бы как «правило обработало всё».
        logger.warning(
            "Automation rule %s matched %s issues, processed %s; the rest wait for the next tick",
            rule.rule_key,
            len(issues),
            settings.automation_batch_size,
        )
    _reschedule(rule, moment, definition)
    await rules.flush()
    return outcomes


# --- Макросы -----------------------------------------------------------------------


async def run_macro(
    session: AsyncSession,
    rule_key: str,
    *,
    issue: Issue,
    initiator: Actor,
    params: Mapping[str, Any] | None = None,
) -> RunOutcome:
    """Запускает макрос по конкретной задаче.

    Ошибка внутри правила **не** превращается в ошибку вызова: она уходит в журнал, а
    вызывающий получает запись со статусом `failed` и текстом причины. Проброс наружу
    откатил бы транзакцию запроса вместе с этой записью, и единственный след неудачного
    макроса пропал бы ровно в тот момент, когда он нужен.

    Отказы **до** выполнения — другое дело: выключенное правило, не та форма, чужая
    очередь — это отказ в запросе, а не результат работы правила, и он идёт исключением.
    """
    load_rules()
    definition = rule_registry.get(rule_key)
    rule = await AutomationRuleRepository(session).get_by_key(rule_key)
    if rule is None:
        raise AutomationRuleNotFoundError(details={"rule": rule_key})
    if definition is None:
        raise AutomationRuleUnavailableError(details={"rule": rule_key})
    if definition.kind is not RuleKind.MACRO:
        raise AutomationRuleKindError(
            details={"rule": rule_key, "kind": definition.kind.value, "expected": RuleKind.MACRO},
        )
    if not rule.is_enabled:
        raise AutomationRuleDisabledError(details={"rule": rule_key})
    if not _in_scope(rule, issue):
        raise AutomationRuleOutOfScopeError(
            details={
                "rule": rule_key,
                "issue": issue.key,
                "queue": None if rule.queue is None else rule.queue.key,
            },
        )

    system = await actors_service.get_system_actor(session)
    return await run_rule(
        session,
        definition=definition,
        rule=rule,
        issue=issue,
        event=None,
        initiator=initiator,
        system=system,
        trigger=RunTrigger.MANUAL,
        guards=Guards.from_settings(),
        params_override=params,
    )


# --- Общее выполнение ---------------------------------------------------------------


async def run_rule(
    session: AsyncSession,
    *,
    definition: RuleDefinition,
    rule: AutomationRule,
    issue: Issue | None,
    event: EventEnvelope | None,
    initiator: Actor,
    system: Actor,
    trigger: RunTrigger,
    guards: Guards,
    params_override: Mapping[str, Any] | None = None,
) -> RunOutcome:
    """Выполняет одно правило и записывает результат в журнал. Наружу не бросает.

    Единственный путь исполнения правила в проекте. Всё, что должно случиться с каждым
    срабатыванием — защиты, системный актор, след в событиях, изоляция ошибки, запись
    журнала, — стоит здесь ровно по одному разу.
    """
    incoming_depth = 0 if event is None else depth_of(event.payload)
    depth = incoming_depth + 1

    skip = await _guarded(
        session,
        definition=definition,
        rule=rule,
        issue=issue,
        event=event,
        guards=guards,
        incoming_depth=incoming_depth,
    )
    if skip is not None:
        return RunOutcome(
            run=await _write_run(
                session,
                definition=definition,
                rule=rule,
                issue=issue,
                event=event,
                initiator=initiator,
                trigger=trigger,
                status=RunStatus.SKIPPED,
                reason=skip.value,
                actions=[],
                error=None,
                depth=depth,
                duration_ms=0,
            )
        )

    run_id = uuid.uuid4()
    context = RuleContext(
        session=session,
        definition=definition,
        rule=rule,
        run_id=run_id,
        depth=depth,
        actor=system,
        initiator=initiator,
        params=definition.parse_params({**rule.params, **(params_override or {})}),
        issue=issue,
        event=event,
    )
    cause = AutomationCause(rule_key=definition.key, run_id=run_id, depth=depth)

    status = RunStatus.SUCCESS
    reason: str | None = None
    error: str | None = None
    started = time.perf_counter()
    try:
        # Своя вложенная транзакция на правило. Изоляция шины уже есть, но её откат унёс
        # бы и запись журнала — а она пишется ниже, снаружи этого блока, и обязана
        # пережить падение правила.
        async with session.begin_nested():
            with events_service.automation_cause(cause):
                await definition.handler(context)
    except RuleSkipped as skipped:
        # Пропуск откатывает всё, что правило успело сделать до него, — это и есть его
        # смысл: «условие не выполнено, меня здесь не было». Список действий очищается,
        # иначе журнал показал бы работу, которой в базе не осталось.
        context.actions.clear()
        status = RunStatus.SKIPPED
        reason = skipped.reason
    except Exception as exc:
        logger.exception(
            "Automation rule %s failed on %s",
            definition.key,
            "-" if issue is None else issue.key,
        )
        context.actions.clear()
        status = RunStatus.FAILED
        error = _short_error(exc)
    else:
        if not context.actions:
            # Правило отработало и ничего не сделало. Это успех с точки зрения кода и
            # пропуск с точки зрения журнала: считать такое срабатывание в лимит значило
            # бы, что правило, честно молчащее на волне событий, само себя заблокирует.
            status = RunStatus.SKIPPED
            reason = SkipReason.NOTHING_TO_DO.value

    duration_ms = int((time.perf_counter() - started) * 1000)
    return RunOutcome(
        run=await _write_run(
            session,
            definition=definition,
            rule=rule,
            issue=issue,
            event=event,
            initiator=initiator,
            trigger=trigger,
            status=status,
            reason=reason,
            actions=action_payload(context.actions),
            error=error,
            depth=depth,
            duration_ms=duration_ms,
            run_id=run_id,
        )
    )


# --- Защиты --------------------------------------------------------------------------


async def _guarded(
    session: AsyncSession,
    *,
    definition: RuleDefinition,
    rule: AutomationRule,
    issue: Issue | None,
    event: EventEnvelope | None,
    guards: Guards,
    incoming_depth: int,
) -> SkipReason | None:
    """Проверяет три защиты по порядку и возвращает причину пропуска или `None`."""
    if event is not None:
        cause = AutomationCause.of(event.payload)
        if cause is not None and cause.rule_key == definition.key:
            return SkipReason.SELF_TRIGGERED
        if incoming_depth >= guards.max_chain_depth:
            return SkipReason.CHAIN_DEPTH_EXCEEDED

    since = datetime.now(UTC) - guards.rate_window
    fired = await AutomationRunRepository(session).count_since(
        rule_id=rule.id,
        issue_id=None if issue is None else issue.id,
        since=since,
    )
    if fired >= guards.rate_limit:
        return SkipReason.RATE_LIMITED
    return None


# --- Внутреннее ----------------------------------------------------------------------


def _in_scope(rule: AutomationRule, issue: Issue | None) -> bool:
    """Задача попадает в область правила. Проверка стоит до вызова, а не внутри правила.

    Правило без привязки видит все очереди. Привязанное правило без задачи (событие
    доски или спринта) не запускается: проверить принадлежность нечем, а «наверное,
    подходит» — это ровно тот случай, когда правило одной очереди трогает чужую.
    """
    if rule.queue_id is None:
        return True
    return issue is not None and issue.queue_id == rule.queue_id


async def _issue_of(session: AsyncSession, event: EventEnvelope) -> Issue | None:
    """Задача, к которой относится событие, если она есть и ещё существует.

    Ключ берётся из полезной нагрузки, а не из `object_key`: у события комментария или
    пункта чеклиста `object_key` — это составной ключ `TRK-1:<uuid>`, а снимок задачи
    лежит в нагрузке у всех событий, которые к задаче относятся.

    Удалённая задача даёт `None`, а не ошибку: `issue.deleted` — законное событие, и
    правило, подписанное на него, работает с нагрузкой, а не со строкой в базе.
    """
    snapshot = event.payload.get("issue")
    if not isinstance(snapshot, dict):
        return None
    key = snapshot.get("key")
    if not isinstance(key, str):
        return None
    try:
        return await issues_service.get_issue_by_key(session, key)
    except IssueNotFoundError:
        return None


async def _initiator_of(session: AsyncSession, event: EventEnvelope, *, fallback: Actor) -> Actor:
    """Настоящий инициатор изменения: тот, чьё действие породило событие.

    Нужен и правилам («не трогать то, что только что тронул человек»), и журналу: связка
    «правило X, запущено из-за действия актора Y» собирается из него и системного актора.
    Отключённый или исчезнувший актор подменяется системным — журнал не должен падать
    из-за того, что агента отключили после его действия.
    """
    try:
        return await actors_service.get_actor_by_key(session, event.actor_key)
    except AppError:
        return fallback


async def _scheduled_issues(
    session: AsyncSession,
    rule: AutomationRule,
    definition: RuleDefinition,
    *,
    initiator: Actor,
) -> list[Issue]:
    """Задачи автодействия: сохранённый фильтр правила либо объявленная в коде строка.

    Привязка к очереди добавляется отдельным условием и складывается с отбором по `and`
    — тем же способом, каким доска складывает свой фильтр с условием колонки. Дописывать
    её в строку текстом нельзя: строка правила может быть любой, включая группы с `or`,
    и склейка текстом изменила бы её смысл.

    `me()` в отборе автодействия означает системного актора: расписание никем не
    инициируется, и подставлять сюда некого. Это надо помнить, а не выяснять по пустой
    выдаче, — поэтому сказано и здесь, и в README.
    """
    settings = get_settings()
    scope = (
        []
        if rule.queue is None
        else [search_service.StructuredTerm(name="queue", values=[rule.queue.key])]
    )
    outcome = await search_service.search_issues(
        session,
        initiator=initiator,
        query=None if rule.saved_filter_id is not None else definition.query,
        saved_filter_id=rule.saved_filter_id,
        structured=scope,
        # На одну больше потолка: разница между «ровно потолок» и «потолка не хватило»
        # видна только так, а молчаливое срезание читается как «обработано всё».
        limit=min(settings.automation_batch_size + 1, 200),
    )
    return outcome.page.items


def _reschedule(rule: AutomationRule, moment: datetime, definition: RuleDefinition | None) -> None:
    """Сдвигает расписание от момента запуска, а не от прошлого срока.

    Сдвиг от прошлого срока догонял бы пропущенные тики: планировщик, простоявший час,
    выполнил бы правило с периодом в минуту шестьдесят раз подряд. Автодействие — это
    «раз в столько-то», а не «столько-то раз за период».
    """
    rule.last_run_at = moment
    rule.next_run_at = (
        None if definition is None or definition.schedule is None else moment + definition.schedule
    )


async def _write_run(
    session: AsyncSession,
    *,
    definition: RuleDefinition,
    rule: AutomationRule,
    issue: Issue | None,
    event: EventEnvelope | None,
    initiator: Actor,
    trigger: RunTrigger,
    status: RunStatus,
    reason: str | None,
    actions: list[dict[str, Any]],
    error: str | None,
    depth: int,
    duration_ms: int,
    run_id: uuid.UUID | None = None,
) -> AutomationRun:
    """Пишет строку журнала. Всегда снаружи вложенной транзакции правила.

    `run_id` передаётся тогда, когда правило уже отработало под ним: тот же
    идентификатор лежит в следе автоматики у порождённых событий, и по нему цепочку
    «срабатывание → изменение → событие» можно пройти в обе стороны.
    """
    run = AutomationRun(
        rule_id=rule.id,
        rule_key=definition.key,
        issue_id=None if issue is None else issue.id,
        issue_key=None if issue is None else issue.key,
        event_id=None if event is None else event.id,
        event_type=None if event is None else event.event_type,
        trigger=trigger,
        status=status,
        reason=reason,
        actions=actions,
        error=error,
        initiator_id=initiator.id,
        initiator_key=initiator.key,
        chain_depth=depth,
        duration_ms=duration_ms,
    )
    if run_id is not None:
        run.id = run_id
    return await AutomationRunRepository(session).add(run)


def _short_error(exc: BaseException | None) -> str | None:
    """Тип и текст исключения, обрезанные до потолка колонки."""
    if exc is None:
        return None
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]


def registered_rules() -> Sequence[RuleDefinition]:
    """Объявленные правила. Публичная — через неё их читает сценарий и API."""
    load_rules()
    return rule_registry.all()
