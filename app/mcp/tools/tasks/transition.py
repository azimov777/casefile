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
            "in_progress < done` and for `cancelled` (`transition_reason_required` "
            "otherwise), optional elsewhere. Filed in the `status_changed` entry as text "
            "only: a wait is held by its carrier — an open `blocking` question, "
            "`blocked_by` or `not_before` — and not by the reason"
        )
    ),
]

TaskStatusArg = Annotated[TaskStatusSchema, Field(description="Target status")]


def register(tools: Toolset) -> None:
    """Объявляет `transition`."""
    runtime = tools.runtime

    @tools.tool(title="Change task status", annotations=FILING)
    async def transition(
        key: TaskKeyArg,
        to: TaskStatusArg,
        reason: ReasonArg = None,
    ) -> MutationView:
        """Moves a task to another status along the fixed transition table.

        Refusals: leaving `in_progress` without a summary filed since the last entry
        into it — `summary_required`; entering `in_progress` without an assignee —
        `assignee_required`, by anyone but the assignee — `assignee_mismatch` (assignee
        and caller signature in `details`), with an open blocker — `task_blocked`, with
        an unanswered `blocking` question — `task_has_open_blocking_questions` (question
        numbers in `details.questions`), before its `not_before` moment while the
        `deferred` feature is true — `task_deferred` (the moment in `details.not_before`);
        `open` with incomplete sections — `task_sections_incomplete`; `cancelled` with
        open children — `task_has_unclosed_children`; `done` — `closing_not_a_transition`,
        since a task is closed by `close_task`; a move outside the table —
        `transition_not_allowed`, the allowed targets in `details.allowed`.

        A task waiting in `open` stays there when its carrier closes: neither an answer,
        a closed blocker nor an arrived `not_before` moves it, and it becomes a candidate
        again with no `status_changed` entry. Each entry into `in_progress` starts a new
        pass of the task.

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
