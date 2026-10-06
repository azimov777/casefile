"""Инструмент `restore_project`: вернуть проект или направление из архива с причиной."""

from app.db.models.direction import Direction
from app.mcp.arguments import CaseOwnerKeyArg
from app.mcp.tools.registries.arguments import ProjectReasonArg
from app.mcp.tools.registries.views import ProjectArchiveView, project_archive
from app.mcp.toolset import FILING, Toolset
from app.services import directions as directions_service
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `restore_project`."""
    runtime = tools.runtime

    @tools.tool(title="Restore project", annotations=FILING)
    async def restore_project(key: CaseOwnerKeyArg, reason: ProjectReasonArg) -> ProjectArchiveView:
        """Brings an archived project or direction back: files a `restored` entry carrying
        the reason in its case, and its tasks resume where the archive left them.

        One that is not archived is refused with `project_not_archived` or
        `direction_not_archived`; a direction of an archived project, with
        `project_archived`.
        """
        async with runtime.call() as (session, actor):
            owner = await directions_service.get_owner(session, key)
            if isinstance(owner, Direction):
                entry = await directions_service.restore_direction(
                    session, owner, actor=actor, reason=reason
                )
            else:
                entry = await projects_service.restore_project(
                    session, owner, actor=actor, reason=reason
                )
            return project_archive(owner, entry)
