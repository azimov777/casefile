"""Инструмент `get_project`: проект с описанием — общим контекстом его задач."""

from pydantic import BaseModel, Field

from app.db.models.project import Project
from app.mcp.arguments import ProjectKeyArg
from app.mcp.toolset import READ_ONLY, Toolset
from app.services import projects as projects_service


class ProjectView(BaseModel):
    """Project with its description."""

    key: str
    title: str
    description: str = Field(
        description=(
            "Shared context of all tasks of the project: where the code lives, which "
            "documents apply, what is out of bounds. Task cards carry only the project's "
            "key and title"
        )
    )


def project(item: Project) -> ProjectView:
    """Проект с описанием — общим контекстом всех его задач.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом.
    """
    return ProjectView(key=item.key, title=item.title, description=item.description)


def register(tools: Toolset) -> None:
    """Объявляет `get_project` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=READ_ONLY)
    async def get_project(key: ProjectKeyArg) -> ProjectView:
        """Returns one project by its key: key, title and description.

        The keys of the installation's projects are listed by `list_projects`.
        """
        async with runtime.call() as (session, actor):
            return project(await projects_service.read_project(session, key, actor=actor))
