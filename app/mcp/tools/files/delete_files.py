"""Инструмент `delete_files`: стереть все файлы под отбор, подтвердив их число."""

from typing import Annotated

from pydantic import Field

from app.mcp.tools.files.list_files import ProjectFilterArg, QueryArg, TypeFilterArg
from app.mcp.toolset import DESTRUCTIVE, Toolset
from app.mcp.views import AttachedFileView, attached_file
from app.services import files as files_service

ExpectedCountArg = Annotated[
    int,
    Field(
        ge=0,
        description=(
            "How many files the filter matches, as `list_files` with the same filter shows; "
            "any other number is refused with `file_count_mismatch` and nothing is deleted"
        ),
    ),
]
UnopenedOnlyArg = Annotated[
    bool, Field(description="Only images with the `unopened` mark (not opened for the term)")
]


def register(tools: Toolset) -> None:
    """Объявляет `delete_files`."""
    runtime = tools.runtime

    @tools.tool(title="Delete files", annotations=DESTRUCTIVE)
    async def delete_files(
        expected_count: ExpectedCountArg,
        project: ProjectFilterArg = None,
        query: QueryArg = None,
        mime_type: TypeFilterArg = None,
        unopened: UnopenedOnlyArg = False,
    ) -> list[AttachedFileView]:
        """Erases the bytes of every live file the filter picks and keeps their tombstones.
        Without a filter that is every file of the installation. Count the picked files
        with `list_files` first: the call deletes only when `expected_count` equals them.
        """
        async with runtime.call() as (session, actor):
            cards = await files_service.delete_matching(
                session,
                actor=actor,
                expected_count=expected_count,
                project=project,
                query=query,
                mime_type=mime_type,
                unopened=unopened,
            )
            return [attached_file(card) for card in cards]
