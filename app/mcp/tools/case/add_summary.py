"""Инструмент `add_summary`: промежуточная сводка — справка при передаче дела."""

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import (
    SummaryBlockersArg,
    SummaryDoneArg,
    SummaryNextStepArg,
    SummaryRemainingArg,
)
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет `add_summary` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def add_summary(
        key: TaskKeyArg,
        done: SummaryDoneArg,
        remaining: SummaryRemainingArg,
        blockers: SummaryBlockersArg,
        next_step: SummaryNextStepArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedEntryView:
        """Files a summary: the handover note of a case, in four parts, none of them empty
        (`entry_fields_invalid` lists the empty ones).

        A summary follows each significant step: a decision made, a finished part of the
        work, a failure that changes the plan, any point where a colleague would need an
        explanation of where the work stands.

        Its index title is the first line of `done`, returned in the response. The final
        summary, with `unmeasured`, is filed by `close_task`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> AppendedEntryView:
                entry = await case_service.add_summary(
                    session,
                    task,
                    actor=actor,
                    done=done,
                    remaining=remaining,
                    blockers=blockers,
                    next_step=next_step,
                )
                return appended_entry(entry, task_key=task.key)

            return await Once.of(add_summary, session, actor, idempotency_key).run(
                result=AppendedEntryView,
                request={
                    "task": task.key,
                    "done": done,
                    "remaining": remaining,
                    "blockers": blockers,
                    "next_step": next_step,
                },
                build=append,
            )
