"""Инструмент `archive_project`: заморозить проект или направление с причиной."""

from app.db.models.direction import Direction
from app.mcp.arguments import CaseOwnerKeyArg
from app.mcp.tools.registries.arguments import ProjectReasonArg
from app.mcp.tools.registries.views import ProjectArchiveView, project_archive
from app.mcp.toolset import FILING, Toolset
from app.services import directions as directions_service
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

        A direction address archives the direction: its card, attributes and case refuse
        changes with `direction_archived`.

        An already archived project is refused with `project_archived`, a direction with
        `direction_archived`.
        """
        async with runtime.call() as (session, actor):
            owner = await directions_service.get_owner(session, key)
            if isinstance(owner, Direction):
                entry = await directions_service.archive_direction(
                    session, owner, actor=actor, reason=reason
                )
            else:
                entry = await projects_service.archive_project(
                    session, owner, actor=actor, reason=reason
                )
            return project_archive(owner, entry)
