"""Формы ответа, общие для инструментов задач: карточка, признаки, короткий ответ изменения.

Карточку и признаки отдают `get_task` и `search_tasks`, короткий ответ `MutationView` —
`create_task`, `update_task` и `transition`. Почему ответ изменения короче карточки — в
шапке `app/mcp/views.py`.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.domain.tasks import TaskFeatures
from app.mcp.enums import TaskPrioritySchema, TaskStatusSchema
from app.mcp.views import AuthorView, ProjectRefView, author
from app.services.tasks import TaskMutation


# Проект в карточке задачи — тот же набор полей, что у `TaskProjectRead` в REST.
class TaskProjectView(ProjectRefView):
    """Project of the task: key, title, its short description and archive time."""

    description: str = Field(
        description=(
            f'Short "what this is" of the project, up to {MAX_PROJECT_DESCRIPTION_LENGTH} '
            "characters; may be empty. Attributes and the project's case are returned by "
            "`get_project`"
        )
    )
    archived_at: datetime | None = Field(
        description="When the project was archived; `null` while it is active"
    )


def task_project(project: Project) -> TaskProjectView:
    """Проект в карточке задачи: строка проекта, описание и архив (`CONCEPT.md`, 4.2).

    Описание короткое и признак архива едут здесь ровно затем, чтобы агент получал
    контекст проекта и знал о заморозке тем же `get_task`, без `get_project` (TRK-167).
    Выдача поиска ни того, ни другого не несёт — там проект строкой (`project_ref`).
    """
    return TaskProjectView(
        key=project.key,
        title=project.title,
        description=project.description,
        archived_at=project.archived_at,
    )


# Карточка задачи — тот же набор полей, что у `TaskRead` в REST.
class TaskView(BaseModel):
    """Task card."""

    id: str
    key: str = Field(
        description=(
            "Current key; changes only when the task moves to another project with `move_task`"
        )
    )
    previous_keys: list[str] = Field(
        description=(
            "Keys the task had before moves, in the order they were left; empty for a task "
            "never moved. Each one is accepted wherever a task key is"
        )
    )
    project: TaskProjectView
    title: str
    description: str
    goal: str
    context: str
    constraints: str
    output: str
    checks: list[str]
    status: TaskStatusSchema
    assignee: str | None
    priority: TaskPrioritySchema
    version: int
    created_by: AuthorView
    created_at: datetime
    updated_at: datetime


def task(item: Task) -> TaskView:
    """Карточка задачи — тот же набор полей, что у `TaskRead` в REST."""
    return TaskView(
        id=str(item.id),
        key=item.key,
        previous_keys=list(item.previous_keys),
        project=task_project(item.project),
        title=item.title,
        description=item.description,
        goal=item.goal,
        context=item.context,
        constraints=item.constraints,
        output=item.output,
        checks=list(item.checks),
        status=item.status,
        assignee=item.assignee,
        priority=item.priority,
        version=item.version,
        created_by=author(item.created_by),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class MutationView(BaseModel):
    """Task state after the call and the entries it filed; the card in full is returned
    by `get_task`.
    """

    key: str
    status: TaskStatusSchema
    version: int = Field(description="Task version after the call")
    entries: list[int] = Field(
        description=(
            "Numbers of the entries filed in this task's case, in filing order. Empty when "
            "the sent values were already in place; the version then stays the same"
        )
    )
    parent_entry: int | None = Field(
        default=None,
        description=(
            "Number of the `link_added` entry filed into the parent task's own case "
            "when `create_task` was given `parent`. `null` when no `parent` was given, "
            "and always `null` for `transition` and `update_task`: they touch no other "
            "task's case."
        ),
    )


def mutation(value: TaskMutation, *, parent_entry: int | None = None) -> MutationView:
    """Ответ изменяющего инструмента: что стало и чем это подшито, без карточки.

    Почему не карточка — в шапке `app/mcp/views.py`. Здесь важно, что `entries` бывает пустым, и
    это законный ответ: клиент прислал то, что уже стоит, — версия не выросла, дело не
    пополнилось. Отличать «применилось» от «уже так было» агент будет именно по нему,
    поэтому отдельного поля `changed` рядом нет: два способа узнать один факт разошлись
    бы при первой же правке.

    `parent_entry` называет номер записи в **чужом** деле — родителя, которого дал
    `create_task`; `entries`, наоборот, всегда о деле **своей** задачи, и смешивать два
    дела в одном списке значило бы отдать номер без адреса, к какому делу он относится.
    У `transition` и `update_task` параметр не передаётся и остаётся `null`: они не
    трогают чужих дел вовсе.
    """
    return MutationView(
        key=value.task.key,
        status=value.task.status,
        version=value.task.version,
        entries=list(value.entries),
        parent_entry=parent_entry,
    )


# Вычисляемые признаки задачи (`CONCEPT.md`, 4.3).
class FeaturesView(BaseModel):
    """Computed task features."""

    blocked: bool
    open_questions: int
    open_blocking_questions: int
    open_remarks: int
    last_summary_at: datetime | None
    last_entry_at: datetime | None


def features(value: TaskFeatures) -> FeaturesView:
    """Вычисляемые признаки задачи (`CONCEPT.md`, 4.3)."""
    return FeaturesView(
        blocked=value.blocked,
        open_questions=value.open_questions,
        open_blocking_questions=value.open_blocking_questions,
        open_remarks=value.open_remarks,
        last_summary_at=value.last_summary_at,
        last_entry_at=value.last_entry_at,
    )
