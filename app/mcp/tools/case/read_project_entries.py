"""Инструмент `read_project_entries`: тела записей дела проекта по номерам, типам,
имени атрибута и «после»."""

from app.mcp.arguments import CursorArg, LimitArg, ProjectKeyArg
from app.mcp.tools.case.arguments import AfterNoArg, AttributeArg, EntryNosArg, EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import case as case_service
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `read_project_entries` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def read_project_entries(
        key: ProjectKeyArg,
        nos: EntryNosArg = None,
        types: EntryTypesArg = None,
        attribute: AttributeArg = None,
        after_no: AfterNoArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[EntryView]:
        """Returns the bodies of a project's case entries, payload included, ordered by
        entry number.

        The project's case holds decisions, findings, artifacts and notes about the
        project, and the tracker's own entries about its card. Filters combine with
        `and`, as in `read_entries`. `attribute` gives one attribute's history:
        `attribute_created`, `attribute_changed`, `attribute_removed` entries with that
        name. The case index, titles only, comes with `get_project`.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)
            listed = await case_service.list_project_entries(
                session,
                project,
                actor=actor,
                nos=nos,
                types=types,
                attribute=attribute,
                after_no=after_no,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (entry(item, project_key=project.key) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
