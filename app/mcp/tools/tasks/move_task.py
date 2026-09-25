"""Инструмент `move_task`: перенос задачи в другой проект с причиной, только набором `main`."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.domain.tokens import TokenScope
from app.mcp.arguments import TaskKeyArg
from app.mcp.toolset import FILING, Toolset
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.tasks import TaskMove

ProjectArg = Annotated[
    str,
    Field(
        description=(
            "Key of the project the task moves to, case-insensitive. An unknown key is "
            "refused with `project_not_found`, the project the task is already in with "
            "`task_already_in_project`"
        ),
        examples=["TRK"],
    ),
]

MoveReasonArg = Annotated[
    str,
    Field(
        description=(
            "Why the task moves; a blank one is refused with `task_move_reason_required`. "
            "Filed in the `moved` entry of the task's case"
        )
    ),
]


# Ответ переноса — по тому же правилу, что `MutationView`: что стало и где это в деле.
class MoveView(BaseModel):
    """Task after the move, by the entry that records it; the card in full is returned by
    `get_task`.
    """

    key: str = Field(description="Key the task got in the new project")
    previous_keys: list[str] = Field(
        description="Keys the task had before, in the order they were left"
    )
    version: int = Field(description="Task version after the move")
    no: int = Field(description="Number of the `moved` entry in the task's case")


def move(value: TaskMove) -> MoveView:
    """Ответ `move_task`: новый ключ, прежние ключи, версия и номер записи `moved`."""
    return MoveView(
        key=value.task.key,
        previous_keys=list(value.task.previous_keys),
        version=value.task.version,
        no=value.entry.no,
    )


def register(tools: Toolset) -> None:
    """Объявляет `move_task` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN)
    async def move_task(key: TaskKeyArg, project: ProjectArg, reason: MoveReasonArg) -> MoveView:
        """Moves a task to another project, recording the move, both keys and the reason
        as a `moved` entry of the task. Available to a `main` token alone.

        The task gets the next number of the new project, or its own earlier key there
        when it returns to a project it has been in: a task holds at most one key per
        project. The key it leaves goes to `previous_keys` and keeps addressing the task
        in every call that takes a key; no other task ever gets it. Status, sections,
        links, parent, children and case stay as they are, and a closed task moves too.
        One call moves one task: its children stay in their project.

        Moving into or out of a frozen project fails with `project_archived`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            target = await projects_service.get_project(session, project)
            moved = await tasks_service.move_task(
                session, task, actor=actor, project=target, reason=reason
            )
            return move(moved)
