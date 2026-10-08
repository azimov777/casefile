"""Инструмент `create_project`: новый проект — или, по адресу `ПРОЕКТ/ключ`, новая
область проекта.

Своего инструмента у области нет (TRK#57): аргументы те же — ключ, название,
описание, — и отдельный инструмент стоил бы в `tools/list` больше, чем укладывается в
предел задачи (замер — дело TRK-555). Здесь же агент впервые встречает само понятие,
поэтому описание определяет его и называет границу с задачей-родителем.
"""

from typing import Annotated

from pydantic import Field

from app.db.models.area import Area
from app.db.models.project import Project
from app.domain.areas import is_area_address
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.mcp.arguments import IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.views import ProjectKeyView, project_key
from app.mcp.toolset import FILING, Toolset
from app.services import areas as areas_service
from app.services import projects as projects_service

NewProjectKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the new project: a Latin letter followed by 1–15 Latin letters or digits "
            "(`invalid_project_key` otherwise). It is stored upper-case, never changes and "
            "prefixes the key of every task of the project. A key already taken, in any "
            "case, is refused with `project_key_taken`.\n"
            "An address `PROJECT/key` creates an area of that project; its key is "
            "lower-case Latin letters, digits and inner hyphens (`invalid_area_key` "
            "otherwise), and a key taken there is refused with `area_key_taken`"
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
            "trimming; a longer one is refused with `project_description_too_long` or "
            "`area_description_too_long`. It rides in the card of every task of the "
            "project"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `create_project`."""
    runtime = tools.runtime

    @tools.tool(title="Create project", annotations=FILING, creating=True)
    async def create_project(
        key: NewProjectKeyArg,
        title: ProjectTitleArg,
        description: ProjectDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> ProjectKeyView:
        """Creates a project with a key, a title and a description.

        With an address it creates an area: an endless part of a project's work with
        its own attributes and case, and no status, assignee, checks or closing; work with
        a check that ends it is a parent task with children. The tools of a project take
        the area address in place of the project key.
        """
        async with runtime.call() as (session, actor):

            async def create() -> ProjectKeyView:
                created: Project | Area
                if is_area_address(key):
                    created = await areas_service.create_area(
                        session, actor=actor, address=key, title=title, description=description
                    )
                else:
                    created = await projects_service.create_project(
                        session, actor=actor, key=key, title=title, description=description
                    )
                return project_key(created)

            return await Once.of(create_project, session, actor, idempotency_key).run(
                result=ProjectKeyView,
                request={"key": key, "title": title, "description": description},
                build=create,
            )
