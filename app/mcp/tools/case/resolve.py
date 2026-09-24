"""Инструмент `resolve`: исход замечания и задача, куда ушла работа."""

from typing import Annotated

from pydantic import Field

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.enums import RemarkOutcomeSchema
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service

RemarkNoArg = Annotated[
    int,
    Field(
        description=(
            "Number of the `remark` entry in the same task; any other number is refused "
            "with `entry_fields_invalid`"
        )
    ),
]

RemarkOutcomeArg = Annotated[
    RemarkOutcomeSchema,
    Field(
        description=(
            "How the remark is resolved, and what the body holds:\n"
            "- `fixed` — corrected at once; the body states what changed;\n"
            "- `accepted` — taken into work as a separate task named in `task`;\n"
            "- `needs_detail` — the remark needs clarification; the body holds the "
            "concrete question;\n"
            "- `declined` — nothing will change; the body gives the reason"
        )
    ),
]

ContinuationKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Key of the task the work went to. Required with `accepted` and refused with "
            "any other outcome, both as `entry_fields_invalid`"
        ),
        examples=["TRK-43"],
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `resolve` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def resolve(
        key: TaskKeyArg,
        remark_no: RemarkNoArg,
        outcome: RemarkOutcomeArg,
        task: ContinuationKeyArg = None,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedEntryView:
        """Resolves a remark on a task: its outcome and where the work went.

        Any outcome resolves the remark, `needs_detail` included: the resolution removes
        it from `open_remarks`, while `accepted` keeps it in `remarks_in_work` until the
        continuation task is closed. Its title is made of the remark reference and the
        outcome.
        """
        async with runtime.call() as (session, actor):
            entry_task = await tasks_service.get_task(session, key)

            async def append() -> AppendedEntryView:
                entry = await case_service.resolve(
                    session,
                    entry_task,
                    actor=actor,
                    remark_no=remark_no,
                    outcome=outcome,
                    continuation=task,
                    body=body,
                )
                return appended_entry(entry, task_key=entry_task.key)

            return await Once.of(resolve, session, actor, idempotency_key).run(
                result=AppendedEntryView,
                request={
                    "task": entry_task.key,
                    "remark_no": remark_no,
                    "outcome": outcome,
                    "continuation": task,
                    "body": body,
                },
                build=append,
            )
