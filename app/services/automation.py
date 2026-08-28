"""Сценарии автоматики: реестр правил, их настройка, журнал и ручной запуск.

Правило состоит из двух половин, и путать их нельзя. **Объявление** живёт в коде
(`app/automation/registry.py`) и меняется только выкладкой. **Состояние** живёт в базе и
меняется через API без перезапуска: включено ли, к какой очереди привязано, с какими
параметрами, каким фильтром отбирает задачи. Наружу обе половины отдаются вместе
(`RuleView`) — по отдельности они бесполезны: объявление без состояния не отвечает
«работает ли», состояние без объявления не отвечает «что оно делает».

## Новое правило приезжает выключенным

`sync_rules` заводит строку под каждое новое объявление и никогда не включает её сама.
Правило, приехавшее с выкладкой включённым, начало бы менять задачи в ту же минуту,
когда его ещё никто не настроил и не прочитал, — а «начало менять задачи» здесь означает
не список на экране, а закрытые задачи и разосланные комментарии.

Строку исчезнувшего правила синхронизация **не удаляет**: каскад унёс бы вместе с ней
журнал срабатываний, то есть ровно ту историю, ради которой в журнал и смотрят после
того, как правило убрали.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.automation import engine
from app.automation.registry import RuleDefinition
from app.automation.registry import registry as rule_registry
from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule, AutomationRun
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.models.saved_filter import SavedFilter
from app.db.pagination import Page
from app.db.repositories import AutomationRuleRepository, AutomationRunRepository
from app.domain.automation import RuleKind, RunStatus
from app.domain.errors import (
    AutomationRuleNotFoundError,
    AutomationRuleUnavailableError,
    InvalidAutomationRuleError,
)
from app.services.permissions import ensure_allowed


@dataclass(frozen=True, slots=True)
class RuleView:
    """Правило целиком: состояние из базы и объявление из кода.

    `definition is None` означает правило, удалённое из репозитория: строка осталась,
    выполнять нечего. Это состояние обязано быть видимым, а не молча превращаться в
    «выключено»: правило продолжает значиться включённым, и вопрос «почему оно не
    срабатывает» иначе останется без ответа.
    """

    rule: AutomationRule
    definition: RuleDefinition | None

    @property
    def key(self) -> str:
        return self.rule.rule_key

    @property
    def is_available(self) -> bool:
        return self.definition is not None


# --- Синхронизация ------------------------------------------------------------------


async def sync_rules(session: AsyncSession) -> list[str]:
    """Заводит строки состояния под новые объявления. Возвращает ключи заведённых.

    Идемпотентна и переживает одновременный старт: её зовут три процесса — API в
    lifespan, воркер и планировщик первым шагом цикла, — и на пустой базе они делают это
    одновременно. Строки заводятся одной атомарной вставкой (`insert_missing`), поэтому
    гонка не даёт ни конфликта целостности, ни второй строки под тот же ключ.

    Возвращаются ключи, заведённые **этим** вызовом: проигравший гонку получает пустой
    список. Вызывающий пишет его в лог, и список того, что вызов пытался завести, вводил
    бы в заблуждение ровно при том старте, ради которого лог и читают.
    """
    return await AutomationRuleRepository(session).insert_missing(
        {definition.key: definition.default_params() for definition in engine.registered_rules()}
    )


# --- Чтение -------------------------------------------------------------------------


async def get_rule(session: AsyncSession, rule_key: str) -> AutomationRule:
    """Строка состояния правила или `automation_rule_not_found`.

    Прав не проверяет: точка входа интерфейса — `read_rule`, а движок зовёт репозиторий
    напрямую, потому что права там уже проверены на уровне запустившего сценария.
    """
    rule = await AutomationRuleRepository(session).get_by_key(rule_key)
    if rule is None:
        raise AutomationRuleNotFoundError(details={"rule": rule_key})
    return rule


async def read_rule(session: AsyncSession, rule_key: str, *, initiator: Actor) -> RuleView:
    ensure_allowed(initiator, "automation.read")
    rule = await get_rule(session, rule_key)
    return _view(rule)


async def list_rules(
    session: AsyncSession,
    *,
    initiator: Actor,
    queue: Queue | None = None,
    is_enabled: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[RuleView]:
    """Страница правил. Объявление подтягивается к каждой строке из реестра кода."""
    ensure_allowed(initiator, "automation.list")
    page = await AutomationRuleRepository(session).list_page(
        queue_id=None if queue is None else queue.id,
        is_enabled=is_enabled,
        limit=limit,
        cursor=cursor,
    )
    return Page(
        items=[_view(rule) for rule in page.items],
        next_cursor=page.next_cursor,
    )


async def list_runs(
    session: AsyncSession,
    *,
    initiator: Actor,
    rule: AutomationRule | None = None,
    issue: Issue | None = None,
    status: RunStatus | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[AutomationRun]:
    """Журнал срабатываний страницами, от старого к новому.

    Отбор по правилу, по задаче и по результату: это три вопроса, с которыми в журнал и
    приходят — «что делало это правило», «что делали с этой задачей» и «где сломалось».
    """
    ensure_allowed(initiator, "automation.runs")
    return await AutomationRunRepository(session).list_page(
        rule_id=None if rule is None else rule.id,
        issue_id=None if issue is None else issue.id,
        status=status,
        limit=limit,
        cursor=cursor,
    )


# --- Изменение ----------------------------------------------------------------------


async def update_rule(
    session: AsyncSession,
    rule: AutomationRule,
    *,
    initiator: Actor,
    is_enabled: bool = UNSET,
    queue: Queue | None = UNSET,
    params: Mapping[str, Any] = UNSET,
    saved_filter: SavedFilter | None = UNSET,
) -> RuleView:
    """Меняет состояние правила. Не переданное поле не трогается.

    Параметры проверяются схемой самого правила прямо здесь, а не при запуске:
    включённое правило с мусорными параметрами падало бы в фоне, и заметили бы это по
    несделанной работе, а не по ошибке.

    Правило без объявления настраивать нельзя вовсе: проверить параметры нечем, а
    сохранить непроверенные значило бы завести ту самую строку, ради которой проверка и
    стоит.
    """
    ensure_allowed(initiator, "automation.update", target=rule)
    definition = rule_registry.get(rule.rule_key)
    if definition is None:
        raise AutomationRuleUnavailableError(details={"rule": rule.rule_key})

    if is_set(params):
        # Параметры заменяются целиком, а не сливаются с текущими: слияние не давало бы
        # способа снять значение, и «вернуть как было» пришлось бы делать перечислением
        # умолчаний руками.
        rule.params = definition.parse_params(dict(params)).model_dump(mode="json")
    if is_set(queue):
        rule.queue = queue
    if is_set(saved_filter):
        _ensure_filter_applicable(definition, saved_filter)
        rule.saved_filter = saved_filter
    if is_set(is_enabled):
        rule.is_enabled = is_enabled

    _sync_schedule(rule, definition)
    await AutomationRuleRepository(session).flush()
    return _view(rule)


async def run_macro(
    session: AsyncSession,
    rule_key: str,
    *,
    issue: Issue,
    initiator: Actor,
    params: Mapping[str, Any] | None = None,
) -> engine.RunOutcome:
    """Запускает макрос по задаче. Возвращает запись журнала, а не бросает при неудаче.

    Ошибка внутри правила — это результат срабатывания, а не отказ в запросе: она уже
    записана в журнал, и проброс исключения откатил бы транзакцию вместе с этой записью.
    Вызывающий видит `status: failed` и текст причины.
    """
    ensure_allowed(initiator, "automation.run", target=issue)
    return await engine.run_macro(
        session,
        rule_key,
        issue=issue,
        initiator=initiator,
        params=params,
    )


# --- Внутреннее ----------------------------------------------------------------------


def _view(rule: AutomationRule) -> RuleView:
    return RuleView(rule=rule, definition=rule_registry.get(rule.rule_key))


def _ensure_filter_applicable(definition: RuleDefinition, saved_filter: SavedFilter | None) -> None:
    """Сохранённый фильтр осмыслен только у автодействия: остальным нечего отбирать.

    Триггер получает задачу из события, макрос — из вызова. Фильтр у них молча ни на что
    не влиял бы, а настроивший его человек считал бы, что правило ограничено.
    """
    if saved_filter is None or definition.kind is RuleKind.SCHEDULED:
        return
    raise InvalidAutomationRuleError(
        details={
            "rule": definition.key,
            "field": "saved_filter",
            "reason": "not_allowed_for_kind",
            "kind": definition.kind.value,
        },
    )


def _sync_schedule(rule: AutomationRule, definition: RuleDefinition) -> None:
    """Приводит расписание в соответствие с включённостью.

    Включили автодействие — оно должно сработать на ближайшем тике, а не через полный
    период: человек включил его, чтобы оно заработало, и ждать шесть часов ради
    симметрии незачем. Выключили — срок снимается, иначе выборка планировщика продолжала
    бы поднимать эту строку и отбрасывать её.
    """
    if definition.kind is not RuleKind.SCHEDULED:
        rule.next_run_at = None
        return
    if not rule.is_enabled:
        rule.next_run_at = None
    elif rule.next_run_at is None:
        rule.next_run_at = datetime.now(UTC)


def definitions() -> Sequence[RuleDefinition]:
    """Объявленные в коде правила. Нужна HTTP-слою для описания схемы параметров."""
    return engine.registered_rules()


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> AutomationRun | None:
    """Запись журнала по идентификатору. Нужна тестам и отладке."""
    return await session.get(AutomationRun, run_id)
