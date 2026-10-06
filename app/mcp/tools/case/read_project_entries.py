"""Инструмент `read_project_entries`: тела записей дела проекта или направления по номерам,
типам, имени атрибута и «после»."""

from app.db.models.direction import Direction
from app.mcp.arguments import CaseOwnerKeyArg, CursorArg, LimitArg
from app.mcp.tools.case.arguments import AfterNoArg, AttributeArg, EntryNosArg, EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import case as case_service
from app.services import directions as directions_service


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
                after_no=after_no,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (
                    entry(item, direction=owner.address)
                    if isinstance(owner, Direction)
                    else entry(item, project_key=owner.key)
                    for item in listed.items
                ),
                next_cursor=listed.next_cursor,
            )
