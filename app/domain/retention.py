"""Срок хранения растущих журналов: политика прохода, отчёт и согласование с окном SSE.

Три таблицы пишутся на каждое событие установки и не чистятся сами: очередь событий
(`outbox_events`), журнал срабатываний автоматики (`automation_runs`) и журнал доставок
вебхуков (`webhook_deliveries`). У последней скорость роста ещё и умножается на число
подписок — одно событие кладёт строку на каждый адрес.

## Почему решение одно на три таблицы, а не три независимых

Срок хранения `outbox_events` — это не только объём базы. Это глубина ленты
`GET /api/v1/events` и, главное, окно переподключения живого потока: клиент присылает
`Last-Event-ID`, и поток продолжается с названного события. Удалённое чисткой событие
даёт `invalid_stream_cursor` с `reason: unknown_event` — то есть отказ, положенный
клиенту, отставшему на тысячи событий, получает клиент, отставший на десять. Назначить
этой таблице срок отдельно значит молча сузить обещание, данное настройкой
`TRACKER_STREAM_REPLAY_LIMIT`.

## Почему согласованность нельзя проверить по конфигурации

`stream_replay_limit` меряется **в событиях**, срок хранения — **в днях**. Статически
они несопоставимы: пятьсот событий — это час на живом контуре и месяц на тихом.
Поэтому проверка идёт по данным (`StreamWindowCheck`), а не по паре чисел в `.env`, и
делается в момент чистки, когда данные под рукой.

## Пол окна важнее самой проверки

Проверка сообщает о несогласованности, но не защищает от неё. Защищает **пол**: чистка
не трогает `stream_replay_limit + 1` самых свежих событий, каким бы старым ни был этот
хвост. Единица сверх лимита не описка — клиент проходит, пока `behind <= limit`, а у
`(limit + 1)`-го с конца события `behind` равен ровно лимиту.

Пол считается по всей очереди, без учёта отбора по типам событий. Поток, суженный
`event_types`, считает своё отставание только по своим типам, поэтому его окно в
абсолютных событиях шире и полом не покрывается. Обещание поэтому формулируется
абсолютно: `TRACKER_STREAM_REPLAY_LIMIT` событий **всей** очереди.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

#: Настройка, которой задаётся окно переподключения. Имя нужно в тексте отчёта: тот,
#: кто читает предупреждение, должен видеть, что именно править, а не идти искать.
STREAM_REPLAY_SETTING = "TRACKER_STREAM_REPLAY_LIMIT"


class RetentionTarget(StrEnum):
    """Что чистится за один проход.

    Журнал автоматики разделён на две цели, а не на два фильтра одной: у срабатываний
    правила, которого больше нет в коде, свой — более короткий — срок, и в отчёте это
    обязано быть видно отдельной строкой. Таблица у них при этом одна, см. `table`.
    """

    OUTBOX_EVENTS = "outbox_events"
    AUTOMATION_RUNS = "automation_runs"
    ORPHAN_AUTOMATION_RUNS = "orphan_automation_runs"
    WEBHOOK_DELIVERIES = "webhook_deliveries"

    @property
    def table(self) -> str:
        """Таблица, к которой относится цель. У двух целей она общая."""
        if self is RetentionTarget.ORPHAN_AUTOMATION_RUNS:
            return RetentionTarget.AUTOMATION_RUNS.value
        return self.value


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Сроки хранения и границы одного прохода.

    Пачка и потолок числа пачек — часть контракта команды, а не внутренняя деталь. Один
    `DELETE` на миллион строк держит блокировку всё время выполнения и разом раздувает
    WAL; пачка ограничивает и то и другое, а потолок не даёт одному проходу молотить
    базу часами. Упёршийся в потолок проход об этом сообщает — работа не потеряна, её
    доделает следующий запуск.
    """

    outbox_days: int
    automation_runs_days: int
    orphan_runs_days: int
    webhook_deliveries_days: int
    batch_size: int
    max_batches: int

    def __post_init__(self) -> None:
        """Отвергает бессмысленный набор вместо того, чтобы удалить лишнее.

        Проверка здесь, а не только в настройках: те же значения приходят флагами
        команды, и вторая проверка рядом с флагами разошлась бы с первой.
        """
        for name, value in (
            ("outbox_days", self.outbox_days),
            ("automation_runs_days", self.automation_runs_days),
            ("orphan_runs_days", self.orphan_runs_days),
            ("webhook_deliveries_days", self.webhook_deliveries_days),
            ("batch_size", self.batch_size),
            ("max_batches", self.max_batches),
        ):
            if value < 1:
                raise ValueError(f"Retention {name} must be at least 1, got {value}")

    def days(self, target: RetentionTarget) -> int:
        """Срок хранения этой цели в днях."""
        match target:
            case RetentionTarget.OUTBOX_EVENTS:
                return self.outbox_days
            case RetentionTarget.AUTOMATION_RUNS:
                return self.automation_runs_days
            case RetentionTarget.ORPHAN_AUTOMATION_RUNS:
                return self.orphan_runs_days
            case RetentionTarget.WEBHOOK_DELIVERIES:
                return self.webhook_deliveries_days

    def cutoff(self, target: RetentionTarget, *, now: datetime) -> datetime:
        """Граница: строки строго старше неё подлежат удалению."""
        return now - timedelta(days=self.days(target))

    @property
    def max_rows(self) -> int:
        """Потолок удаляемого за один проход по одной цели."""
        return self.batch_size * self.max_batches


@dataclass(frozen=True, slots=True)
class TargetOutcome:
    """Что случилось с одной целью за проход."""

    target: RetentionTarget
    cutoff: datetime
    deleted: int
    batches: int
    #: Проход упёрся в потолок: подходящие строки остались, их доберёт следующий запуск.
    capped: bool = False
    #: Строки, которые срок хранения удалил бы, но их держит окно переподключения SSE.
    #: Ненулевое значение бывает только у очереди событий и означает несогласованность.
    protected: int = 0
    #: Почему цель пропущена целиком. `None` — цель обработана.
    skipped: str | None = None

    def line(self) -> str:
        """Строка отчёта команды."""
        if self.skipped is not None:
            return f"{self.target.value}: skipped ({self.skipped})"
        parts = [f"{self.target.value}: {self.deleted} rows"]
        parts.append(f"older than {self.cutoff.isoformat(timespec='seconds')}")
        if self.batches:
            parts.append(f"in {self.batches} batch" + ("" if self.batches == 1 else "es"))
        if self.protected:
            parts.append(f"{self.protected} kept by the SSE window")
        if self.capped:
            parts.append("pass limit reached, run again")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class StreamWindowCheck:
    """Согласован ли срок хранения очереди событий с окном переподключения SSE.

    Согласовано — когда окно целиком помещается внутрь срока хранения, то есть срок
    ничего не хотел удалить из того, что окно обязано держать. Как только чистка
    упирается в пол окна, обещание и настройка разошлись: окно на этой установке
    уходит глубже, чем срок хранения, и держится оно полом, а не сроком.
    """

    replay_limit: int
    retention_days: int
    cutoff: datetime
    #: Возраст самого старого события, которое обязано пережить чистку. `None` — событий
    #: в очереди меньше, чем обещает окно, и удалять из неё нельзя ничего.
    oldest_replayable_at: datetime | None
    #: Сколько обработанных событий старше срока держит окно.
    protected: int

    @property
    def is_consistent(self) -> bool:
        return self.protected == 0

    def message(self) -> str:
        """Однострочное объяснение: что разошлось и что с этим делать."""
        if self.is_consistent:
            return (
                f"SSE reconnect window ({self.replay_limit} events) fits inside the "
                f"{self.retention_days}-day retention of outbox_events"
            )
        return (
            f"SSE reconnect window ({self.replay_limit} events, {STREAM_REPLAY_SETTING}) "
            f"reaches further back than the {self.retention_days}-day retention of "
            f"outbox_events: {self.protected} events are kept only because of it. "
            f"Raise TRACKER_RETENTION_OUTBOX_DAYS or lower {STREAM_REPLAY_SETTING}"
        )


@dataclass(frozen=True, slots=True)
class RetentionReport:
    """Итог прохода: печатается командой и уходит в лог планировщика."""

    outcomes: tuple[TargetOutcome, ...]
    stream_window: StreamWindowCheck
    started_at: datetime
    dry_run: bool = False

    @property
    def deleted(self) -> int:
        return sum(item.deleted for item in self.outcomes)

    @property
    def capped(self) -> bool:
        """Хотя бы одна цель упёрлась в потолок прохода."""
        return any(item.capped for item in self.outcomes)

    def outcome(self, target: RetentionTarget) -> TargetOutcome | None:
        """Итог по одной цели. Нужен тестам и вызывающему коду, читающему одну строку."""
        return next((item for item in self.outcomes if item.target is target), None)

    def lines(self) -> list[str]:
        """Отчёт построчно. Первая строка отвечает, удалялось ли вообще что-нибудь."""
        head = "dry run, nothing deleted" if self.dry_run else "cleanup"
        lines = [f"{head}: {self.deleted} rows total"]
        lines.extend(item.line() for item in self.outcomes)
        lines.append(f"stream window: {self.stream_window.message()}")
        if self.capped:
            lines.append("pass limit reached on some targets: run the command again")
        return lines


def utcnow() -> datetime:
    """Текущее время в UTC. Отдельной функцией — чтобы тест мог передать своё."""
    return datetime.now(UTC)
