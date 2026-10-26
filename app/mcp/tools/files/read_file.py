"""Инструмент `read_file`: изображение — содержимым `image`, документ — карточкой и ссылкой."""

from datetime import datetime
from typing import Any

import pydantic_core
from mcp.server.mcpserver import Image
from mcp_types import CallToolResult, TextContent
from pydantic import SerializerFunctionWrapHandler, model_serializer

from app.domain.files import FileCard
from app.mcp.file_links import LinkKind, link_url
from app.mcp.tools.files.arguments import FileIdArg, file_id
from app.mcp.tools.files.views import FileLinkView, download_link
from app.mcp.toolset import READ_MARKING, Toolset
from app.mcp.views import AttachedFileView, attached_file
from app.services import files as files_service

#: Изображения, которые модель видит содержимым `image`.
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}

#: Самое большое изображение, которое отдаётся содержимым: выше предела изображения у
#: моделей (5 МБ в API Claude). Больше — карточка и ссылка, как у документа.
MAX_IMAGE_CONTENT_BYTES = 5 * 1024 * 1024


class FileReadView(AttachedFileView):
    """File card; a file not shown as an image also carries the one-time download `url`,
    its `command` and `expires_at`."""

    sha256: str
    url: str | None = None
    command: str | None = None
    expires_at: datetime | None = None

    @model_serializer(mode="wrap")
    def _link_only_when_given(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        dumped: dict[str, Any] = handler(self)
        for name in ("deleted_at", "url", "command", "expires_at"):
            if dumped.get(name) is None:
                dumped.pop(name, None)
        return dumped


def _view(card: FileCard, link: FileLinkView | None = None) -> FileReadView:
    """Карточка выданного файла; ссылка, если она выдана, лежит в тех же полях."""
    return FileReadView(
        **attached_file(card).model_dump(),
        sha256=card.sha256,
        url=None if link is None else link.url,
        command=None if link is None else link.command,
        expires_at=None if link is None else link.expires_at,
    )


def register(tools: Toolset) -> None:
    """Объявляет `read_file`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="Read file", annotations=READ_MARKING)
    async def read_file(file: FileIdArg) -> FileReadView:
        """Returns a file. A PNG, JPEG, GIF or WebP image up to 5 MB comes as `image`
        content that the model sees as a picture, after its card. Any other file comes as
        its card and a one-time link with the `curl -o` command; its bytes never pass
        through the model.

        Giving out an image marks the file as opened; a card with a link does not, the
        download does. A deleted file returns its tombstone card.
        """
        async with runtime.call() as (session, actor):
            identifier = file_id(file)
            card = await files_service.read_file(session, identifier, actor=actor)
            if card.deleted:
                return _result(_view(card))
            if card.mime_type in IMAGE_TYPES and card.size_bytes <= MAX_IMAGE_CONTENT_BYTES:
                opened = await files_service.open_file(session, identifier, actor=actor)
                return _result(
                    _view(opened.card),
                    Image(data=opened.data, format=IMAGE_TYPES[card.mime_type]),
                )
            link = tools.links.issue(LinkKind.DOWNLOAD, actor, file_id=identifier)
            return _result(_view(card, download_link(link, link_url(settings, link))))


def _result(view: FileReadView, image: Image | None = None) -> Any:
    """Результат вызова: карточка текстом и структурой, затем изображение, если оно есть.

    Возвращается готовый `CallToolResult`, а не список блоков: у инструмента объявлена форма
    ответа (`outputSchema`), и структурный ответ идёт рядом с картинкой. Кодирование
    изображения для провода делает SDK (`Image.to_image_content`), своего кода кодирования
    у слоя MCP нет.
    """
    content: list[Any] = [
        TextContent(type="text", text=pydantic_core.to_json(view, exclude_none=True).decode())
    ]
    if image is not None:
        content.append(image.to_image_content())
    return CallToolResult(
        content=content,
        structured_content=pydantic_core.to_jsonable_python(view, exclude_none=True),
    )
