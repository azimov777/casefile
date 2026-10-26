"""Инструмент `list_files`: файлы установки с поиском по имени, отбором и сортировкой."""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.files import FileSort
from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.tools.files.views import FileCardView, file_card
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import files as files_service

ProjectFilterArg = Annotated[
    str | None,
    Field(
        description=(
            "Only this project's files; an archived project's only when named here. An "
            "unknown key is refused with `project_not_found`"
        )
    ),
]
QueryArg = Annotated[str | None, Field(description="Only names containing this text, any case")]
TypeFilterArg = Annotated[
    str | None,
    Field(description="Only this media type, or a family: `image/png`, `image` or `image/*`"),
]
UnopenedArg = Annotated[
    bool,
    Field(description="Only images not opened for the installation's term of days (`unopened`)"),
]
SortArg = Annotated[
    Literal["added", "opened", "size", "type"],
    Field(
        description=(
            "Order by the time added, the time last opened (never opened: the time added), "
            "size or media type"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `list_files`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="List files", annotations=READ_ONLY)
    async def list_files(
        project: ProjectFilterArg = None,
        query: QueryArg = None,
        mime_type: TypeFilterArg = None,
        sort: SortArg = "added",
        descending: bool = True,
        include_deleted: bool = False,
        unopened: UnopenedArg = False,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[FileCardView]:
        """Lists the installation's files as cards, without bytes. Tombstones of deleted
        files are left out unless `include_deleted` is set. Listing does not mark a file
        as opened. An image not opened for the installation's term of days carries `unopened`
        and is picked by the `unopened` argument; a person or an agent may delete it, the
        tracker never does.
        """
        async with runtime.call() as (session, actor):
            listed = await files_service.list_files(
                session,
                actor=actor,
                project=project,
                query=query,
                mime_type=mime_type,
                sort=FileSort(sort),
                descending=descending,
                include_deleted=include_deleted,
                unopened=unopened,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page((file_card(item) for item in listed.items), next_cursor=listed.next_cursor)
