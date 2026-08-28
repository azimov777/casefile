"""Формы правил автоматики, происхождение срабатывания и след автоматики в событии.

Чистый Python: ни ORM, ни HTTP, ни Pydantic. Здесь лежит то, что обязано одинаково
пониматься движком, журналом срабатываний, шиной событий и HTTP-слоем.

## Почему след автоматики живёт в полезной нагрузке события

Правило меняет задачу → рождается событие → срабатывает правило. Разорвать эту цепочку
можно только тем, что доедет от изменения до следующего события, а между ними стоит
outbox: подписчик получает `EventEnvelope`, а не стек вызовов. Поэтому «это изменение
сделано автоматикой», номер срабатывания и глубина цепочки едут в `payload`
(`app/services/events.py` их туда кладёт), а не в отдельной таблице и не в переменной
процесса: воркер — другой процесс и другая транзакция.

Отсутствие ключа `automation` в нагрузке — это не «неизвестно», а «изменение сделал
человек или агент». Глубина такой цепочки — ноль.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from app.domain.errors import InvalidAutomationRuleError

#: Ключ правила: та же латиница в нижнем регистре, что у ключей полей и статусов.
#: Ключ — часть контракта: по нему адресуется маршрут API и по нему же в базе лежит
#: состояние правила, поэтому переименование правила равносильно заведению нового.
RULE_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
_RULE_KEY_RE = re.compile(RULE_KEY_PATTERN)

MAX_RULE_NAME_LENGTH = 255

#: Ключ, под которым след автоматики лежит в полезной нагрузке события.
AUTOMATION_PAYLOAD_KEY = "automation"

#: Минимальный период автодействия. Не «сколько выдержит база», а защита от опечатки:
#: `timedelta(seconds=1)` в объявлении правила означает автодействие, которое
#: перебирает весь фильтр каждую секунду, и заметят это по нагрузке, а не по логу.
MIN_SCHEDULE = timedelta(seconds=30)


class RuleKind(StrEnum):
    """Форма правила: чем оно запускается.

    Форма определяет не только источник запуска, но и набор осмысленных объявлений:
    у триггера обязаны быть типы событий, у автодействия — расписание, у макроса —
    ни того, ни другого. Проверка стоит в `validate_declaration`.
    """

    #: Реагирует на событие из шины.
    TRIGGER = "trigger"
    #: Работает по расписанию, отбирает задачи фильтром.
    SCHEDULED = "scheduled"
    #: Запускается вручную человеком или агентом для конкретной задачи.
    MACRO = "macro"


class RunTrigger(StrEnum):
    """Что запустило срабатывание. Совпадает по смыслу с формой правила, но не с ней самой.

    Разные перечисления намеренно: форма — свойство правила и меняется только правкой
    кода, а происхождение — свойство одного срабатывания. Их совпадение сегодня не
    повод склеивать: запуск макроса из другого правила или ручной прогон автодействия
    добавятся сюда, не трогая формы.
    """

    EVENT = "event"
    SCHEDULE = "schedule"
    MANUAL = "manual"


class RunStatus(StrEnum):
    """Чем кончилось срабатывание.

    `SKIPPED` — правило рассмотрело задачу и ничего не сделало: не подошло условие или
    остановила защита от цикла. Это полноценный результат, а не отсутствие результата:
    вопрос «почему правило не сработало» задают чаще, чем «что оно сделало», и ответ на
    него обязан лежать в журнале, а не выводиться из его пустоты.
    """

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class SkipReason(StrEnum):
    """Почему срабатывание не состоялось. Список закрытый: по нему строят отбор в журнале.

    Причины делятся на две группы, и различать их важно. `CONDITION_NOT_MET` и
    `NOTHING_TO_DO` — нормальная работа: правило посмотрело и решило, что делать нечего.
    Остальные — сработавшая защита: они означают, что правило хотело действовать, но
    ему не дали, и частота таких записей в журнале — сигнал о разладившемся контуре.
    """

    #: Правило само решило, что условие не выполнено.
    CONDITION_NOT_MET = "condition_not_met"
    #: Правило отработало, но ни одного действия не потребовалось.
    NOTHING_TO_DO = "nothing_to_do"
    #: Событие вызвано этим же правилом: реакция на себя — самый короткий цикл.
    SELF_TRIGGERED = "self_triggered"
    #: Цепочка «правило → событие → правило» стала глубже потолка.
    CHAIN_DEPTH_EXCEEDED = "chain_depth_exceeded"
    #: Правило уже отработало по этой задаче слишком много раз за окно времени.
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class AutomationCause:
    """След автоматики в событии: какое правило, каким срабатыванием и на какой глубине.

    Глубина считается от человека: изменение, сделанное руками, даёт глубину 0, правило,
    сработавшее на него, — 1, правило, сработавшее на изменение первого, — 2. Потолок
    задаётся настройкой, потому что подобрать его можно только на живом наборе правил.
    """

    rule_key: str
    run_id: uuid.UUID
    depth: int

    def to_payload(self) -> dict[str, Any]:
        """Вид для JSONB: идентификатор строкой, как везде в полезной нагрузке."""
        return {"rule": self.rule_key, "run": str(self.run_id), "depth": self.depth}

    @classmethod
    def of(cls, payload: dict[str, Any]) -> AutomationCause | None:
        """След из полезной нагрузки события. `None` — изменение сделал человек или агент.

        Испорченный след (чужой формат, не тот тип) читается как его отсутствие, а не
        роняет обработку: событие с мусором в служебном ключе не должно останавливать
        шину. Цена — правило, которое в этом случае сочтёт цепочку начатой заново;
        от бесконечного цикла при этом остаются лимит срабатываний и потолок попыток
        доставки.
        """
        raw = payload.get(AUTOMATION_PAYLOAD_KEY)
        if not isinstance(raw, dict):
            return None
        rule_key = raw.get("rule")
        depth = raw.get("depth")
        if not isinstance(rule_key, str) or not isinstance(depth, int):
            return None
        try:
            run_id = uuid.UUID(str(raw.get("run")))
        except ValueError, TypeError:
            return None
        return cls(rule_key=rule_key, run_id=run_id, depth=depth)


def depth_of(payload: dict[str, Any]) -> int:
    """Глубина цепочки, на которой родилось событие. У изменения человека — ноль."""
    cause = AutomationCause.of(payload)
    return 0 if cause is None else cause.depth


def validate_rule_key(key: str) -> str:
    """Проверяет ключ правила и возвращает канонический вид."""
    normalized = key.strip().lower()
    if not _RULE_KEY_RE.match(normalized):
        raise InvalidAutomationRuleError(
            details={"key": key, "reason": "pattern_mismatch", "pattern": RULE_KEY_PATTERN},
        )
    return normalized


def validate_declaration(
    *,
    key: str,
    name: str,
    kind: RuleKind,
    events: tuple[str, ...],
    schedule: timedelta | None,
    query: str | None,
) -> None:
    """Проверяет объявление правила: у каждой формы свой обязательный набор.

    Проверка выполняется при импорте модуля правил, то есть при старте процесса, — и
    это осознанно жёсткий момент. Правило, объявленное неверно, обязано уронить старт,
    а не тихо не попасть в реестр: во втором случае оно просто «перестанет работать»,
    и искать причину будут в базе и в логах доставки.
    """
    if not name.strip():
        raise InvalidAutomationRuleError(
            details={"key": key, "field": "name", "reason": "required"},
        )
    if len(name) > MAX_RULE_NAME_LENGTH:
        raise InvalidAutomationRuleError(
            details={
                "key": key,
                "field": "name",
                "reason": "too_long",
                "max": MAX_RULE_NAME_LENGTH,
            },
        )

    if kind is RuleKind.TRIGGER:
        _require(key, events, field="events", kind=kind)
        _forbid(key, schedule, field="schedule", kind=kind)
        _forbid(key, query, field="query", kind=kind)
    elif kind is RuleKind.SCHEDULED:
        _require(key, schedule, field="schedule", kind=kind)
        _require(key, query, field="query", kind=kind)
        _forbid(key, events, field="events", kind=kind)
        if schedule is not None and schedule < MIN_SCHEDULE:
            raise InvalidAutomationRuleError(
                details={
                    "key": key,
                    "field": "schedule",
                    "reason": "too_frequent",
                    "min_seconds": int(MIN_SCHEDULE.total_seconds()),
                },
            )
    else:
        _forbid(key, events, field="events", kind=kind)
        _forbid(key, schedule, field="schedule", kind=kind)
        _forbid(key, query, field="query", kind=kind)


def _require(key: str, value: object, *, field: str, kind: RuleKind) -> None:
    if not value:
        raise InvalidAutomationRuleError(
            details={"key": key, "field": field, "reason": "required_for_kind", "kind": kind.value},
        )


def _forbid(key: str, value: object, *, field: str, kind: RuleKind) -> None:
    if value:
        raise InvalidAutomationRuleError(
            details={
                "key": key,
                "field": field,
                "reason": "not_allowed_for_kind",
                "kind": kind.value,
            },
        )
