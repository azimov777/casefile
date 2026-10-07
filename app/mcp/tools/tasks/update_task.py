"""Инструмент `update_task`: частичная правка задачи.

## Частичное изменение — вложенная модель

У инструмента нет способа отличить пропущенный аргумент от `null`, если у параметра есть
значение по умолчанию (`docs/notes/mcp.md`). Поэтому изменения задачи приезжают объектом
`changes`, поля которого объявлены через `unset_field`, а `model_dump(exclude_unset=True)`
отдаёт ровно переданные ключи. Без этого правка тегов каждый раз снимала бы исполнителя,
а снять его было бы нечем.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.sentinels import unset_field
from app.domain.tasks import FIRST_CHECK_NUMBER, MAX_CHECK_LENGTH, CheckEdit
from app.mcp.arguments import TaskKeyArg
from app.mcp.enums import TaskPrioritySchema
from app.mcp.tools.tasks.arguments import AREA_RULE, DECISIONS_RULE, NOT_BEFORE_RULE
from app.mcp.tools.tasks.views import MutationView, mutation
from app.mcp.toolset import IDEMPOTENT_TASK_UPDATE, Toolset
from app.services import tasks as tasks_service

VersionArg = Annotated[
    int | None,
    Field(
        description=(
            "Task version read earlier. When given and the task has changed since, the "
            "call is refused with `version_conflict` instead of overwriting the other "
            "change; when left out, the edit applies on top of the current version"
        )
    ),
]


class CheckEditArg(BaseModel):
    """Rewrite of one check: its number and new text."""

    model_config = ConfigDict(extra="forbid")

    no: int = Field(
        ge=FIRST_CHECK_NUMBER,
        description="Number of the check in the current list, from 1",
    )
    text: str = Field(
        min_length=1,
        max_length=MAX_CHECK_LENGTH,
        description="New wording of this check",
    )


# `null` осмыслен только у `assignee`, `area` и `not_before`: он снимает значение. У
# остальных полей `null` смысла не имеет, и схема его не пропустит. Статуса здесь нет — он меняется
# `transition`; ключа нет — он меняется только переносом (`move_task`).
class TaskChanges(BaseModel):
    """Fields to change; a field left out stays as it is. Title, description, sections
    and checks are editable only in `backlog`; elsewhere they are refused with
    `task_field_locked`. Checks of a task that has ever entered `in_progress` are not
    editable at all: `task_checks_frozen`.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(description="Task title")
    description: str = unset_field(description="Task description")
    goal: str = unset_field(description="Section `goal`")
    context: str = unset_field(description="Section `context`")
    constraints: str = unset_field(description="Section `constraints`")
    output: str = unset_field(description="Section `output`")
    checks: list[str] = unset_field(
        description=(
            "All review checks as a list: changes their composition — a check added, "
            "removed or moved. Refused with `task_checks_frozen` once the task has "
            "entered `in_progress`"
        )
    )
    check: CheckEditArg = unset_field(
        description=(
            "Rewrites one check in place; the other checks stay byte for byte, and the "
            "`section_changed` entry names the check number. Refused together with "
            "`checks` (`task_fields_invalid`); refused with `task_checks_frozen` once the "
            "task has entered `in_progress`"
        )
    )
    assignee: str | None = unset_field(
        description=(
            "Participant name or temporary agent label; `null` clears it. The name is "
            "compared with the caller's signature regardless of case, and every session "
            "signed with that name counts as the assignee. Replacing another "
            "participant's name takes the task over from them: the tracker accepts it, "
            "files `assignee_changed` and informs no one"
        )
    )
    priority: TaskPrioritySchema = unset_field(description="Task priority")
    area: str | None = unset_field(
        description=(
            f"{AREA_RULE}; the area can be changed but not taken off: `null` is refused with "
            "`area_required`"
        ),
    )
    not_before: str | None = unset_field(
        description=(
            f"{NOT_BEFORE_RULE}. Editable in any status but `done` and `cancelled`; on a "
            "task in `in_progress` it holds from the next entry. `null` clears it, and "
            "every change files `field_changed`"
        ),
    )
    decisions: list[str] = unset_field(
        description=(
            "The whole new list, editable in any status but `done` and `cancelled`. "
            + DECISIONS_RULE
            + ". A reference already in the field stays there after its decision is "
            "superseded"
        ),
        examples=[["TRK#15"]],
    )


def register(tools: Toolset) -> None:
    """Объявляет `update_task`."""
    runtime = tools.runtime

    @tools.tool(title="Update task", annotations=IDEMPOTENT_TASK_UPDATE)
    async def update_task(
        key: TaskKeyArg,
        changes: TaskChanges,
        version: VersionArg = None,
    ) -> MutationView:
        """Changes the given fields of a task; fields left out stay as they are.

        Title, description and sections are fixed from `open` on. A task past `backlog`
        has them edited by a return to `backlog` through `transition` with a reason,
        this call, and a move forward again to `open` and `in_progress`. Checks are
        the exception: once a task has entered `in_progress`, they are not edited at
        all (`task_checks_frozen`); a check that cannot be run is closed with the
        outcome `unverifiable`, not rewritten.

        Each changed field files `section_changed` or `field_changed`, an assignee
        change files `assignee_changed`. An edit of one check names its number, and the
        earlier verdicts on that check become `outdated`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            given = changes.model_dump(exclude_unset=True)
            if "check" in given:
                # Аргумент приезжает словарём, а сценарий ждёт значение домена: перевод
                # стоит здесь, где кончается транспорт.
                given["check"] = CheckEdit(**given["check"])
            changed = await tasks_service.update_task(
                session,
                task,
                actor=actor,
                changes=tasks_service.TaskChanges(**given),
                expected_version=version,
            )
            return mutation(changed)
