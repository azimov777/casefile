"""Инструмент `create_project`: новый проект, только набором `main`."""

from typing import Annotated

from pydantic import Field

from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.domain.tokens import TokenScope
from app.mcp.arguments import IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.views import ProjectKeyView, project_key
from app.mcp.toolset import FILING, Toolset
from app.services import projects as projects_service

NewProjectKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the new project: a Latin letter followed by 1–15 Latin letters or digits "
            "(`invalid_project_key` otherwise). It is stored upper-case, never changes and "
            "prefixes the key of every task of the project. A key already taken, in any "
            "case, is refused with `project_key_taken`"
        ),
        examples=["TRK"],
    ),
]

ProjectTitleArg = Annotated[str, Field(description="Project title")]


ProjectDescriptionArg = Annotated[
    str,
    Field(
        description=(
            f'Short "what this is", up to {MAX_PROJECT_DESCRIPTION_LENGTH} characters after '
            "trimming; a longer one is refused with `project_description_too_long`. It rides "
            "in the card of every task of the project"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `create_project` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def create_project(
        key: NewProjectKeyArg,
        title: ProjectTitleArg,
        description: ProjectDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> ProjectKeyView:
        """Creates a project with a key, a title and a description. Only a `main` token
        creates projects.
        """
        async with runtime.call() as (session, actor):

            async def create() -> ProjectKeyView:
                return project_key(
                    await projects_service.create_project(
                        session, actor=actor, key=key, title=title, description=description
                    )
                )

            return await Once.of(create_project, session, actor, idempotency_key).run(
                result=ProjectKeyView,
                request={"key": key, "title": title, "description": description},
                build=create,
            )
