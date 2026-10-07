"""Инструмент `archive_project`: заморозить проект или область с причиной."""

from app.db.models.area import Area
from app.mcp.arguments import CaseOwnerKeyArg
from app.mcp.tools.registries.arguments import ProjectReasonArg
from app.mcp.tools.registries.views import ProjectArchiveView, project_archive
from app.mcp.toolset import FILING, Toolset
from app.services import areas as areas_service
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `archive_project`."""
    runtime = tools.runtime

    @tools.tool(title="Archive project", annotations=FILING)
    async def archive_project(key: CaseOwnerKeyArg, reason: ProjectReasonArg) -> ProjectArchiveView:
        """Archives a project with a reason and files an `archived` entry in its case.

        The project and its tasks freeze as they are: statuses stay, open tasks need no
        closing. From then on any change in the project or its tasks — a new task, an
        entry, a transition, an edit, an attribute, a new link — is refused with
        `project_archived`, until `restore_project`. The one change still accepted is
        `unlink` of a link with its task: an open archived task keeps blocking its
        `blocked_by` tasks and holding its parent until the link is removed. Reads work
        as before.

        An area address archives the area: its card, attributes and case refuse
        changes with `area_archived`.

        An already archived project is refused with `project_archived`, an area with
        `area_archived`.
        """
        async with runtime.call() as (session, actor):
            owner = await areas_service.get_owner(session, key)
            if isinstance(owner, Area):
                entry = await areas_service.archive_area(session, owner, actor=actor, reason=reason)
            else:
                entry = await projects_service.archive_project(
                    session, owner, actor=actor, reason=reason
                )
            return project_archive(owner, entry)
