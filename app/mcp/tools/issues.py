"""Инструменты рабочего цикла: найти, прочитать, завести, изменить, перевести.

Всё здесь — тонкий перевод аргументов инструмента в вызов сценария. Своего отбора,
своей проверки полей и своей записи истории тут нет и быть не может: те же сценарии
зовёт REST, и вторая реализация означала бы, что одна и та же операция из двух
интерфейсов ведёт себя по-разному.

## Поиск принимает строку языка, а не набор аргументов под каждое поле

Ради этого язык и делался: одна строка вместо конструктора, и её же можно сохранить
фильтром. Поэтому «задачи проекта» — это `project: alpha` в том же инструменте, а не
отдельный инструмент, и «задачи очереди» — `queue: TRK`. Второй способ отбирать задачи
разошёлся бы с первым на первом же краевом случае.

## Ошибка разбора запроса доносится целиком

`invalid_search_query` несёт позицию символа и причину в подробностях, и инструмент
обязан отдать их агенту как есть: по ним запрос исправляется за одну попытку, а «invalid
query» отправляет в слепой перебор.
"""

from datetime import datetime
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.core.config import get_settings
from app.core.sentinels import UNSET, unset_field
from app.db.pagination import MAX_PAGE_SIZE
from app.domain.issues import IssuePriority
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import comments as comments_service
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import search as search_service
from app.services import workflow as workflow_service
from app.services.catalogs import format_entry_ref

QUERY_LANGUAGE = """Query language: `field: [operator] value[, value]`, combined with \
`and`, `or` and parentheses; `and` binds tighter than `or`. Operators: `=` (default), \
`!=`, `>`, `>=`, `<`, `<=`, `~` (contains), `!~`, `in`, `not in`; several values \
separated by commas mean «any of». Functions: `me()`, `today()`, `now()`, `empty()` \
(no value), with day offsets such as `today() - 7d` (`d`, `w`, `h`, `m`). Fields: \
queue, key, issue_type, status, status_category, resolution, priority, author, \
assignee, followers, tags, project, summary, description, text (summary, description \
or any comment), deadline, created_at, updated_at, and custom fields addressed by \
reference (`severity`, `TRK.severity`). A bare date covers the whole day; a moment \
with time needs quotes: `deadline: >= "2026-08-28T10:00:00+00:00"`. Examples: \
`queue: TRK and status: open and assignee: me()`, \
`project: alpha and status_category: != done`, `tags: release and deadline: <= today()`\
"""

DETAIL_LEVELS = """How much of the issue to return. `brief` — key, summary, status, \
type, priority, assignee, deadline, updated_at. `full` — every field including \
description, tags, followers and custom values. `history` — everything from `full` \
plus the changelog and the discussion. Start with `brief`: a full issue with history \
is kilobytes of text\
"""


class IssueChangesInput(BaseModel):
    """Частичное изменение задачи: применяются только переданные поля.

    `null` осмыслен ровно у трёх полей — `resolution`, `assignee` и `deadline` — и
    означает «очистить». Различать «не передано» и «передано null» обязательно: иначе
    правка названия каждый раз снимала бы исполнителя.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = unset_field(description="Single line shown in lists and notifications")
    description: str = unset_field(description="Pass an empty string to clear it")
    issue_type: str = unset_field(description="Issue type reference: `bug`, `TRK.incident`")
    status: str = unset_field(
        description=(
            "Status reference. Prefer `transition_issue`: a direct write skips the "
            "workflow, and a status outside the assigned graph is rejected anyway"
        )
    )
    resolution: str | None = unset_field(description="Resolution reference, or null to clear it")
    priority: IssuePriority = unset_field()
    assignee: str | None = unset_field(description="Actor key, or null to unassign")
    deadline: datetime | None = unset_field(
        description="ISO 8601 with a UTC offset, or null to drop the deadline"
    )
    project: str | None = unset_field(
        description="Project key, or null to take the issue out of its project"
    )
    tags: list[str] = unset_field(description="Replaces the whole tag set")
    values: dict[str, JsonValue] = unset_field(
        description=(
            "Custom field values keyed by field reference. Partial: null clears a "
            "field, a key that is not sent is left alone"
        )
    )


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты задач."""

    @server.tool()
    async def search_issues(
        query: Annotated[
            str,
            Field(description=f"Query string; empty means every issue. {QUERY_LANGUAGE}"),
        ] = "",
        fields: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Fields to return for each issue. Omit for the brief set "
                    f"({', '.join(views.BRIEF_FIELDS)}); pass `['*']` for whole issues; "
                    "pass a custom field reference to get only that entry of `values`. "
                    "The key is always included"
                )
            ),
        ] = None,
        sort: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Sort keys, most significant first; a leading `-` sorts descending "
                    "(`-deadline`). Sortable: created_at, updated_at, deadline, "
                    "priority, summary and single-valued custom fields"
                )
            ),
        ] = None,
        limit: Annotated[
            int | None,
            Field(ge=1, le=MAX_PAGE_SIZE, description="Page size; defaults to the server setting"),
        ] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """Find issues by a query language string.

        This is the only way to select issues: the list of a project (`project: alpha`),
        of a queue (`queue: TRK`) or of your own work (`assignee: me()`) is this tool
        with a condition, not a separate one.

        Returns a page of issues with `next_cursor` and `has_more`. Returns the brief
        field set unless `fields` says otherwise — a hundred whole issues eat the whole
        context. A malformed query is rejected with the character position and the
        reason in the error details; fix the query by them instead of guessing.
        """
        settings = get_settings()
        selected = _selected_fields(fields)
        async with runtime.call() as (session, actor):
            outcome = await search_service.search_issues(
                session,
                initiator=actor,
                query=query or None,
                sort=sort or (),
                fields=selected,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (
                    views.issue(
                        item,
                        fields=outcome.resolved.fields,
                        value_refs=outcome.resolved.value_refs,
                        text_limit=settings.mcp_text_limit,
                    )
                    for item in outcome.page.items
                ),
                next_cursor=outcome.page.next_cursor,
            )

    @server.tool()
    async def get_issue(
        issue: Annotated[str, Field(description="Issue key, for example `TRK-123`")],
        detail: Annotated[
            str, Field(pattern="^(brief|full|history)$", description=DETAIL_LEVELS)
        ] = "brief",
        limit: Annotated[
            int | None,
            Field(
                ge=1,
                le=MAX_PAGE_SIZE,
                description=(
                    "Size of the changelog and comment pages when `detail` is `history`; "
                    "both come back oldest first with their own `next_cursor`"
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read one issue at the requested level of detail.

        `brief` answers «what is this and who is on it», `full` adds description, tags
        and custom values, `history` adds the changelog and the discussion. Ask for the
        level you actually need: history of a long-lived issue is kilobytes of text.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await issues_service.read_issue(session, issue, initiator=actor)
            if detail == "brief":
                return views.issue_brief(entry, text_limit=settings.mcp_text_limit)
            payload = views.issue(entry, text_limit=settings.mcp_text_limit)
            if detail == "full":
                return payload
            size = limit or settings.mcp_page_size
            changelog = await events_service.list_changelog(
                session, entry, initiator=actor, limit=size
            )
            discussion = await comments_service.list_comments(
                session, entry, initiator=actor, limit=size
            )
            return payload | {
                "changelog": views.page(
                    (views.changelog_entry(item) for item in changelog.items),
                    next_cursor=changelog.next_cursor,
                ),
                "comments": views.page(
                    (
                        views.comment(item, text_limit=settings.mcp_text_limit)
                        for item in discussion.items
                    ),
                    next_cursor=discussion.next_cursor,
                ),
            }

    @server.tool()
    async def create_issue(
        queue: Annotated[str, Field(description="Queue key the issue is created in")],
        summary: Annotated[str, Field(description="Single line; it is what lists show")],
        description: Annotated[str, Field(description="Markdown body")] = "",
        issue_type: Annotated[
            str | None,
            Field(description="Issue type reference; defaults to the queue default"),
        ] = None,
        status: Annotated[
            str | None,
            Field(description="Status reference; defaults to the queue default"),
        ] = None,
        priority: Annotated[IssuePriority | None, Field(description="Defaults to normal")] = None,
        assignee: Annotated[str | None, Field(description="Actor key")] = None,
        deadline: Annotated[
            datetime | None, Field(description="ISO 8601 with a UTC offset")
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Flat labels")] = None,
        project: Annotated[str | None, Field(description="Project key")] = None,
        values: Annotated[
            dict[str, JsonValue] | None,
            Field(
                description=(
                    "Custom field values keyed by field reference. Which fields exist "
                    "and which of them are required is in `get_queue_config`"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Create an issue. Mutating: this writes to the tracker.

        The key is handed out by the queue counter, not chosen by the caller. Type and
        status default to the queue settings. The author is the actor behind the token.

        A missing required custom field is rejected with the field reference and the
        allowed values in the error details — check `get_queue_config` first when you
        do not know the queue.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            target = await refs.queue(session, queue)
            created = await issues_service.create_issue(
                session,
                initiator=actor,
                queue=target,
                summary=summary,
                description=description,
                issue_type=await refs.optional_issue_type(session, issue_type, initiator=actor),
                status=await refs.optional_status(session, status, initiator=actor),
                priority=priority or IssuePriority.NORMAL,
                assignee=await refs.actor(session, assignee),
                deadline=deadline,
                tags=tags or (),
                project=await refs.optional_project(session, project),
                values=values or {},
            )
            return views.issue(created, text_limit=settings.mcp_text_limit)

    @server.tool()
    async def update_issue(
        issue: Annotated[str, Field(description="Issue key")],
        changes: IssueChangesInput,
        version: Annotated[
            int | None,
            Field(
                ge=1,
                description=(
                    "Version the caller last saw. Sent back it turns a lost update into "
                    "a `version_conflict` instead of silently overwriting someone's work"
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Change the given fields of an issue. Mutating: this writes to the tracker.

        Only the fields you pass are touched. `null` clears `resolution`, `assignee`
        and `deadline`; for every other field it is rejected. `values` is partial too:
        a null value clears one custom field, a key you do not send is left alone.

        To change the status use `transition_issue`: it runs the workflow with its
        checks, while a direct status write is refused when the status is outside the
        assigned graph.
        """
        settings = get_settings()
        given = changes.model_dump(exclude_unset=True)
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            mutation = await issues_service.update_issue(
                session,
                entry,
                initiator=actor,
                changes=issues_service.IssueChanges(
                    summary=given.get("summary", UNSET),
                    description=given.get("description", UNSET),
                    issue_type=await _catalog(
                        session, given, "issue_type", refs.issue_type, initiator=actor
                    ),
                    status=await _catalog(session, given, "status", refs.status, initiator=actor),
                    resolution=await _catalog(
                        session, given, "resolution", refs.resolution, initiator=actor
                    ),
                    priority=given.get("priority", UNSET),
                    assignee=(
                        await refs.actor(session, given["assignee"])
                        if "assignee" in given
                        else UNSET
                    ),
                    deadline=given.get("deadline", UNSET),
                    project=(
                        await refs.optional_project(session, given["project"])
                        if "project" in given
                        else UNSET
                    ),
                    tags=given.get("tags", UNSET),
                    values=given.get("values", UNSET),
                ),
                expected_version=version,
            )
            return views.issue(mutation.issue, text_limit=settings.mcp_text_limit) | {
                "changed_fields": [change.field for change in mutation.changes],
            }

    @server.tool()
    async def assign_issue(
        issue: Annotated[str, Field(description="Issue key")],
        assignee: Annotated[str | None, Field(description="Actor key, or null to unassign")] = None,
        version: Annotated[
            int | None, Field(ge=1, description="Version the caller last saw")
        ] = None,
    ) -> dict[str, Any]:
        """Assign an issue to an actor, or unassign it with null. Mutating.

        The same thing `update_issue` does with the `assignee` field. It is a separate
        tool because assignment is the most frequent single action of an agent, and a
        one-field call is cheaper to get right than a partial update.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            mutation = await issues_service.assign_issue(
                session,
                entry,
                initiator=actor,
                assignee=await refs.actor(session, assignee),
                expected_version=version,
            )
            return views.issue(mutation.issue, text_limit=settings.mcp_text_limit)

    @server.tool()
    async def list_transitions(
        issue: Annotated[str, Field(description="Issue key")],
    ) -> dict[str, Any]:
        """List the workflow transitions of an issue and whether each is available now.

        This is how a status is changed: pick a transition id from here and call
        `transition_issue`. An unavailable transition names what is missing in
        `missing_fields`; `requires_resolution` means the call must carry a resolution.

        The issue version comes back with the list — pass it to `transition_issue` so a
        concurrent change turns into a conflict instead of a silent overwrite.
        """
        async with runtime.call() as (session, actor):
            entry = await issues_service.read_issue(session, issue, initiator=actor)
            available = await workflow_service.available_transitions(
                session,
                entry,
                initiator=actor,
                filled_fields=issues_service.filled_fields_for(entry),
            )
            return {
                "issue": entry.key,
                "status": format_entry_ref(entry.status),
                "version": entry.version,
                "transitions": [views.transition(item) for item in available],
            }

    @server.tool()
    async def transition_issue(
        issue: Annotated[str, Field(description="Issue key")],
        transition: Annotated[str, Field(description="Transition id from `list_transitions`")],
        resolution: Annotated[
            str | None,
            Field(
                description=(
                    "Resolution reference; required when the target status is in the "
                    "`done` category. Leaving `done` clears it on its own"
                )
            ),
        ] = None,
        assignee: Annotated[
            str | None,
            Field(description="Actor key to set together with the status, in one change"),
        ] = None,
        version: Annotated[
            int | None,
            Field(ge=1, description="Version from `list_transitions` or from `get_issue`"),
        ] = None,
    ) -> dict[str, Any]:
        """Move an issue through a workflow transition. Mutating.

        The transition is refused when the workflow has no such edge
        (`transition_not_allowed`), when a required field is empty
        (`transition_requirements_not_met`) or when the target status needs a
        resolution and none was given (`issue_resolution_required`). That is the process
        working, not a defect: read the reason, fill what it names and call again.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            mutation = await issues_service.transition_issue(
                session,
                entry,
                refs.identifier(transition, "transition"),
                initiator=actor,
                changes=issues_service.IssueChanges(
                    resolution=(
                        await refs.resolution(session, resolution, initiator=actor)
                        if resolution is not None
                        else UNSET
                    ),
                    assignee=(
                        await refs.actor(session, assignee) if assignee is not None else UNSET
                    ),
                ),
                expected_version=version,
            )
            return views.issue(mutation.issue, text_limit=settings.mcp_text_limit)


def _selected_fields(fields: list[str] | None) -> tuple[str, ...]:
    """Что вернуть по каждой задаче: краткий набор, всё, или названное клиентом.

    Умолчание — краткий набор, а не полная задача: поиск отвечает на вопрос «что есть»,
    и сто задач со всеми полями съедают контекст целиком. Явная звёздочка означает
    «всё» и передаётся в сценарий пустым набором — так же, как это делает REST.
    """
    if not fields:
        return views.BRIEF_FIELDS
    if "*" in fields:
        return ()
    return tuple(fields)


async def _catalog(
    session: Any,
    given: dict[str, Any],
    name: str,
    resolve: Any,
    *,
    initiator: Any,
) -> Any:
    """Ссылка справочника из переданных полей в объект, сохраняя «не передано» и `null`."""
    if name not in given:
        return UNSET
    ref = given[name]
    return None if ref is None else await resolve(session, ref, initiator=initiator)
