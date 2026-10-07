"""Инструмент `update_project`: название и описание проекта или области."""

from typing import Annotated

from pydantic import Field

from app.db.models.area import Area
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.mcp.arguments import CaseOwnerKeyArg
from app.mcp.tools.registries.views import ProjectKeyView, project_key
from app.mcp.toolset import IDEMPOTENT_TASK_UPDATE, Toolset
from app.services import areas as areas_service
from app.services import projects as projects_service

# Отдельные аннотации для правки: `None` здесь означает «не передано». Осмысленного
# `null` ни у названия, ни у описания нет, поэтому третьего состояния и не нужно — в
# отличие от исполнителя задачи, который `null` как раз снимается.
ProjectTitleChangeArg = Annotated[
    str | None, Field(description="New title; when left out, the title stays")
]

ProjectDescriptionChangeArg = Annotated[
    str | None,
    Field(
        description=(
            f"New description, up to {MAX_PROJECT_DESCRIPTION_LENGTH} characters after "
            "trimming (`project_description_too_long` or `area_description_too_long` "
            "otherwise); when left out, the description stays"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `update_project`."""
    runtime = tools.runtime

    @tools.tool(title="Update project", annotations=IDEMPOTENT_TASK_UPDATE)
    async def update_project(
        key: CaseOwnerKeyArg,
        title: ProjectTitleChangeArg = None,
        description: ProjectDescriptionChangeArg = None,
    ) -> ProjectKeyView:
        """Changes the title and description of a project or area card; a field left
        out stays. The key never changes. Each changed field files a `field_changed`
        entry with the previous and the new value in the card owner's case;
        a value equal to the current one files nothing.
        """
        async with runtime.call() as (session, actor):
            owner = await areas_service.get_owner(session, key)
            if isinstance(owner, Area):
                updated = await areas_service.update_area(
                    session, owner, actor=actor, title=title, description=description
                )
            else:
                updated = await projects_service.update_project(
                    session, owner, actor=actor, title=title, description=description
                )
            return project_key(updated)
