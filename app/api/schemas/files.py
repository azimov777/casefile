"""Схемы файлов: карточка, список, тела удаления.

Карточка одна на весь API: так же файл приходит в записи дела (`files` у записи) и в
выдаче `/files`. У удалённого файла — надгробие: `deleted` равно `true`, `deleted_by` и
`deleted_at` назвали, а имя, тип, размер и `sha256` остались те, что были.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.authors import AuthorRead
from app.domain.files import FileCard

#: Сколько файлов можно назвать одним запросом удаления выбранных.
MAX_DELETE_SELECTION = 1000


class FileRead(BaseModel):
    """Карточка файла без байтов — живого или надгробие."""

    id: uuid.UUID = Field(description="File reference: stays the same when the file is replaced")
    project_key: str = Field(examples=["TRK"])
    name: str = Field(examples=["scheme.png"])
    mime_type: str = Field(examples=["image/png"])
    size_bytes: int = Field(examples=[48213], description="Size of the content at the last upload")
    sha256: str = Field(description="SHA-256 of the content, 64 hexadecimal characters")
    added_by: AuthorRead
    added_at: datetime
    replaced_by: AuthorRead | None = Field(
        default=None, description="Who replaced the content last; null if never replaced"
    )
    replaced_at: datetime | None = None
    last_opened_at: datetime | None = Field(
        default=None, description="When the bytes were last served; null if never opened"
    )
    deleted: bool = Field(description="True for a tombstone: the bytes are gone")
    deleted_by: AuthorRead | None = None
    deleted_at: datetime | None = None
    unopened: bool = Field(
        description=(
            "Image (PNG, JPEG, GIF, WebP) not opened for the installation's "
            "`file_unopened_days` days, counted from the last opening or, if never opened, "
            "from adding. Computed on reading, stored nowhere; documents and tombstones "
            "never have it. The tracker deletes nothing by itself"
        )
    )
    entries: int = Field(description="Case entries that attach the file")
    tasks: int = Field(description="Distinct tasks among those entries")


def file_read(card: FileCard) -> FileRead:
    """Карточка домена в схему ответа."""
    return FileRead(
        id=card.id,
        project_key=card.project_key,
        name=card.name,
        mime_type=card.mime_type,
        size_bytes=card.size_bytes,
        sha256=card.sha256,
        added_by=AuthorRead.model_validate(card.added_by),
        added_at=card.added_at,
        replaced_by=None
        if card.replaced_by is None
        else AuthorRead.model_validate(card.replaced_by),
        replaced_at=card.replaced_at,
        last_opened_at=card.last_opened_at,
        deleted=card.deleted,
        deleted_by=None if card.deleted_by is None else AuthorRead.model_validate(card.deleted_by),
        deleted_at=card.deleted_at,
        unopened=card.unopened,
        entries=card.entries,
        tasks=card.tasks,
    )


class FileUpload(BaseModel):
    """Части формы `POST /files`: `multipart/form-data`. Лишняя часть — отказ."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    project: str = Field(description="Key of the project the file belongs to", examples=["TRK"])
    file: UploadFile = Field(
        description="The file itself. Its `filename` and `Content-Type` name the file and its type"
    )
    name: str | None = Field(
        default=None, description="Name of the file; without it the `filename` of the part is used"
    )


class FileReplacement(BaseModel):
    """Части формы `PUT /files/{id}/content`: `multipart/form-data`."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    file: UploadFile = Field(
        description="The new content. Its `Content-Type` becomes the type of the file"
    )
    name: str | None = Field(
        default=None, description="New name of the file; without it the name stays"
    )


class FileDeletion(BaseModel):
    """Удаление нескольких файлов: выбранные по номерам или все под отбор с числом.

    Ровно одно из двух: `ids` — выбранные файлы; либо `expected_count` — число файлов,
    которое человек увидел и подтвердил, вместе с отбором (`project`, `q`, `mime_type`;
    без отбора — все файлы установки). Не совпало с числом подходящих — отказ
    `file_count_mismatch`, ничего не удалено.
    """

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DELETE_SELECTION,
        description="Files picked one by one; all of them are deleted or none",
    )
    expected_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of matching files the person confirmed; with the filter below",
    )
    project: str | None = Field(default=None, examples=["TRK"], description="Filter by project")
    q: str | None = Field(default=None, description="Filter by a part of the name")
    mime_type: str | None = Field(
        default=None, examples=["image"], description="Filter by type: `image/png` or `image`"
    )
    unopened: bool | None = Field(
        default=None,
        description="True: only images not opened for `file_unopened_days` days (`unopened`)",
    )

    @model_validator(mode="after")
    def _one_way(self) -> FileDeletion:
        by_filter = any(
            value is not None
            for value in (
                self.expected_count,
                self.project,
                self.q,
                self.mime_type,
                self.unopened,
            )
        )
        if self.ids is not None and by_filter:
            raise ValueError("name either `ids` or a filter with `expected_count`, not both")
        if self.ids is None and self.expected_count is None:
            raise ValueError("name `ids` or `expected_count` with a filter")
        return self


class FilesDeleted(BaseModel):
    """Итог удаления нескольких файлов: надгробия."""

    deleted: int
    files: list[FileRead]
