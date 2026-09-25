"""Инструмент `list_projects`: проекты установки строкой — ключ, название и время архива."""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.db.models.project import Project
from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, ProjectRefView, page
from app.services import projects as projects_service

IncludeArchivedArg = Annotated[
    bool,
    Field(
        description=(
            "Also list archived projects; without it they are left out. A project is read "
            "by its key with `get_project` either way"
        )
    ),
]


# Строка списка — строка проекта (`ProjectRefView`) плюс время архива: с
# `include_archived` в одной выдаче стоят живые и архивные, и различить их больше нечем.
# В строке поиска этого поля нет: там проект не главный предмет ответа.
class ProjectRowView(ProjectRefView):
    """Project in one line: key, title and when it was archived."""

    archived_at: datetime | None = Field(
        description="When the project was archived, `null` while it is active"
    )


def project_row(item: Project) -> ProjectRowView:
    """Строка `list_projects`."""
    return ProjectRowView(key=item.key, title=item.title, archived_at=item.archived_at)


def register(tools: Toolset) -> None:
    """Объявляет `list_projects` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def list_projects(
        include_archived: IncludeArchivedArg = False,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[ProjectRowView]:
        """Lists the installation's projects, one page at a time: key, title and archive
        time. A project's description is returned by `get_project`.
        """
        async with runtime.call() as (session, actor):
            listed = await projects_service.list_projects(
                session,
                actor=actor,
                include_archived=include_archived,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (project_row(item) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
