"""Инструмент `transition`: перевод задачи по зашитой таблице статусов, кроме `done`."""

from typing import Annotated

from pydantic import Field

from app.mcp.arguments import TaskKeyArg
from app.mcp.enums import TaskStatusSchema
from app.mcp.tools.tasks.views import MutationView, mutation
from app.mcp.toolset import FILING, Toolset
from app.services import tasks as tasks_service

ReasonArg = Annotated[
    str | None,
    Field(
        description=(
            "Why the task moves. Required for any step back along `backlog < open < "
            "in_progress < done`, for `cancelled` and for `waiting` "
            "(`transition_reason_required` otherwise), optional elsewhere. For `waiting` "
            "it is the only record of what the task waits for. Filed in the "
            "`status_changed` entry"
        )
    ),
]

TaskStatusArg = Annotated[TaskStatusSchema, Field(description="Target status")]


def register(tools: Toolset) -> None:
    """Объявляет `transition` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING)
    async def transition(
        key: TaskKeyArg,
        to: TaskStatusArg,
        reason: ReasonArg = None,
    ) -> MutationView:
        """Moves a task to another status along the fixed transition table.

        Refusals: leaving `in_progress` without a summary filed since the last entry
        into it — `summary_required`; entering `in_progress` without an assignee —
        `assignee_required`, by anyone but the assignee — `assignee_mismatch` (assignee
        and caller signature in `details`), with an open blocker — `task_blocked`;
        `open` with incomplete sections — `task_sections_incomplete`; `cancelled` with
        open children — `task_has_unclosed_children`; `done` —
        `closing_not_a_transition`, since a task is closed by `close_task`; a move
        outside the table — `transition_not_allowed`, the allowed targets in
        `details.allowed`.

        The tracker never moves a task into or out of `waiting` by itself: both moves
        are the caller's. Each entry into `in_progress`, from any status including
        `waiting`, starts a new pass of the task.

        `cancelled` takes no verdicts. It clears the `blocked` feature of the tasks this
        one blocked (`blocks`), with no entry in their cases.

        The response names the new status and version and the number of the filed
        `status_changed` entry.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            changed = await tasks_service.transition_task(
                session, task, actor=actor, to=to, reason=reason
            )
            return mutation(changed)
