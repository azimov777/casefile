"""Инструмент `restore_project`: вернуть проект из архива с причиной, только набором `main`."""

from app.domain.tokens import TokenScope
from app.mcp.arguments import ProjectKeyArg
from app.mcp.tools.registries.arguments import ProjectReasonArg
from app.mcp.tools.registries.views import ProjectArchiveView, project_archive
from app.mcp.toolset import FILING, Toolset
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `restore_project` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN)
    async def restore_project(key: ProjectKeyArg, reason: ProjectReasonArg) -> ProjectArchiveView:
        """Brings an archived project back: files a `restored` entry carrying the reason in
        its case, and its tasks resume where the archive left them. Only a `main` token
        restores.

        A project that is not archived is refused with `project_not_archived`.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)
            entry = await projects_service.restore_project(
                session, project, actor=actor, reason=reason
            )
            return project_archive(project, entry)
