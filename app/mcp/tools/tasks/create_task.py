"""Инструмент `create_task`: задача в `backlog`, по желанию сразу ребёнком родителя."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.domain.links import LinkKind
from app.domain.tasks import DEFAULT_PRIORITY
from app.mcp.arguments import IdempotencyKeyArg, ProjectKeyArg
from app.mcp.enums import TaskPrioritySchema
from app.mcp.idempotency import Once
from app.mcp.tools.tasks.views import MutationView, mutation
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.tasks import TaskMutation

ParentKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Key of the parent task: the new task is born as its child. A closed parent "
            "is refused with `task_closed`. The parent is not closed — neither `done` "
            "nor `cancelled` — while any of its children is open"
        ),
        examples=["TRK-42"],
    ),
]

TaskTitleArg = Annotated[str, Field(description="Task title, one line")]


TaskDescriptionArg = Annotated[
    str,
    Field(
        description=(
            "What happened and why it is a task. For a continuation of a closed task it "
            "names the task the work grew from; the lineage itself is a `relates` link"
        )
    ),
]

AssigneeArg = Annotated[
    str | None,
    Field(
        description=(
            "Participant name or temporary agent label. The tracker never sets or clears "
            "it by itself; only a caller whose signature matches it moves the task into "
            "`in_progress`"
        )
    ),
]

PriorityArg = Annotated[TaskPrioritySchema, Field(description="Task priority")]


class TaskSections(BaseModel):
    """The five task sections; they are editable only while the task is in `backlog`."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(default="", description="Why the task exists and what will change")
    context: str = Field(default="", description="What already exists and what the work relies on")
    constraints: str = Field(
        default="", description="What is out of scope and what stays unchanged"
    )
    output: str = Field(default="", description="What exists once the task is done")
    checks: list[str] = Field(
        default_factory=list,
        description=(
            "Review checks in order, numbered from 1; each names what is run and the "
            "expected result"
        ),
    )


SectionsArg = Annotated[
    TaskSections | None,
    Field(
        description=(
            "The five sections. The task moves from `backlog` to `open` only with four "
            "non-empty text sections and at least one check (`task_sections_incomplete` "
            "otherwise); until then they can be completed with `update_task`"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `create_task` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def create_task(
        project: ProjectKeyArg,
        title: TaskTitleArg,
        description: TaskDescriptionArg,
        sections: SectionsArg = None,
        parent: ParentKeyArg = None,
        assignee: AssigneeArg = None,
        priority: PriorityArg = DEFAULT_PRIORITY,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> MutationView:
        """Creates a task in `backlog`; a new task starts in no other status.

        With `parent`, the task is born as the parent's child in the same call: the link
        files `link_added` both in the new task's case and in the parent's case, and
        `parent_entry` in the response is the number of the parent's entry.

        A child task takes a part of the parent's work when the parent's output falls
        into separate results, its checks cannot all pass in one pass, the work does not
        fit one pass, or it depends on something that does not exist yet. These signs
        appear on entry into the parent and after each attempt.

        The response carries the key issued by the tracker. An empty title or
        description is refused with `task_fields_invalid`.
        """
        async with runtime.call() as (session, actor):
            # Всё, что может отказать, — до занятия ключа: отклонённый вызов не должен
            # тратить ключ. Ключи уезжают в отпечаток разрешёнными (`TRK`, а не `trk`):
            # адресация мягкая, и иначе повтор тем же ключом ответил бы конфликтом.
            resolved_project = await projects_service.get_project(session, project)
            parent_task = None if parent is None else await tasks_service.get_task(session, parent)
            parts = sections or TaskSections()

            async def create() -> MutationView:
                task = await tasks_service.create_task(
                    session,
                    actor=actor,
                    project=resolved_project,
                    title=title,
                    description=description,
                    goal=parts.goal,
                    context=parts.context,
                    constraints=parts.constraints,
                    output=parts.output,
                    checks=parts.checks,
                    assignee=assignee,
                    priority=priority,
                )
                parent_entry: int | None = None
                if parent_task is not None:
                    await links_service.add_link(
                        session, task, parent_task, actor=actor, kind=LinkKind.CHILD
                    )
                    # Номер записи в деле родителя читается из дела, тем же приёмом,
                    # что и у ребёнка ниже: общая блокировка изменений (`app/db/locks.py`,
                    # `lock_changes`) держит транзакцию монопольно до конца вызова, и
                    # никто другой не мог подшить запись в дело родителя между `add_link`
                    # и этим чтением — последняя запись его описи и есть только что
                    # поставленный `link_added`.
                    parent_index = await case_service.case_index(session, parent_task, actor=actor)
                    parent_entry = parent_index[-1].no
                # Номера подшитого читаются из дела, а не собираются по дороге:
                # `create_task` отдаёт задачу, `add_link` — связь, и номерами не
                # заведует ни один из них. У новой задачи в деле одна-две строки, и
                # прочитать их дешевле, чем протаскивать номера через две подписи
                # сценариев ради одного вызова MCP. Заодно ответ называет **всё**, что
                # подшилось, — включая `link_added` у ребёнка.
                filed = await case_service.case_index(session, task, actor=actor)
                return mutation(
                    TaskMutation(task=task, entries=tuple(item.no for item in filed)),
                    parent_entry=parent_entry,
                )

            return await Once.of(create_task, session, actor, idempotency_key).run(
                result=MutationView,
                request={
                    "project": resolved_project.key,
                    "title": title,
                    "description": description,
                    "sections": parts,
                    "parent": None if parent_task is None else parent_task.key,
                    "assignee": assignee,
                    "priority": priority,
                },
                build=create,
            )
