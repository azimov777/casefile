"""Инструмент `archive_project`: заморозить проект с причиной, только набором `main`."""

from app.domain.tokens import TokenScope
from app.mcp.arguments import ProjectKeyArg
from app.mcp.tools.registries.arguments import ProjectReasonArg
from app.mcp.tools.registries.views import ProjectArchiveView, project_archive
from app.mcp.toolset import FILING, Toolset
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `archive_project` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN)
    async def archive_project(key: ProjectKeyArg, reason: ProjectReasonArg) -> ProjectArchiveView:
        """Archives a project with a reason and files an `archived` entry in its case. Only
        a `main` token archives.

        The project and its tasks freeze as they are: statuses stay, open tasks need no
        closing. From then on any change in the project or its tasks — a new task, an
        entry, a transition, an edit, an attribute, a new link — is refused with
        `project_archived`, until `restore_project`. The one change still accepted is
        `unlink` of a link with its task: an open archived task keeps blocking its
        `blocked_by` tasks and holding its parent until the link is removed. Reads work
        as before.

        An already archived project is refused with `project_archived`.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)
            entry = await projects_service.archive_project(
                session, project, actor=actor, reason=reason
            )
            return project_archive(project, entry)
