"""Инструмент `get_project`: проект с описанием, атрибутами и описью его дела."""

from pydantic import BaseModel, Field

from app.db.models.attribute import ProjectAttribute
from app.db.models.project import Project
from app.domain.case import EntryHeading
from app.mcp.arguments import ProjectKeyArg
from app.mcp.tools.case.views import HeadingView, heading
from app.mcp.toolset import READ_ONLY, Toolset
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import projects as projects_service


class AttributeView(BaseModel):
    """Current value of a project attribute."""

    name: str = Field(description="Name as it was first set; matching ignores case")
    value: str


class ProjectView(BaseModel):
    """Project with its description, attributes and the index of its case."""

    key: str
    title: str
    description: str = Field(
        description=(
            "Shared context of all tasks of the project: where the code lives, which "
            "documents apply, what is out of bounds. Task cards carry only the project's "
            "key and title"
        )
    )
    attributes: list[AttributeView] = Field(
        description=(
            "Current attribute values, ordered by name ignoring case. Their history is "
            "in the project's case: `attribute_created`, `attribute_changed` and "
            "`attribute_removed` entries"
        )
    )
    index: list[HeadingView] = Field(
        description=(
            "Index of the project's case, titles only, in number order: decisions, "
            "findings, artifacts and notes about the project and the tracker's entries "
            "about its card. Entry bodies come from `read_project_entries`"
        )
    )


def project(
    item: Project, attributes: list[ProjectAttribute], index: list[EntryHeading]
) -> ProjectView:
    """Проект с описанием — общим контекстом всех его задач — и описью его дела.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом. Опись — те же
    строки, что у дела задачи в `get_task`: заголовки без тел.
    """
    return ProjectView(
        key=item.key,
        title=item.title,
        description=item.description,
        attributes=[AttributeView(name=a.name, value=a.value) for a in attributes],
        index=[heading(line) for line in index],
    )


def register(tools: Toolset) -> None:
    """Объявляет `get_project` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=READ_ONLY)
    async def get_project(key: ProjectKeyArg) -> ProjectView:
        """Returns one project by its key: key, title, description, current attribute
        values and the index of the project's case.

        The keys of the installation's projects are listed by `list_projects`.
        """
        async with runtime.call() as (session, actor):
            found = await projects_service.read_project(session, key, actor=actor)
            attributes = await attributes_service.list_attributes(session, found, actor=actor)
            index = await case_service.project_case_index(session, found, actor=actor)
            return project(found, attributes, index)
