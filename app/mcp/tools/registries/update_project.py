"""Инструмент `update_project`: название и описание проекта, только набором `main`."""

from typing import Annotated

from pydantic import Field

from app.domain.tokens import TokenScope
from app.mcp.arguments import ProjectKeyArg
from app.mcp.tools.registries.views import ProjectKeyView, project_key
from app.mcp.toolset import IDEMPOTENT_TASK_UPDATE, Toolset
from app.services import projects as projects_service

# Отдельные аннотации для правки: `None` здесь означает «не передано». Осмысленного
# `null` ни у названия, ни у описания нет, поэтому третьего состояния и не нужно — в
# отличие от исполнителя задачи, который `null` как раз снимается.
ProjectTitleChangeArg = Annotated[
    str | None, Field(description="New title; when left out, the title stays")
]

ProjectDescriptionChangeArg = Annotated[
    str | None, Field(description="New description; when left out, the description stays")
]


def register(tools: Toolset) -> None:
    """Объявляет `update_project` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=IDEMPOTENT_TASK_UPDATE, scope=TokenScope.MAIN)
    async def update_project(
        key: ProjectKeyArg,
        title: ProjectTitleChangeArg = None,
        description: ProjectDescriptionChangeArg = None,
    ) -> ProjectKeyView:
        """Changes a project's title and description; a field left out stays. Only a `main`
        token edits projects. The key never changes. Each changed field files a
        `field_changed` entry with the previous and the new value in the project's case;
        a value equal to the current one files nothing.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)
            return project_key(
                await projects_service.update_project(
                    session, project, actor=actor, title=title, description=description
                )
            )
