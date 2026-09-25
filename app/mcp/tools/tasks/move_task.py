"""Инструмент `move_task`: перенос задачи или списка задач в другой проект, только набором `main`.

Список ключей — TRK-309 (решение владельца TRK-309#2): каждая задача переносится сама по
себе, ответ — итог по каждому элементу списка. Форма ответа выбирается формой аргумента
`key`: строка отвечает прежним ответом одиночного переноса поле в поле, список (даже из
одного ключа) — `results`. Одна модель с необязательными полями, а не объединение двух:
SDK заворачивает объединение в `{"result": ...}` (`func_metadata._create_output_model`),
и одиночный ответ сменил бы форму у всех прежних вызовов.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from app.domain.tasks import MAX_MOVE_KEYS
from app.domain.tokens import TokenScope
from app.mcp.toolset import FILING, Toolset
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.tasks import (
    TaskAlreadyThere,
    TaskMove,
    TaskMoved,
    TaskMoveOutcome,
    TaskMoveRefused,
)

MoveKeyArg = Annotated[
    str | list[str],
    Field(
        description=(
            "Task key `PROJECT-N`, case-insensitive, or a list of 1 to "
            f"{MAX_MOVE_KEYS} keys; a previous key of a moved task addresses it as well. "
            "A list outside that range is refused with `task_move_batch_size_invalid` "
            "before any move"
        ),
        examples=["TRK-42", ["TRK-42", "TRK-43"]],
    ),
]

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


class MovedView(BaseModel):
    """The task moved."""

    key: str = Field(description="The key as listed")
    outcome: Literal["moved"]
    from_key: str = Field(description="Key the task left")
    to_key: str = Field(description="Key the task got in the new project")
    no: int = Field(description="Number of the `moved` entry in the task's case")


class AlreadyView(BaseModel):
    """The task already was in the project: `task_already_in_project`, nothing filed."""

    key: str = Field(description="The key as listed")
    outcome: Literal["already"]
    to_key: str = Field(description="Key the task holds in that project")


class RefusedView(BaseModel):
    """The task was not moved: the refusal of this task alone."""

    key: str = Field(description="The key as listed")
    outcome: Literal["error"]
    code: str = Field(description="Error code, as a single move would answer it")
    message: str
    details: dict[str, Any]


MoveResultView = Annotated[MovedView | AlreadyView | RefusedView, Field(discriminator="outcome")]


# Ответ переноса — по тому же правилу, что `MutationView`: что стало и где это в деле.
# Поля одиночной формы и `results` необязательны, и сериализатор отдаёт только заданные:
# одиночный ответ обязан остаться прежним поле в поле, а `null` вместо «поля нет»
# сменил бы его. Схему это не портит — приём и довод те же, что у `FoundTaskView`
# (`search_tasks.py`).
class MoveView(BaseModel):
    """A key as a string: the task after the move, by the entry that records it; the
    card in full is returned by `get_task`. A list of keys: `results` alone.
    """

    key: str | None = Field(default=None, description="Key the task got in the new project")
    previous_keys: list[str] | None = Field(
        default=None, description="Keys the task had before, in the order they were left"
    )
    version: int | None = Field(default=None, description="Task version after the move")
    no: int | None = Field(
        default=None, description="Number of the `moved` entry in the task's case"
    )
    results: list[MoveResultView] | None = Field(
        default=None, description="One outcome per listed key, in list order"
    )

    @model_serializer(mode="wrap")
    def _only_what_was_set(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Оставляет в ответе только заданные поля: форма ответа — по форме `key`."""
        return {
            name: value for name, value in handler(self).items() if name in self.model_fields_set
        }


def move(value: TaskMove) -> MoveView:
    """Ответ `move_task` по одному ключу: новый ключ, прежние ключи, версия и номер `moved`."""
    return MoveView(
        key=value.task.key,
        previous_keys=list(value.task.previous_keys),
        version=value.task.version,
        no=value.entry.no,
    )


def move_result(value: TaskMoveOutcome) -> MovedView | AlreadyView | RefusedView:
    """Итог пакетного переноса по одному ключу списка."""
    match value:
        case TaskMoved():
            return MovedView(
                key=value.key,
                outcome="moved",
                from_key=value.from_key,
                to_key=value.to_key,
                no=value.no,
            )
        case TaskAlreadyThere():
            return AlreadyView(key=value.key, outcome="already", to_key=value.to_key)
        case TaskMoveRefused():
            return RefusedView(
                key=value.key,
                outcome="error",
                code=value.refusal.code,
                message=value.refusal.message,
                details=value.refusal.details,
            )


def register(tools: Toolset) -> None:
    """Объявляет `move_task` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN)
    async def move_task(key: MoveKeyArg, project: ProjectArg, reason: MoveReasonArg) -> MoveView:
        """Moves a task to another project, recording the move, both keys and the reason
        as a `moved` entry of the task. Available to a `main` token alone.

        The task gets the next number of the new project, or its own earlier key there
        when it returns to a project it has been in: a task holds at most one key per
        project. The key it leaves goes to `previous_keys` and keeps addressing the task
        in every call that takes a key; no other task ever gets it. Status, sections,
        links, parent, children and case stay as they are, and a closed task moves too.
        One key moves one task: its children stay in their project.

        Moving into or out of a frozen project fails with `project_archived`.

        A list of keys moves each task on its own, in list order, so new numbers follow
        that order; each moved task gets its own `moved` entry with the one reason. The
        answer is `results`, one per listed key, repeats included: `moved`, `already`
        (the task is in that project already) or `error` with the code a single move
        would give, such as `task_not_found` or `project_archived` of the task's own
        project. A refusal of one task leaves the others moved. A missing `main` scope,
        a blank reason, an unknown or archived target project and a list size out of
        range refuse the whole call before any move.
        """
        async with runtime.call() as (session, actor):
            if not isinstance(key, str):
                outcomes = await tasks_service.move_tasks(
                    session, key, actor=actor, project_key=project, reason=reason
                )
                return MoveView(results=[move_result(item) for item in outcomes])
            task = await tasks_service.get_task(session, key)
            target = await projects_service.get_project(session, project)
            moved = await tasks_service.move_task(
                session, task, actor=actor, project=target, reason=reason
            )
            return move(moved)
