"""Инструмент `get_project`: проект с описанием, атрибутами, действующими решениями и
заметками, областями и описью его дела — и по адресу область в той же форме.

Отдельного чтения области нет намеренно (`CONCEPT.md`, 3.7; замер — дело TRK-555):
опись дела несёт в `outputSchema` всю форму фактов, и второй инструмент с описью повторил
бы её целиком. Область устроена как проект, и форма ответа у них одна (решение TRK#57,
раздел 6): свои действующие решения и заметки, `index_omitted` и опись без них; список
областей у области пуст.

Решений и заметок в описи нет (решение TRK#48, раздел 3; задача TRK-657): опись с 646
заметками стоила ≈ 87 тыс. токенов на вызов (TRK-598#11). Действующие приходят списками
«ссылка и заголовок», число всех по типам — в `index_omitted`, тела и заменённые —
`read_project_entries`. Режима «опись целиком» рядом не оставлено (TRK#12).
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.db.models.area import Area
from app.db.models.attribute import Attribute
from app.domain.case import EntryHeading
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.mcp.arguments import CaseOwnerKeyArg
from app.mcp.tools.case.views import HeadingView, heading
from app.mcp.toolset import READ_ONLY, Toolset
from app.services import areas as areas_service
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import decisions as decisions_service
from app.services.case import CaseOwner, owner_name
from app.services.decisions import CaseKnowledge

IncludeArchivedAreasArg = Annotated[
    bool,
    Field(description="Also list archived areas"),
]


class AttributeView(BaseModel):
    """Current value of a project attribute."""

    name: str = Field(description="Name as it was first set; matching ignores case")
    value: str


class AreaRefView(BaseModel):
    """Area: address, title and archive time."""

    address: str
    title: str
    archived_at: datetime | None


class InForceView(BaseModel):
    """Decision or finding in force: its address and title."""

    ref: str = Field(
        description="Address of the entry in the case: `TRK#15` or `TRK/mcp#3`",
        examples=["TRK#15"],
    )
    title: str


class ProjectView(BaseModel):
    """Project or area with its description, attributes and the index of its case."""

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
            "and its tasks refuse changes with `project_archived`, an archived area "
            "with `area_archived`; `restore_project` lifts it"
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
            "Decisions in force, in number order: `decision` entries of the case that no "
            "later decision names in `supersedes`. An area's decisions in force set the work "
            "in it, as the project's set the work in the whole project. Bodies come from "
            "`read_project_entries`; the tasks citing a decision, from `search_tasks` with "
            "`decision`"
        )
    )
    findings: list[InForceView] = Field(
        description=(
            "Findings in force, in number order: `finding` entries of the case that no "
            "later finding names in `supersedes`"
        )
    )
    areas: list[AreaRefView] = Field(
        description=("Areas of the project by key, created by `create_project`; empty for an area")
    )
    index: list[HeadingView] = Field(
        description=(
            "Index of the case, titles only, in number order: artifacts and notes and the "
            "tracker's entries about the card. Decisions and findings are left out, in "
            "force or superseded. Entry bodies come from `read_project_entries`"
        )
    )
    # Словарь с ключами-строками, а не модель и не ключи-перечисление: `EntryTypeSchema`
    # встраивает в `outputSchema` весь список типов записи ещё раз, модель — свой `$defs`.
    index_omitted: dict[str, int] = Field(
        description=(
            "Number of entries left out of `index`, by type, `decision` and `finding`: all "
            "of them in the case, the superseded ones included. `read_project_entries` "
            "returns them by `types`, `in_force` and `text`"
        )
    )


def project(
    item: CaseOwner,
    attributes: list[Attribute],
    knowledge: CaseKnowledge,
    areas: list[Area],
    index: list[EntryHeading],
) -> ProjectView:
    """Проект (или область) с описанием — общим контекстом всех его задач — и описью
    его дела.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом. Опись — те же
    строки, что у дела задачи в `get_task`: заголовки без тел. Знание — у проекта и у
    области одной формой (решение TRK#57, раздел 6).
    """
    return ProjectView(
        key=owner_name(item),
        title=item.title,
        description=item.description,
        archived_at=item.archived_at,
        attributes=[AttributeView(name=a.name, value=a.value) for a in attributes],
        decisions=[InForceView(ref=d.ref, title=d.title) for d in knowledge.decisions],
        findings=[InForceView(ref=f.ref, title=f.title) for f in knowledge.findings],
        areas=[
            AreaRefView(address=d.address, title=d.title, archived_at=d.archived_at) for d in areas
        ],
        index=[heading(line) for line in index],
        index_omitted={kind.value: count for kind, count in knowledge.totals.items()},
    )


def register(tools: Toolset) -> None:
    """Объявляет `get_project`."""
    runtime = tools.runtime

    @tools.tool(title="Get project", annotations=READ_ONLY)
    async def get_project(
        key: CaseOwnerKeyArg, include_archived_areas: IncludeArchivedAreasArg = False
    ) -> ProjectView:
        """Returns one project by its key: key, title, description, current attribute
        values, the project decisions and findings in force by address and title, its
        areas and the index of the project's case. Decisions and findings stay out
        of that index; `index_omitted` counts them by type. An area address returns
        the area in the same shape: its own decisions and findings in force, superseded
        the way a project's are, and an empty list of areas.

        The keys of the installation's projects are listed by `list_projects`.
        """
        async with runtime.call() as (session, actor):
            found = await areas_service.get_owner(session, key)
            attributes = await attributes_service.list_attributes(session, found, actor=actor)
            knowledge = await decisions_service.case_knowledge(session, found, actor=actor)
            areas = (
                []
                if isinstance(found, Area)
                else await areas_service.list_areas(
                    session, found, actor=actor, include_archived=include_archived_areas
                )
            )
            index = await case_service.project_case_index(session, found, actor=actor)
            return project(found, attributes, knowledge, areas, index)
