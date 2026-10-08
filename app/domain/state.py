"""Блок `state`: краткая сводка состояния задачи, которую никто не пишет (TRK-579).

Агент, вернувшийся к задаче, спрашивает «что с ней сейчас», и ответ рассыпан по пяти
местам пакета: причина ожидания лежит только в записи о переходе, свежий ответ — строкой
описи после сводки, блокеры — в связях. Блок собирает их вместе **при каждом чтении**
(TRK#154): ничего не хранится, устареть нечему, модель данных и записи дела
не меняются — тот же способ, что у вычисляемых признаков (4.3).

Чистые функции от уже прочитанного: ни запросов, ни времени «сейчас». Слабое место
блока — слабость входов: он так же информативен, как причина перехода, `next_step` и
заголовки записей, которые агенты уже пишут.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.authors import Author
from app.domain.case import (
    AGENT_ENTRY_TYPES,
    TITLE_CUT_TRAILING,
    TITLE_ELLIPSIS,
    EntryHeading,
    EntryType,
    SectionChangedFacts,
    open_warning,
)
from app.domain.tasks import CLOSED_STATUSES, TaskStatus

#: Причина последнего перехода, `next_step` и `blockers` последней сводки, заголовок записи.
REASON_LIMIT = 160
#: `unmeasured` закрывающей сводки: оно длиннее прочих частей и нужнее читающему закрытое.
UNMEASURED_LIMIT = 200
#: Заголовок записи в строке или в списке вопросов и замечаний.
TITLE_LIMIT = 100
#: Сколько записей после последней сводки показывает блок; остальные — счётчиком `total`.
RECENT_LIMIT = 4


def clip(text: str, limit: int) -> str:
    """Обрезает текст по границе слова с многоточием; в пределах потолка отдаёт как есть.

    Обрезка видна в самом тексте: блок — сводка для чтения, а не значение для сравнения,
    и полный текст всегда лежит в записи, на которую указывает номер.
    """
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    head = flat[: limit - len(TITLE_ELLIPSIS)]
    boundary = head.rfind(" ")
    if boundary > 0:
        head = head[:boundary].rstrip(TITLE_CUT_TRAILING)
    return head + TITLE_ELLIPSIS


def _stamp(moment: datetime) -> str:
    """Момент до минуты в UTC: `2026-10-06T11:59Z` — секунды читающему состояние не нужны."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _signature(author: Author) -> str:
    return author.signature or author.kind.value


# --- Входы: то, что сценарий уже прочитал ---------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusChange:
    """Последняя запись `status_changed`: откуда, куда, кто, когда и почему."""

    no: int
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    author: Author
    created_at: datetime
    reason: str | None


@dataclass(frozen=True, slots=True)
class SummaryParts:
    """Последняя сводка: её номер, время и части, нужные блоку."""

    no: int
    created_at: datetime
    next_step: str
    blockers: str
    unmeasured: str | None


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    """Вопрос без ответа: номер, адресаты, признак `blocking`, заголовок и обсуждение.

    `discussion` — адрес обсуждения, в чьём деле вопрос (`TRK~7`), и тогда `no` — номер
    в его деле; `None` — прежний вопрос дела самой задачи.
    """

    no: int
    addressees: Sequence[str]
    blocking: bool
    title: str
    discussion: str | None = None


@dataclass(frozen=True, slots=True)
class OpenRemark:
    """Замечание без резолюции: номер, автор и заголовок."""

    no: int
    author: Author
    title: str


@dataclass(frozen=True, slots=True)
class ChildStatus:
    """Ребёнок задачи: ключ и статус."""

    key: str
    status: TaskStatus


# --- Выход ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateTransition:
    """Последний переход статуса с причиной, обрезанной до `REASON_LIMIT`."""

    no: int
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    at: str
    by: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class StateSummary:
    """Части последней сводки, обрезанные до `REASON_LIMIT` (`unmeasured` — до 200)."""

    no: int
    at: str
    next_step: str
    blockers: str
    unmeasured: str | None


@dataclass(frozen=True, slots=True)
class StateQuestion:
    no: int
    to: list[str]
    blocking: bool
    title: str
    discussion: str | None


@dataclass(frozen=True, slots=True)
class StateNote:
    """Замечание или предупреждение: номер записи, автор и заголовок."""

    no: int
    by: str
    title: str


@dataclass(frozen=True, slots=True)
class TaskState:
    """Блок `state`: состояние задачи на момент чтения, собранное из дела и связей."""

    status: TaskStatus
    last_transition: StateTransition | None
    last_summary: StateSummary | None
    #: Номер сводки, после которой считаны записи, или `None`, если сводки нет.
    after_summary: int | None
    #: До `RECENT_LIMIT` самых поздних записей агентов и человека после сводки (без сводки —
    #: в деле) строками `#no тип автор время: заголовок` по возрастанию номера.
    recent: list[str]
    #: Сколько таких записей всего: строки показывают только хвост.
    recent_total: int
    questions: list[StateQuestion]
    remarks: list[StateNote]
    warning: StateNote | None
    blockers: list[str]
    #: Дети по статусам: `{"done": 2, "open": 1}`; без детей — пусто.
    children: dict[str, int]
    #: Ключи детей не в `done` и не в `cancelled`.
    children_unclosed: list[str]
    decisions_after_card: list[int]
    #: Итоги и записи человека в обсуждениях задачи после последней правки разделов —
    #: ссылками `TRK~7#5` (решение `TRK#51`, п. 5): работу задают и они.
    discussions_after_card: list[str]
    #: Действующие решения проекта задачи, подшитые после последней правки разделов, —
    #: ссылками `TRK#7` по возрастанию номера (TRK#154): работу задают все они.
    project_decisions_after_card: list[str]


def status_change(
    *,
    no: int,
    author: Author,
    created_at: datetime,
    payload: Mapping[str, Any],
) -> StatusChange:
    """Запись о переходе из нагрузки: статусы и причина (пустая причина — `None`)."""
    reason = payload.get("reason")
    return StatusChange(
        no=no,
        from_status=_status(payload.get("from")),
        to_status=_status(payload.get("to")),
        author=author,
        created_at=created_at,
        reason=reason if isinstance(reason, str) and reason.strip() else None,
    )


def _status(value: Any) -> TaskStatus | None:
    try:
        return TaskStatus(value)
    except ValueError:
        return None


def _line(heading: EntryHeading) -> str:
    return (
        f"#{heading.no} {heading.type.value} {_signature(heading.author)} "
        f"{_stamp(heading.created_at)}: {clip(heading.title, TITLE_LIMIT)}"
    )


def _recent(index: Sequence[EntryHeading], summary_no: int | None) -> tuple[list[str], int]:
    """Записи агента и человека после сводки, а без сводки — все: хвост строками и счёт."""
    entries = [
        heading
        for heading in index
        if heading.type in AGENT_ENTRY_TYPES and (summary_no is None or heading.no > summary_no)
    ]
    return [_line(heading) for heading in entries[-RECENT_LIMIT:]], len(entries)


def decisions_after_card(index: Sequence[EntryHeading]) -> list[int]:
    """Номера `decision` после последней правки раздела или заведения задачи.

    Карточка замораживается с `open`, а решения копятся в деле: решение, подшитое после
    последней правки разделов, постановка могла не учесть. Суждения «постановка устарела»
    блок не выносит — он называет записи, с которых стоит начать проверять.
    """
    cut = 0
    for heading in index:
        if heading.type is EntryType.CREATED or isinstance(heading.facts, SectionChangedFacts):
            cut = heading.no
    return [
        heading.no for heading in index if heading.type is EntryType.DECISION and heading.no > cut
    ]


def project_decisions_after_card(
    project_key: str,
    decisions: Sequence[tuple[int, int]],
    *,
    cut_seq: int,
    superseded: Collection[int],
) -> list[str]:
    """Ссылки на действующие решения проекта, подшитые позже последней правки разделов.

    `decisions` — пары «номер и `seq`» решений дела проекта, `cut_seq` — `seq` последней
    записи `created` или `section_changed` задачи, `superseded` — номера заменённых
    решений. Заменённые не входят: их место занимает преемник, если он подшит после
    границы. Суждения «постановка устарела» блок не выносит.
    """
    return [
        f"{project_key}#{no}"
        for no, seq in sorted(decisions)
        if seq > cut_seq and no not in superseded
    ]


def build_state(
    *,
    status: TaskStatus,
    index: Sequence[EntryHeading],
    last_change: StatusChange | None,
    summary: SummaryParts | None,
    questions: Sequence[OpenQuestion],
    remarks: Sequence[OpenRemark],
    open_blockers: Sequence[str],
    children: Sequence[ChildStatus],
    discussions_after_card: Sequence[str],
    project_decisions_after_card: Sequence[str],
) -> TaskState:
    """Собирает блок `state` из уже прочитанного: опись, последний переход, сводка,
    вопросы (дела задачи и её обсуждений), замечания, блокеры, дети и записи обсуждений
    после правки разделов.
    """
    counts: dict[str, int] = {}
    for child in children:
        counts[child.status.value] = counts.get(child.status.value, 0) + 1
    warning = open_warning(index)
    recent, recent_total = _recent(index, None if summary is None else summary.no)
    return TaskState(
        status=status,
        last_transition=None
        if last_change is None
        else StateTransition(
            no=last_change.no,
            from_status=last_change.from_status,
            to_status=last_change.to_status,
            at=_stamp(last_change.created_at),
            by=_signature(last_change.author),
            reason=None if last_change.reason is None else clip(last_change.reason, REASON_LIMIT),
        ),
        last_summary=None
        if summary is None
        else StateSummary(
            no=summary.no,
            at=_stamp(summary.created_at),
            next_step=clip(summary.next_step, REASON_LIMIT),
            blockers=clip(summary.blockers, REASON_LIMIT),
            unmeasured=None
            if summary.unmeasured is None
            else clip(summary.unmeasured, UNMEASURED_LIMIT),
        ),
        after_summary=None if summary is None else summary.no,
        recent=recent,
        recent_total=recent_total,
        questions=[
            StateQuestion(
                no=question.no,
                to=list(question.addressees),
                blocking=question.blocking,
                title=clip(question.title, TITLE_LIMIT),
                discussion=question.discussion,
            )
            for question in questions
        ],
        remarks=[
            StateNote(
                no=remark.no, by=_signature(remark.author), title=clip(remark.title, TITLE_LIMIT)
            )
            for remark in remarks
        ],
        warning=None
        if warning is None
        else StateNote(
            no=warning.no, by=_signature(warning.author), title=clip(warning.title, TITLE_LIMIT)
        ),
        blockers=list(open_blockers),
        children=counts,
        children_unclosed=[child.key for child in children if child.status not in CLOSED_STATUSES],
        decisions_after_card=decisions_after_card(index),
        discussions_after_card=list(discussions_after_card),
        project_decisions_after_card=list(project_decisions_after_card),
    )
