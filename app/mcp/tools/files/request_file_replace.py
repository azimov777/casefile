"""Инструмент `request_file_replace`: одноразовая ссылка на замену содержимого файла."""

from app.domain.errors import FileDeletedError
from app.mcp.file_links import LinkKind, link_url
from app.mcp.tools.files.arguments import FileIdArg, FileMimeTypeArg, FileNameOrNoneArg, file_id
from app.mcp.tools.files.views import FileLinkView, upload_link
from app.mcp.toolset import FILING, Toolset
from app.services import files as files_service


def register(tools: Toolset) -> None:
    """Объявляет `request_file_replace`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="Request file replacement link", annotations=FILING)
    async def request_file_replace(
        file: FileIdArg,
        name: FileNameOrNoneArg = None,
        mime_type: FileMimeTypeArg = None,
    ) -> FileLinkView:
        """Swaps the content of an existing file under the same id: returns a single-use
        upload address with a ready `command` for a local path.

        The upload erases the previous bytes; no earlier version is kept, and every entry
        that attaches the file shows the new content. `name` and `mime_type` change only
        when given. A deleted file is refused with `file_deleted`, an archived project's
        with `project_archived`; the link follows the rules of `request_file_upload`.
        """
        async with runtime.call() as (session, actor):
            identifier = file_id(file)
            card = await files_service.read_file(session, identifier, actor=actor)
            if card.deleted:
                raise FileDeletedError(details={"id": str(card.id), "name": card.name})
            if name is not None or mime_type is not None:
                name, mime_type = files_service.validate_name_and_type(
                    card.name if name is None else name, mime_type
                )
            link = tools.links.issue(
                LinkKind.REPLACE, actor, file_id=identifier, name=name, mime_type=mime_type
            )
            return upload_link(
                link,
                link_url(settings, link),
                max_bytes=await files_service.file_size_limit(session, settings),
            )
