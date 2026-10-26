"""Инструмент `request_file_upload`: одноразовая ссылка на загрузку нового файла в проект."""

import mimetypes

from app.mcp.arguments import ProjectKeyArg
from app.mcp.file_links import LinkKind, link_url
from app.mcp.tools.files.arguments import FileMimeTypeArg, FileNameArg
from app.mcp.tools.files.views import FileLinkView, upload_link
from app.mcp.toolset import FILING, Toolset
from app.services import files as files_service
from app.services import projects as projects_service


def register(tools: Toolset) -> None:
    """Объявляет `request_file_upload`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="Request file upload link", annotations=FILING)
    async def request_file_upload(
        project: ProjectKeyArg,
        name: FileNameArg,
        mime_type: FileMimeTypeArg = None,
    ) -> FileLinkView:
        """Returns a one-time link and the `curl -T` command that uploads a new file to a
        project; the bytes travel from disk to the tracker and never through the model.

        The link opens one upload within ten minutes and is spent by the first request,
        whether it succeeds or not. The upload answers with the file `id`, which an entry
        attaches through its `files` argument. A file larger than `max_bytes` is refused
        with `file_too_large`; an archived project with `project_archived`.
        """
        async with runtime.call() as (session, actor):
            await projects_service.get_project(session, project)
            clean_name, clean_type = files_service.validate_name_and_type(
                name, mime_type or mimetypes.guess_type(name)[0]
            )
            link = tools.links.issue(
                LinkKind.UPLOAD,
                actor,
                project=project,
                name=clean_name,
                mime_type=clean_type,
            )
            return upload_link(
                link,
                link_url(settings, link),
                max_bytes=await files_service.file_size_limit(session, settings),
            )
