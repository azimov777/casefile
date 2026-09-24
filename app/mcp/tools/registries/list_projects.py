"""Инструмент `list_projects`: проекты установки строкой — ключ и название."""

from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, ProjectRefView, page, project_ref
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `list_projects` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def list_projects(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[ProjectRefView]:
        """Lists the installation's projects, one page at a time: key and title. A project's
        description is returned by `get_project`.
        """
        async with runtime.call() as (session, actor):
            listed = await projects_service.list_projects(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return page(
                (project_ref(item) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
