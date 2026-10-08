"""Инструмент `read_project_entries`: тела записей дела проекта, области или обсуждения по
номерам, типам, имени атрибута, статусу, подстроке и «после»."""

from typing import Annotated

from pydantic import Field

from app.db.models.area import Area
from app.domain.discussions import is_discussion_address
from app.mcp.arguments import CaseAddressArg, CursorArg, LimitArg
from app.mcp.tools.case.arguments import AfterNoArg, AttributeArg, EntryNosArg, EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import discussions as discussions_service

InForceArg = Annotated[
    bool | None,
    Field(
        description=(
            "`true`: only the decisions and findings in force; `false`: only the superseded "
            "ones. Entries without a status — other types and every entry of a "
            "discussion's case — match neither"
        )
    ),
]

# `min_length` здесь, вопреки правилу `app/mcp/arguments.py` «границы — домену»: пустая
# подстрока входит в любой текст, и отбор молча стал бы «всё дело». Тот же порог у `text`
# поиска задач в REST (`app/api/schemas/search.py`) и у `text` чтения дела в REST.
EntryTextArg = Annotated[
    str | None,
    Field(
        min_length=1,
        description="Only entries whose title or body contains this substring, ignoring case",
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `read_project_entries`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="Read project entries", annotations=READ_ONLY)
    async def read_project_entries(
        key: CaseAddressArg,
        nos: EntryNosArg = None,
        types: EntryTypesArg = None,
        attribute: AttributeArg = None,
        text: EntryTextArg = None,
        in_force: InForceArg = None,
        after_no: AfterNoArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[EntryView]:
        """Returns the entry bodies of a project's, area's or discussion's case, payload
        included, ordered by entry number.

        A project's or area's case holds decisions, findings, artifacts and notes about
        its owner, and the tracker's own entries about its card; a discussion's case
        holds its questions, answers, notes, conclusions and the tracker's entries on
        attaching, detaching and closing. Filters combine with
        `and`, as in `read_entries`. `attribute` gives one attribute's history:
        `attribute_created`, `attribute_changed`, `attribute_removed` entries with that
        name; `text` finds a substring in titles and bodies. Titles come with
        `get_project`: the case index, and for a project its decisions and findings in
        force, which that index leaves out.

        Decisions and findings of a project's or an area's case carry `status` and
        `superseded_by` on every read, numbers included; `superseded_by` is the direct
        successor's number.
        """
        async with runtime.call() as (session, actor):
            if is_discussion_address(key):
                discussion = await discussions_service.get_discussion(session, key)
                found = await case_service.list_discussion_entries(
                    session,
                    discussion,
                    actor=actor,
                    nos=nos,
                    types=types,
                    attribute=attribute,
                    text=text,
                    in_force=in_force,
                    after_no=after_no,
                    limit=limit or settings.mcp_page_size,
                    cursor=cursor,
                )
                return page(
                    (entry(item, discussion=discussion.address) for item in found.items),
                    next_cursor=found.next_cursor,
                )
            owner = await areas_service.get_owner(session, key)
            listed = await case_service.list_project_entries(
                session,
                owner,
                actor=actor,
                nos=nos,
                types=types,
                attribute=attribute,
                text=text,
                in_force=in_force,
                after_no=after_no,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (
                    entry(item, area=owner.address, standing=listed.standings.get(item.no))
                    if isinstance(owner, Area)
                    else entry(item, project_key=owner.key, standing=listed.standings.get(item.no))
                    for item in listed.items
                ),
                next_cursor=listed.next_cursor,
            )
