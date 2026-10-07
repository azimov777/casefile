"""Инструмент `get_project`: проект с описанием, атрибутами, действующими решениями и
заметками, направлениями и описью его дела — и по адресу направление в той же форме.

Отдельного чтения направления нет намеренно (`CONCEPT.md`, 3.7; замер — дело TRK-555):
опись дела несёт в `outputSchema` всю форму фактов, и второй инструмент с описью повторил
бы её целиком. Направление устроено как проект, и форма ответа у них одна; решения,
заметки и направления у направления пусты.

Решений и заметок в описи проекта нет (решение TRK#48, раздел 3; задача TRK-657): опись с
646 заметками стоила ≈ 87 тыс. токенов на вызов (TRK-598#11). Действующие приходят
списками «ссылка и заголовок», число всех по типам — в `index_omitted`, тела и заменённые —
`read_project_entries`. Режима «опись целиком» рядом не оставлено (TRK#12).
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
from app.services.decisions import CaseKnowledge

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


class InForceView(BaseModel):
    """Decision or finding in force: its address and title."""

    ref: str = Field(description="Address of the entry in the project's case", examples=["TRK#15"])
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
    decisions: list[InForceView] = Field(
        description=(
            "Project decisions in force, in number order: `decision` entries of the "
            "project's case that no later decision names in `supersedes`. Bodies come from "
            "`read_project_entries`; the tasks citing a decision, from `search_tasks` with "
            "`decision`"
        )
    )
    findings: list[InForceView] = Field(
        description=(
            "Project findings in force, in number order: `finding` entries of the project's "
            "case that no later finding names in `supersedes`; empty for a direction"
        )
    )
    directions: list[DirectionRefView] = Field(
        description=(
            "Directions of the project by key, created by `create_project`; empty for a direction"
        )
    )
    index: list[HeadingView] = Field(
        description=(
            "Index of the case, titles only, in number order: artifacts and notes and the "
            "tracker's entries about the card. A project's decisions and findings are left "
            "out, in force or superseded; a direction's index holds every entry of its "
            "case. Entry bodies come from `read_project_entries`"
        )
    )
    # Словарь с ключами-строками, а не модель и не ключи-перечисление: `EntryTypeSchema`
    # встраивает в `outputSchema` весь список типов записи ещё раз, модель — свой `$defs`.
    index_omitted: dict[str, int] = Field(
        description=(
            "Number of entries left out of `index`, by type, `decision` and `finding`: all "
            "of them in a project's case, the superseded ones included. "
            "`read_project_entries` returns them by `types`, `in_force` and `text`. Empty "
            "for a direction"
        )
    )


def project(
    item: CaseOwner,
    attributes: list[Attribute],
    knowledge: CaseKnowledge | None,
    directions: list[Direction],
    index: list[EntryHeading],
) -> ProjectView:
    """Проект (или направление) с описанием — общим контекстом всех его задач — и описью
    его дела.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом. Опись — те же
    строки, что у дела задачи в `get_task`: заголовки без тел. `knowledge` — `None` у
    направления: записей знания со статусом в его деле нет, и списки пусты.
    """
    return ProjectView(
        key=owner_name(item),
        title=item.title,
        description=item.description,
        archived_at=item.archived_at,
        attributes=[AttributeView(name=a.name, value=a.value) for a in attributes],
        decisions=[]
        if knowledge is None
        else [InForceView(ref=d.ref, title=d.title) for d in knowledge.decisions],
        findings=[]
        if knowledge is None
        else [InForceView(ref=f.ref, title=f.title) for f in knowledge.findings],
        directions=[
            DirectionRefView(address=d.address, title=d.title, archived_at=d.archived_at)
            for d in directions
        ],
        index=[heading(line) for line in index],
        index_omitted={}
        if knowledge is None
        else {kind.value: count for kind, count in knowledge.totals.items()},
    )


def register(tools: Toolset) -> None:
    """Объявляет `get_project`."""
    runtime = tools.runtime

    @tools.tool(title="Get project", annotations=READ_ONLY)
    async def get_project(
        key: CaseOwnerKeyArg, include_archived_directions: IncludeArchivedDirectionsArg = False
    ) -> ProjectView:
        """Returns one project by its key: key, title, description, current attribute
        values, the project decisions and findings in force by address and title, its
        directions and the index of the project's case. Decisions and findings stay out
        of that index; `index_omitted` counts them by type. A direction address returns
        the direction in the same shape, its index holding every entry of its case.

        The keys of the installation's projects are listed by `list_projects`.
        """
        async with runtime.call() as (session, actor):
            found = await directions_service.get_owner(session, key)
            attributes = await attributes_service.list_attributes(session, found, actor=actor)
            if isinstance(found, Direction):
                knowledge: CaseKnowledge | None = None
                directions: list[Direction] = []
            else:
                knowledge = await decisions_service.case_knowledge(session, found, actor=actor)
                directions = await directions_service.list_directions(
                    session, found, actor=actor, include_archived=include_archived_directions
                )
            index = await case_service.project_case_index(session, found, actor=actor)
            return project(found, attributes, knowledge, directions, index)
