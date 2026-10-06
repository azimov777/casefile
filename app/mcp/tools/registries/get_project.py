"""Инструмент `get_project`: проект с описанием, атрибутами, действующими решениями,
направлениями и описью его дела — и по адресу направление в той же форме.

Отдельного чтения направления нет намеренно (`CONCEPT.md`, 3.7; замер — дело TRK-555):
опись дела несёт в `outputSchema` всю форму фактов, и второй инструмент с описью повторил
бы её целиком. Направление устроено как проект, и форма ответа у них одна; решения и
направления у направления пусты.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.db.models.attribute import Attribute
from app.db.models.direction import Direction
from app.domain.case import EntryHeading
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.mcp.arguments import CaseOwnerKeyArg
from app.mcp.tools.case.views import HeadingView, heading
from app.mcp.toolset import READ_ONLY, Toolset
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import decisions as decisions_service
from app.services import directions as directions_service
from app.services.case import CaseOwner, owner_name
from app.services.decisions import ProjectDecision

IncludeArchivedDirectionsArg = Annotated[
    bool,
    Field(description="Also list archived directions"),
]


class AttributeView(BaseModel):
    """Current value of a project attribute."""

    name: str = Field(description="Name as it was first set; matching ignores case")
    value: str


class DirectionRefView(BaseModel):
    """Direction: address, title and archive time."""

    address: str
    title: str
    archived_at: datetime | None


class DecisionInForceView(BaseModel):
    """Project decision in force: its address and the decision in one line."""

    ref: str = Field(
        description="Address of the `decision` entry in the project's case",
        examples=["TRK#15"],
    )
    title: str


class ProjectView(BaseModel):
    """Project with its description, attributes and the index of its case."""

    key: str
    title: str
    description: str = Field(
        description=(
            f'Short "what this is" of the project, up to {MAX_PROJECT_DESCRIPTION_LENGTH} '
            "characters; may be empty. Every task card carries it too"
        )
    )
    archived_at: datetime | None = Field(
        description=(
            "When the project was archived, `null` while it is active. An archived project "
            "and its tasks refuse changes with `project_archived`, an archived direction "
            "with `direction_archived`; `restore_project` lifts it"
        )
    )
    attributes: list[AttributeView] = Field(
        description=(
            "Current attribute values, ordered by name ignoring case. Their history is "
            "in the project's case: `attribute_created`, `attribute_changed` and "
            "`attribute_removed` entries"
        )
    )
    decisions: list[DecisionInForceView] = Field(
        description=(
            "Project decisions in force, in number order: `decision` entries of the "
            "project's case that no later decision names in `supersedes`. Bodies come from "
            "`read_project_entries`; the tasks citing a decision, from `search_tasks` with "
            "`decision`"
        )
    )
    directions: list[DirectionRefView] = Field(
        description=(
            "Directions of the project by key, created by `create_project`; empty for a direction"
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
    item: CaseOwner,
    attributes: list[Attribute],
    decisions: list[ProjectDecision],
    directions: list[Direction],
    index: list[EntryHeading],
) -> ProjectView:
    """Проект (или направление) с описанием — общим контекстом всех его задач — и описью
    его дела.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом. Опись — те же
    строки, что у дела задачи в `get_task`: заголовки без тел.
    """
    return ProjectView(
        key=owner_name(item),
        title=item.title,
        description=item.description,
        archived_at=item.archived_at,
        attributes=[AttributeView(name=a.name, value=a.value) for a in attributes],
        decisions=[DecisionInForceView(ref=d.ref, title=d.entry.title) for d in decisions],
        directions=[
            DirectionRefView(address=d.address, title=d.title, archived_at=d.archived_at)
            for d in directions
        ],
        index=[heading(line) for line in index],
    )


def register(tools: Toolset) -> None:
    """Объявляет `get_project`."""
    runtime = tools.runtime

    @tools.tool(title="Get project", annotations=READ_ONLY)
    async def get_project(
        key: CaseOwnerKeyArg, include_archived_directions: IncludeArchivedDirectionsArg = False
    ) -> ProjectView:
        """Returns one project by its key: key, title, description, current attribute
        values, the project decisions in force, its directions and the index of the
        project's case. A direction address returns the direction in the same shape.

        The keys of the installation's projects are listed by `list_projects`.
        """
        async with runtime.call() as (session, actor):
            found = await directions_service.get_owner(session, key)
            attributes = await attributes_service.list_attributes(session, found, actor=actor)
            if isinstance(found, Direction):
                decisions: list[ProjectDecision] = []
                directions: list[Direction] = []
            else:
                decisions = await decisions_service.in_force(session, found, actor=actor)
                directions = await directions_service.list_directions(
                    session, found, actor=actor, include_archived=include_archived_directions
                )
            index = await case_service.project_case_index(session, found, actor=actor)
            return project(found, attributes, decisions, directions, index)
