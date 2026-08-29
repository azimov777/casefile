"""Инструменты настройки процесса: очередь, справочники, воркфлоу, поля.

Отдельная группа, потому что агент должен уметь не только работать внутри готового
процесса, но и собрать его. Здесь же живут два правила, которых нет у рабочего цикла.

## Процесс создаётся целиком одним вызовом

`create_workflow` принимает граф: статусы, переходы и назначение на типы задач. Собирать
то же самое пятнадцатью последовательными вызовами агент будет долго и с ошибкой в
середине, после которой очередь останется в нерабочем состоянии. Граф проверяется
целиком — достижимость статусов, путь в `done`, отсутствие тупиков, совместимость с уже
заведёнными задачами, — и либо сохраняется, либо не сохраняется весь.

## У опасных инструментов есть предварительная проверка

Изменение процесса задевает **все** задачи очереди, а интерфейса агент не видит и о
последствиях узнаёт только из текста ответа. Поэтому `create_workflow` и
`update_workflow_transition` принимают `dry_run`: операция выполняется по-настоящему,
отчёт о последствиях собирается, и транзакция откатывается. Второй, «облегчённой»
проверки при этом нет и быть не может — она разошлась бы с настоящей ровно в тех
случаях, ради которых её и звали.

`impact` в ответе показывает, сколько живых задач останется без исходящих переходов и в
каких статусах они стоят. Ноль там — не украшение: это единственный способ увидеть, что
процесс не запирает работу.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.sentinels import UNSET, unset_field
from app.db.models.workflow import Workflow
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.fields import FieldOption, FieldValueType
from app.domain.workflows import TransitionDefinition
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import catalogs as catalogs_service
from app.services import fields as fields_service
from app.services import queues as queues_service
from app.services import workflow as workflow_service

DRY_RUN = (
    "Run the change, collect the report and roll it back. Use it before touching a "
    "workflow that already has issues in it: the answer shows exactly what the change "
    "would do, and nothing is written"
)


class TransitionInput(BaseModel):
    """Одно ребро графа процесса."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="What the button says: `Start`, `Close`")
    to_status: str = Field(description="Status reference the transition leads to")
    from_status: str | None = Field(
        default=None,
        description="Status reference it starts from; null means «from any status»",
    )
    required_fields: list[str] = Field(
        default_factory=list,
        description=(
            "System field names or custom field references that must be filled in the "
            "target state, for example `assignee` or `TRK.severity`"
        ),
    )
    requires_resolution: bool = Field(
        default=False,
        description="Must be true for a transition into a status of category `done`",
    )

    def definition(self) -> TransitionDefinition:
        return TransitionDefinition(
            name=self.name,
            source_status=self.from_status,
            target_status=self.to_status,
            required_fields=tuple(self.required_fields),
            requires_resolution=self.requires_resolution,
        )


class QueueChangesInput(BaseModel):
    """Правка очереди: применяются только переданные поля.

    Ключа здесь нет и не будет: на нём построены ключи задач, и переименование сломало
    бы каждую внешнюю ссылку молча.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(description="Display name")
    description: str = unset_field(description="What the queue is for")
    default_issue_type: str = unset_field(
        description="Issue type reference used when a new issue does not name one"
    )
    default_status: str = unset_field(
        description=(
            "Status a new issue starts in. It must be part of the workflow of every "
            "allowed issue type and cannot be in category `done`"
        )
    )


class FieldOptionInput(BaseModel):
    """Вариант перечисления: машинный ключ и отображаемое название."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stored value, latin lowercase: `critical`")
    name: str = Field(description="Display name")


class FieldChangesInput(BaseModel):
    """Правка описания поля: применяются только переданные поля."""

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(description="Display name")
    is_required: bool = unset_field(description="An issue cannot be saved without it")
    is_hidden: bool = unset_field(
        description=(
            "Hiding is the only way to retire a field that already has values: the "
            "data and the history stay, new values are refused"
        )
    )
    options: list[FieldOptionInput] = unset_field(
        description="Replaces the whole option set of an enum field"
    )
    default_value: JsonValue = unset_field(description="Applied when the issue carries no value")
    issue_types: list[str] = unset_field(
        description="Issue type references the field applies to; an empty list means every type"
    )


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты настройки процесса."""

    @server.tool()
    async def create_queue(
        key: Annotated[
            str,
            Field(
                description=(
                    "Latin uppercase key, immutable: issue keys are built from it "
                    "(`TRK` gives `TRK-1`)"
                )
            ),
        ],
        name: Annotated[str, Field(description="Display name")],
        description: Annotated[str, Field(description="What the queue is for")] = "",
        issue_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Issue type references allowed in the queue; defaults to the global "
                    "set. A queue always gets a working workflow for them"
                )
            ),
        ] = None,
        default_issue_type: Annotated[
            str | None, Field(description="Issue type used when a new issue does not name one")
        ] = None,
        default_status: Annotated[
            str | None,
            Field(description="Status a new issue starts in; it cannot be in category `done`"),
        ] = None,
    ) -> dict[str, Any]:
        """Create a queue with a working configuration. Mutating.

        A queue owns its process, so it comes out ready to use: allowed issue types, a
        default status and a default workflow are set up in the same call. Refine them
        afterwards with `create_status` and `create_workflow`.
        """
        async with runtime.call() as (session, actor):
            created = await queues_service.create_queue(
                session,
                initiator=actor,
                key=key,
                name=name,
                description=description,
                issue_type_refs=issue_types,
                default_issue_type_ref=default_issue_type,
                default_status_ref=default_status,
            )
            config = await queues_service.get_queue_config(session, created, initiator=actor)
            return views.queue_config(config)

    @server.tool()
    async def update_queue(
        queue: Annotated[str, Field(description="Queue key; the key itself never changes")],
        changes: QueueChangesInput,
    ) -> dict[str, Any]:
        """Change the settings of a queue. Mutating.

        The defaults are what a new issue gets when it names neither a type nor a
        status, and they are also what binds the queue to its process: a workflow can
        only be assigned to an issue type when the queue default status is part of that
        graph. Building a process with your own statuses therefore goes in this order —
        create the statuses, point the queue default at one of them, then create the
        workflow.
        """
        given = changes.model_dump(exclude_unset=True)
        async with runtime.call() as (session, actor):
            target = await refs.queue(session, queue)
            updated = await queues_service.update_queue(
                session,
                target,
                initiator=actor,
                name=given.get("name"),
                description=given.get("description"),
                default_issue_type_ref=given.get("default_issue_type"),
                default_status_ref=given.get("default_status"),
            )
            return views.queue(updated)

    @server.tool()
    async def set_queue_issue_types(
        queue: Annotated[str, Field(description="Queue key")],
        issue_types: Annotated[
            list[str],
            Field(
                min_length=1,
                description=(
                    "The complete set of issue type references allowed in the queue; "
                    "it replaces the current one"
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Set which issue types the queue accepts. Mutating.

        The whole set at once, not one addition at a time: the result then does not
        depend on the order of calls. A freshly created issue type is useless until it
        is listed here — it can neither be assigned a workflow nor carry an issue.

        A type that issues already use cannot be dropped from the set.
        """
        async with runtime.call() as (session, actor):
            target = await refs.queue(session, queue)
            allowed = await queues_service.set_issue_types(
                session, target, initiator=actor, refs=issue_types
            )
            return {
                "queue": target.key,
                "issue_types": [views.catalog_entry(entry) for entry in allowed],
            }

    @server.tool()
    async def create_status(
        key: Annotated[str, Field(description="Latin lowercase key, immutable: `in_review`")],
        name: Annotated[str, Field(description="Display name, shown to people")],
        category: Annotated[
            StatusCategory,
            Field(
                description=(
                    "Machine meaning: `new`, `in_progress` or `done`. Boards, project "
                    "progress and automation rely on it, so a status can be renamed "
                    "without breaking anything"
                )
            ),
        ],
        queue: Annotated[
            str | None,
            Field(
                description=(
                    "Queue key for a queue-local status (addressed as `TRK.in_review`); "
                    "omit to create a global one available to every queue"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Create a status. Mutating.

        A new status is not part of any workflow yet: add it to a graph with
        `create_workflow`, otherwise no issue can ever reach it.
        """
        async with runtime.call() as (session, actor):
            entry = await catalogs_service.create_entry(
                session,
                CatalogKind.STATUS,
                initiator=actor,
                key=key,
                name=name,
                queue=await refs.scope(session, queue),
                category=category,
            )
            return views.catalog_entry(entry)

    @server.tool()
    async def create_issue_type(
        key: Annotated[str, Field(description="Latin lowercase key: `incident`")],
        name: Annotated[str, Field(description="Display name")],
        queue: Annotated[
            str | None, Field(description="Queue key for a local type; omit for a global one")
        ] = None,
    ) -> dict[str, Any]:
        """Create an issue type. Mutating.

        A type is allowed in a queue only after it is listed in the queue settings, and
        it needs a workflow assigned to it — do both while creating the workflow.
        """
        async with runtime.call() as (session, actor):
            entry = await catalogs_service.create_entry(
                session,
                CatalogKind.ISSUE_TYPE,
                initiator=actor,
                key=key,
                name=name,
                queue=await refs.scope(session, queue),
            )
            return views.catalog_entry(entry)

    @server.tool()
    async def create_resolution(
        key: Annotated[str, Field(description="Latin lowercase key: `wont_fix`")],
        name: Annotated[str, Field(description="Display name")],
        queue: Annotated[
            str | None, Field(description="Queue key for a local resolution; omit for a global one")
        ] = None,
    ) -> dict[str, Any]:
        """Create a resolution — how an issue ended. Mutating.

        A transition into a status of category `done` requires one, so a process that
        closes issues needs at least one resolution available in its queue.
        """
        async with runtime.call() as (session, actor):
            entry = await catalogs_service.create_entry(
                session,
                CatalogKind.RESOLUTION,
                initiator=actor,
                key=key,
                name=name,
                queue=await refs.scope(session, queue),
            )
            return views.catalog_entry(entry)

    @server.tool()
    async def create_workflow(
        queue: Annotated[str, Field(description="Queue key the workflow belongs to")],
        name: Annotated[str, Field(description="Name of the process, unique within the queue")],
        initial_status: Annotated[
            str, Field(description="Status a new issue of this process starts in")
        ],
        statuses: Annotated[
            list[str],
            Field(min_length=1, description="Every status reference the graph includes"),
        ],
        transitions: Annotated[
            list[TransitionInput], Field(description="Edges between the statuses")
        ],
        issue_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Issue type references to assign this workflow to. Without an "
                    "assignment the graph exists but governs nothing"
                )
            ),
        ] = None,
        dry_run: Annotated[bool, Field(description=DRY_RUN)] = False,
    ) -> dict[str, Any]:
        """Create a whole workflow in one call: statuses, transitions, assignment. Mutating.

        The graph is validated as a whole: every status must be reachable from the
        initial one, every status must have a path into `done`, a transition into
        `done` must require a resolution, and issues that already exist must keep a way
        out of their current status. Nothing is saved unless all of it holds.

        The answer carries `impact` — how many live issues would be left without an
        outgoing transition, and in which statuses. Run with `dry_run: true` first when
        the queue already has issues.
        """
        async with runtime.call() as (session, actor):
            target = await refs.queue(session, queue)
            created = await workflow_service.create_workflow(
                session,
                target,
                initiator=actor,
                name=name,
                initial_status=initial_status,
                statuses=statuses,
                transitions=[item.definition() for item in transitions],
            )
            for ref in issue_types or ():
                await workflow_service.assign_workflow(
                    session,
                    created,
                    await refs.issue_type(session, ref, initiator=actor),
                    initiator=actor,
                )
            return await _report(session, created, dry_run=dry_run)

    @server.tool()
    async def replace_workflow(
        workflow: Annotated[str, Field(description="Workflow id from `get_workflow`")],
        name: Annotated[str, Field(description="Name of the process")],
        initial_status: Annotated[
            str, Field(description="Status a new issue of this process starts in")
        ],
        statuses: Annotated[
            list[str],
            Field(min_length=1, description="Every status reference the new graph includes"),
        ],
        transitions: Annotated[
            list[TransitionInput], Field(description="Edges between the statuses")
        ],
        dry_run: Annotated[bool, Field(description=DRY_RUN)] = False,
    ) -> dict[str, Any]:
        """Replace the whole graph of an existing workflow. Mutating.

        This is how a queue moves onto statuses of its own: the queue created a default
        process, and the new statuses are put into that same graph instead of a second
        one. The change is checked against the live data — a status where issues are
        standing cannot be dropped, and every assigned issue type must keep a way out of
        its current status.

        The queue default status must stay inside the graph, so the usual order is:
        replace the graph while keeping the old default in it, point the queue default
        at a new status with `update_queue`, then replace the graph again without the
        old one.
        """
        async with runtime.call() as (session, actor):
            graph = await workflow_service.get_workflow(
                session, refs.identifier(workflow, "workflow"), initiator=actor
            )
            updated = await workflow_service.replace_workflow_graph(
                session,
                graph,
                initiator=actor,
                name=name,
                initial_status=initial_status,
                statuses=statuses,
                transitions=[item.definition() for item in transitions],
            )
            return await _report(session, updated, dry_run=dry_run)

    @server.tool()
    async def update_workflow_transition(
        workflow: Annotated[str, Field(description="Workflow id from `get_workflow`")],
        transition: Annotated[str, Field(description="Transition id from `get_workflow`")],
        definition: Annotated[
            TransitionInput,
            Field(description="The transition as it should become; it replaces the old one whole"),
        ],
        dry_run: Annotated[bool, Field(description=DRY_RUN)] = False,
    ) -> dict[str, Any]:
        """Replace one transition of a workflow. Mutating.

        The change is checked against the whole graph, not just this edge: removing the
        last path into `done`, or the only way out of a status where issues are
        standing, is refused with the rule that was broken. The answer carries the
        updated graph and its `impact`.
        """
        async with runtime.call() as (session, actor):
            graph = await workflow_service.get_workflow(
                session, refs.identifier(workflow, "workflow"), initiator=actor
            )
            await workflow_service.update_transition(
                session,
                graph,
                refs.identifier(transition, "transition"),
                initiator=actor,
                definition=definition.definition(),
            )
            return await _report(session, graph, dry_run=dry_run)

    @server.tool()
    async def get_workflow(
        queue: Annotated[
            str | None, Field(description="Queue key: every workflow of this queue")
        ] = None,
        workflow: Annotated[str | None, Field(description="Workflow id: just this one")] = None,
        issue: Annotated[
            str | None,
            Field(description="Issue key: the workflow that governs this issue right now"),
        ] = None,
    ) -> dict[str, Any]:
        """Read workflow graphs: statuses, transitions, assignments and live impact.

        Address them one of three ways — by queue, by workflow id, or by an issue whose
        process you want to see. This is what to read before changing a process, and
        the transition ids from here are what `update_workflow_transition` takes.
        """
        async with runtime.call() as (session, actor):
            if workflow is not None:
                graph = await workflow_service.get_workflow(
                    session, refs.identifier(workflow, "workflow"), initiator=actor
                )
                views_list = [await workflow_service.view_workflow(session, graph)]
            elif issue is not None:
                entry = await refs.issue(session, issue)
                graph = await workflow_service.workflow_for_issue_type(
                    session,
                    queue_id=entry.queue_id,
                    issue_type_id=entry.issue_type_id,
                )
                views_list = [await workflow_service.view_workflow(session, graph)]
            elif queue is not None:
                views_list = await workflow_service.list_queue_workflows(
                    session, await refs.queue(session, queue), initiator=actor
                )
            else:
                raise _needs_target()
            return {"workflows": [views.workflow(item) for item in views_list]}

    @server.tool()
    async def create_field(
        key: Annotated[str, Field(description="Latin lowercase key, immutable: `severity`")],
        name: Annotated[str, Field(description="Display name")],
        value_type: Annotated[
            FieldValueType,
            Field(
                description=(
                    "What the field holds: string, text, number, date, datetime, "
                    "boolean, enum (one of `options`), actor (an actor key) or issue "
                    "(an issue key)"
                )
            ),
        ],
        queue: Annotated[
            str | None,
            Field(
                description=(
                    "Queue key for a queue-local field, addressed and stored as "
                    "`TRK.severity`; omit for a global one addressed as `severity`"
                )
            ),
        ] = None,
        is_multiple: Annotated[
            bool, Field(description="A multiple field stores an array of values")
        ] = False,
        is_required: Annotated[
            bool, Field(description="An issue cannot be created or saved without it")
        ] = False,
        options: Annotated[
            list[FieldOptionInput] | None,
            Field(description="Allowed values of an enum field, in display order"),
        ] = None,
        default_value: Annotated[
            JsonValue, Field(description="Applied when the issue carries no value")
        ] = None,
        issue_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Issue type references the field applies to; omit to apply it to every type"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Create a custom field. Mutating.

        Adding an attribute needs no migration — that is the point of the registry. The
        value is stored under the field reference in `issue.values`, so a global
        `severity` and a queue-local `TRK.severity` are two different fields and never
        overwrite each other.
        """
        async with runtime.call() as (session, actor):
            created = await fields_service.create_field(
                session,
                initiator=actor,
                key=key,
                name=name,
                value_type=value_type,
                queue=await refs.scope(session, queue),
                is_multiple=is_multiple,
                is_required=is_required,
                options=[FieldOption(key=item.key, name=item.name) for item in options or ()],
                default_value=default_value,
                issue_types=[
                    await refs.issue_type(session, ref, initiator=actor)
                    for ref in issue_types or ()
                ]
                or None,
            )
            return views.field(created)

    @server.tool()
    async def update_field(
        field: Annotated[str, Field(description="Field reference: `severity`, `TRK.severity`")],
        changes: FieldChangesInput,
    ) -> dict[str, Any]:
        """Change the description of a custom field. Mutating.

        The key and the value type of a field that already has values are immutable:
        changing them would silently reinterpret data that is already written. Removing
        an option that issues still use is refused for the same reason; hiding the
        field is the way to retire it.
        """
        given = changes.model_dump(exclude_unset=True)
        async with runtime.call() as (session, actor):
            entry = await refs.field(session, field, initiator=actor)
            updated = await fields_service.update_field(
                session,
                entry,
                initiator=actor,
                name=given.get("name"),
                is_required=given.get("is_required"),
                is_hidden=given.get("is_hidden"),
                options=(
                    [FieldOption(key=item["key"], name=item["name"]) for item in given["options"]]
                    if "options" in given
                    else None
                ),
                default_value=given.get("default_value", UNSET),
                issue_types=(
                    [
                        await refs.issue_type(session, ref, initiator=actor)
                        for ref in given["issue_types"]
                    ]
                    if "issue_types" in given
                    else None
                ),
            )
            return views.field(updated)


async def _report(session: AsyncSession, workflow: Workflow, *, dry_run: bool) -> dict[str, Any]:
    """Отчёт о процессе, при `dry_run` — с откатом изменений.

    Отчёт собирается **до** отката: после него объекты принадлежат уже отменённой
    транзакции, и обращение к их связям означало бы новый поход в базу за состоянием,
    которого нет. Откат делает предварительную проверку тем же кодом, что и настоящую
    операцию, — второй, «облегчённой» проверки в проекте нет намеренно: она разошлась бы
    с настоящей ровно там, где её и звали.
    """
    view = await workflow_service.view_workflow(session, workflow)
    payload = views.workflow(view) | {"applied": not dry_run}
    if dry_run:
        await session.rollback()
    return payload


def _needs_target() -> ValidationError:
    """Ни одного способа адресовать процесс: это ошибка вызова, а не пустая выдача."""
    return ValidationError(
        message="One of queue, workflow or issue must be given",
        details={"parameters": ["queue", "workflow", "issue"]},
    )
