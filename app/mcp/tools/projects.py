"""Инструменты проектов и портфелей: результат, ради которого идёт работа.

Очередь показывает процесс, а «сколько сделано по проекту» живёт только здесь: прогресс
считается по задачам проекта в статусах категории `done` и нигде не хранится, поэтому
он никогда не расходится с реальностью.

Списка задач проекта тут нет намеренно: это `search_issues` с условием
`project: <ключ>`. Второй способ отбирать задачи разошёлся бы с поиском на первом же
краевом случае — и разошёлся бы молча, разной выдачей на одинаковый по смыслу вопрос
(выявлено в задаче 10).
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.core.config import get_settings
from app.db.pagination import MAX_PAGE_SIZE
from app.domain.projects import Progress, ProjectStatus
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import projects as projects_service


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты планирования."""

    @server.tool()
    async def list_projects(
        portfolio: Annotated[
            str | None, Field(description="Portfolio key: only projects lying in it")
        ] = None,
        project_status: Annotated[
            ProjectStatus | None, Field(description="Filter by planning status")
        ] = None,
        is_archived: Annotated[
            bool | None, Field(description="Filter by the archived flag; omit to get both")
        ] = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List projects with their progress.

        Progress is `done / total` over the issues of the project, counted at read
        time. `ratio` is null when the project has no issues at all — that is not the
        same as «nothing is done».
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            page = await projects_service.list_projects(
                session,
                initiator=actor,
                portfolio=await refs.optional_portfolio(session, portfolio),
                status=project_status,
                is_archived=is_archived,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            progress = await projects_service.project_progress(session, page.items)
            return views.page(
                (
                    views.project(item, progress=progress.get(item.id, Progress()))
                    for item in page.items
                ),
                next_cursor=page.next_cursor,
            )

    @server.tool()
    async def get_project(
        project: Annotated[str, Field(description="Project key, for example `alpha`")],
    ) -> dict[str, Any]:
        """Read a project card with its progress.

        The issues themselves come from `search_issues` with `project: <key>` — that
        way the query language, sorting, field selection and paging all work the same
        as everywhere else.
        """
        async with runtime.call() as (session, actor):
            entry = await projects_service.read_project(session, project, initiator=actor)
            progress = await projects_service.project_progress(session, [entry])
            return views.project(entry, progress=progress.get(entry.id, Progress()))

    @server.tool()
    async def add_issues_to_project(
        project: Annotated[str, Field(description="Project key")],
        issues: Annotated[
            list[str], Field(min_length=1, description="Issue keys, possibly from several queues")
        ],
    ) -> dict[str, Any]:
        """Put issues into a project. Mutating: this writes to the tracker.

        An issue already in this project is left alone and is not an error; an issue
        from another project moves over, and that shows in its changelog as an ordinary
        field change. The version of every added issue grows.
        """
        async with runtime.call() as (session, actor):
            entry = await projects_service.read_project(session, project, initiator=actor)
            resolved = [await refs.issue(session, key) for key in issues]
            mutations = await projects_service.add_issues(
                session, entry, initiator=actor, issues=resolved
            )
            progress = await projects_service.project_progress(session, [entry])
            return views.project(entry, progress=progress.get(entry.id, Progress())) | {
                "added": [mutation.issue.key for mutation in mutations if mutation.changed],
            }

    @server.tool()
    async def remove_issue_from_project(
        project: Annotated[str, Field(description="Project key")],
        issue: Annotated[str, Field(description="Issue key to take out")],
    ) -> dict[str, Any]:
        """Take an issue out of a project. Mutating.

        The issue itself stays in its queue. An issue that belongs to a different
        project is refused with `project_not_found` and the reason
        `issue_not_in_project`: a silent success would leave the caller sure it worked.
        """
        async with runtime.call() as (session, actor):
            entry = await projects_service.read_project(session, project, initiator=actor)
            target = await refs.issue(session, issue)
            await projects_service.remove_issue(session, entry, initiator=actor, issue=target)
            progress = await projects_service.project_progress(session, [entry])
            return views.project(entry, progress=progress.get(entry.id, Progress())) | {
                "removed": target.key,
            }

    @server.tool()
    async def list_portfolios(
        parent: Annotated[
            str | None, Field(description="Portfolio key: only portfolios nested in it")
        ] = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List portfolios with their progress and how much they hold.

        A portfolio collects projects and other portfolios; its progress sums the
        issues underneath, so it answers «how much of the work below is done».
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            page = await projects_service.list_portfolios(
                session,
                initiator=actor,
                parent=await refs.optional_portfolio(session, parent),
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            progress = await projects_service.portfolio_progress(session, page.items)
            counts = await projects_service.portfolio_child_counts(session, page.items)
            return views.page(
                (
                    views.portfolio(
                        item,
                        progress=progress.get(item.id, Progress()),
                        counts=counts,
                    )
                    for item in page.items
                ),
                next_cursor=page.next_cursor,
            )

    @server.tool()
    async def get_portfolio(
        portfolio: Annotated[str, Field(description="Portfolio key")],
        limit: Annotated[
            int | None,
            Field(ge=1, le=MAX_PAGE_SIZE, description="Page size of the content listing"),
        ] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous content page")
        ] = None,
    ) -> dict[str, Any]:
        """Read a portfolio with its progress and its content.

        The content is one paged collection of projects and nested portfolios; `kind`
        tells them apart.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await projects_service.read_portfolio(session, portfolio, initiator=actor)
            progress = await projects_service.portfolio_progress(session, [entry])
            counts = await projects_service.portfolio_child_counts(session, [entry])
            content = await projects_service.portfolio_content(
                session,
                entry,
                initiator=actor,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.portfolio(
                entry, progress=progress.get(entry.id, Progress()), counts=counts
            ) | {
                "content": views.page(
                    (
                        {
                            "kind": item.kind.value,
                            "key": item.entity.key,
                            "name": item.entity.name,
                            "status": item.entity.status.value,
                        }
                        for item in content.items
                    ),
                    next_cursor=content.next_cursor,
                ),
            }
