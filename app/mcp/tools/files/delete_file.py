"""Инструмент `delete_file`: стереть байты файла и оставить надгробие."""

from app.mcp.tools.files.arguments import FileIdArg, file_id
from app.mcp.toolset import DESTRUCTIVE, Toolset
from app.mcp.views import AttachedFileView, attached_file
from app.services import files as files_service


def register(tools: Toolset) -> None:
    """Объявляет `delete_file`."""
    runtime = tools.runtime

    @tools.tool(title="Delete file", annotations=DESTRUCTIVE)
    async def delete_file(file: FileIdArg) -> AttachedFileView:
        """Erases the bytes of a file and keeps its tombstone: name, type, size, `sha256`,
        who deleted it and when. Entries that attach the file show the tombstone.

        A deleted file cannot be read, replaced or attached to a new entry; deleting it
        again is refused with `file_deleted`. An archived project's file is refused with
        `project_archived`.
        """
        async with runtime.call() as (session, actor):
            card = await files_service.delete_file(session, file_id(file), actor=actor)
            return attached_file(card)
