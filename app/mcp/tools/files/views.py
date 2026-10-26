"""Формы ответов инструментов файлов: карточка файла и выданная ссылка."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

from app.domain.files import FileCard
from app.mcp.file_links import FileLink
from app.mcp.views import AttachedFileView, attached_file, signature


class FileCardView(AttachedFileView):
    """File card with its history. `entries` counts the entries that attach the file,
    `tasks` the distinct tasks among them."""

    sha256: str
    project: str
    added_by: str | None
    added_at: datetime
    replaced_at: datetime | None = None
    last_opened_at: datetime | None = None
    deleted_by: str | None = None
    entries: int
    tasks: int

    @model_serializer(mode="wrap")
    def _tombstone_only_when_deleted(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Убирает отметки, которых не было: не заменяли, не открывали, не удаляли."""
        dumped: dict[str, Any] = handler(self)
        for name in ("replaced_at", "last_opened_at", "deleted_by", "deleted_at"):
            if dumped.get(name) is None:
                dumped.pop(name, None)
        return dumped


def file_card(card: FileCard) -> FileCardView:
    """Карточка файла: живого или надгробия."""
    return FileCardView(
        **attached_file(card).model_dump(),
        sha256=card.sha256,
        project=card.project_key,
        added_by=signature(card.added_by),
        added_at=card.added_at,
        replaced_at=card.replaced_at,
        last_opened_at=card.last_opened_at,
        deleted_by=signature(card.deleted_by),
        entries=card.entries,
        tasks=card.tasks,
    )


class FileLinkView(BaseModel):
    """One-time link and the shell `command` that uses it, with `<path>` for a local path;
    `max_bytes` is the largest file an upload link takes."""

    url: str
    command: str
    expires_at: datetime
    max_bytes: int | None = None

    @model_serializer(mode="wrap")
    def _limit_only_on_upload(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        dumped: dict[str, Any] = handler(self)
        if self.max_bytes is None:
            dumped.pop("max_bytes", None)
        return dumped


def upload_link(link: FileLink, url: str, *, max_bytes: int) -> FileLinkView:
    """Ссылка на загрузку или замену: команда `curl -T`."""
    return FileLinkView(
        url=url,
        command=f"curl --fail-with-body -T <path> '{url}'",
        expires_at=link.expires_at,
        max_bytes=max_bytes,
    )


def download_link(link: FileLink, url: str) -> FileLinkView:
    """Ссылка на скачивание: команда `curl -o`."""
    return FileLinkView(
        url=url,
        command=f"curl --fail-with-body -o <path> '{url}'",
        expires_at=link.expires_at,
    )
