"""Инструмент `close_task`: записи, вердикты и финальная сводка и перевод в `done` одной
транзакцией — единственная дверь в `done`.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.enums import TaskStatusSchema
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import (
    CheckNoArg,
    EntryBodyArg,
    EntryRefsArg,
    EntryTitleArg,
    EntryTypeArg,
    EvidenceArg,
    SummaryBlockersArg,
    SummaryDoneArg,
    SummaryNextStepArg,
    SummaryRemainingArg,
    SummaryUnmeasuredArg,
    VerdictOutcomeArg,
)
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service
from app.services.tasks import TaskClosure


# Поля вложенных моделей объявлены **теми же** аннотациями, что и одиночные аргументы
# подшивающих инструментов: описание у части сводки одно на весь сервер, и второй его
# копии, которая разойдётся с первой, здесь нет.
#
# `unmeasured` обязателен: значение по умолчанию превратило бы «чего не измерили» в
# поле, которое молча опускают ровно в тех делах, где оно и нужно.
class ClosingSummary(BaseModel):
    """Final summary: the four parts of `add_summary` plus `unmeasured`. It takes no
    title: the first line of `done` becomes it.
    """

    model_config = ConfigDict(extra="forbid")

    done: SummaryDoneArg
    remaining: SummaryRemainingArg
    blockers: SummaryBlockersArg
    next_step: SummaryNextStepArg
    unmeasured: SummaryUnmeasuredArg


class ClosingVerdict(BaseModel):
    """Outcome of one review check with its evidence."""

    model_config = ConfigDict(extra="forbid")

    check_no: CheckNoArg
    outcome: VerdictOutcomeArg
    evidence: EvidenceArg = ""


class ClosingEntry(BaseModel):
    """An entry without payload, of the same shape as in `add_entry`."""

    model_config = ConfigDict(extra="forbid")

    type: EntryTypeArg
    title: EntryTitleArg
    body: EntryBodyArg = ""
    refs: EntryRefsArg = None


ClosingSummaryArg = Annotated[
    ClosingSummary,
    Field(
        description=(
            "The summary the task closes with, filed last and reporting the outcome of "
            "the entries and verdicts before it: the first line of `done` states how the "
            "task ended, `remaining` is `nothing` or the key of the task the rest went "
            "to, `next_step` is `no steps` or that key"
        )
    ),
]


ClosingVerdictsArg = Annotated[
    list[ClosingVerdict] | None,
    Field(
        description=(
            "Verdicts filed by this call. The list may be empty: verdicts filed earlier "
            "in the current pass count equally. A refused call files none of them, so a "
            "`failed` verdict sent here leaves no trace in the case, unlike one filed "
            "with `add_verdict`"
        )
    ),
]


ClosingEntriesArg = Annotated[
    list[ClosingEntry] | None,
    Field(
        description=(
            "Entries without payload filed before the verdicts, such as `artifact` pointers "
            "to the result"
        )
    ),
]


# Ответ закрытия: чем стала задача и чем это подшито, без карточки и без записей.
#
# Элемент списка — то же `AppendedEntryView`, каким отвечает подшивающий инструмент,
# поэтому ключ задачи повторяется в каждом: восьмое представление ради двадцати
# сэкономленных байт развело бы две формы одной и той же записи, которые разойдутся
# при первой правке.
#
# Поле, добавленное сюда позже, обязано иметь значение по умолчанию: ответ создающего
# инструмента живёт сутки в ключах идемпотентности, и вчерашнее тело без нового поля
# не поднимется (`docs/notes/mcp.md`, «Сузить форму ответа создающего инструмента
# можно, расширить — нельзя»).
class ClosedTaskView(BaseModel):
    """Closed task: key, new status and version, and every entry the call filed."""

    key: str
    status: TaskStatusSchema
    version: int
    entries: list[AppendedEntryView] = Field(
        default_factory=list,
        description="Filed entries in filing order, ending with `status_changed`",
    )


def closed_task(closure: TaskClosure) -> ClosedTaskView:
    """Ответ закрытия: чем стала задача и чем это подшито, без карточки и без записей.

    Записи идут в порядке подшивки и кончаются `status_changed`: то, что задача закрыта,
    — такая же страница дела, как вердикт, и её номер приезжает тем же списком.
    """
    return ClosedTaskView(
        key=closure.task.key,
        status=closure.task.status,
        version=closure.task.version,
        entries=[appended_entry(item, task_key=closure.task.key) for item in closure.entries],
    )


def register(tools: Toolset) -> None:
    """Объявляет `close_task` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def close_task(
        key: TaskKeyArg,
        summary: ClosingSummaryArg,
        verdicts: ClosingVerdictsArg = None,
        entries: ClosingEntriesArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> ClosedTaskView:
        """Closes a task: files the given entries, then the verdicts, then the final
        summary, and moves the task to `done`, all in one transaction. It is the only
        way into `done`.

        A refusal of any part files nothing and leaves the status as it was. The exit
        conditions are checked after filing: a passing latest verdict on every review
        check within the current pass (`checks_not_passed`), closed children
        (`task_has_unclosed_children`), the task in `in_progress`
        (`transition_not_allowed`). An empty summary part is refused with
        `entry_fields_invalid`.

        For a parent task the final summary covers the whole work: the children's
        results are in their own closing summaries.

        Tasks this one blocked (`blocks`) lose the `blocked` feature, without an entry
        in their cases.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def close() -> ClosedTaskView:
                closure = await tasks_service.close_task(
                    session,
                    task,
                    actor=actor,
                    summary=case_service.SummaryFiling(
                        done=summary.done,
                        remaining=summary.remaining,
                        blockers=summary.blockers,
                        next_step=summary.next_step,
                        unmeasured=summary.unmeasured,
                    ),
                    verdicts=[
                        case_service.VerdictFiling(
                            check_no=item.check_no,
                            outcome=item.outcome,
                            evidence=item.evidence,
                        )
                        for item in verdicts or ()
                    ],
                    entries=[
                        case_service.EntryFiling(
                            type=item.type,
                            title=item.title,
                            body=item.body,
                            refs=item.refs or (),
                        )
                        for item in entries or ()
                    ],
                )
                return closed_task(closure)

            return await Once.of(close_task, session, actor, idempotency_key).run(
                result=ClosedTaskView,
                request={
                    "task": task.key,
                    "summary": summary,
                    "verdicts": verdicts,
                    "entries": entries,
                },
                build=close,
            )
