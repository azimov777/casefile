"""Инструмент `read_project_entries`: тела записей дела проекта или направления по номерам,
типам, имени атрибута, статусу и «после»."""

from typing import Annotated

from pydantic import Field

from app.db.models.direction import Direction
from app.mcp.arguments import CaseOwnerKeyArg, CursorArg, LimitArg
from app.mcp.tools.case.arguments import AfterNoArg, AttributeArg, EntryNosArg, EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import case as case_service
from app.services import directions as directions_service

InForceArg = Annotated[
    bool | None,
    Field(
        description=(
            "`true`: only the decisions and findings in force; `false`: only the superseded "
            "ones. Entries without a status — other types and every entry of a direction's "
            "case — match neither"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `read_project_entries`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="Read project entries", annotations=READ_ONLY)
    async def read_project_entries(
        key: CaseOwnerKeyArg,
        nos: EntryNosArg = None,
        types: EntryTypesArg = None,
        attribute: AttributeArg = None,
        in_force: InForceArg = None,
        after_no: AfterNoArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[EntryView]:
        """Returns the entry bodies of a project's or direction's case, payload included,
        ordered by entry number.

        Such a case holds decisions, findings, artifacts and notes about its owner, and
        the tracker's own entries about its card. Filters combine with
        `and`, as in `read_entries`. `attribute` gives one attribute's history:
        `attribute_created`, `attribute_changed`, `attribute_removed` entries with that
        name. The case index, titles only, comes with `get_project`.

        Decisions and findings of a project's case carry `status` and `superseded_by` on
        every read, numbers included; `superseded_by` is the direct successor's number.
        Entries of a direction's case have none.
        """
        async with runtime.call() as (session, actor):
            owner = await directions_service.get_owner(session, key)
            listed = await case_service.list_project_entries(
                session,
                owner,
                actor=actor,
                nos=nos,
                types=types,
                attribute=attribute,
                in_force=in_force,
                after_no=after_no,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (
                    entry(item, direction=owner.address)
                    if isinstance(owner, Direction)
                    else entry(item, project_key=owner.key, standing=listed.standings.get(item.no))
                    for item in listed.items
                ),
                next_cursor=listed.next_cursor,
            )
