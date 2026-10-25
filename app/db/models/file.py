"""Файл установки: карточка с историей, байты отдельной таблицей, вложения записей дела.

Решение владельца TRK~8#4 и его итог TRK~8#5. Три таблицы.

## `files` — карточка

Один проект (`project_id`), имя, тип MIME, размер, sha256 и четыре отметки. Кто и когда
добавил — `created_by_*` и `created_at` (общая примесь автора, как у любой строки с
автором). Кто и когда последний раз заменил содержимое — `replaced_by_*`, `replaced_at`;
когда последний раз открыт — `last_opened_at` (ставит сценарий выдачи байтов; срока
жизни изображений здесь нет, это отдельная задача). Кто и когда удалил — `deleted_by_*`,
`deleted_at`: непустая отметка и есть надгробие. Истории замен нет: прежние байты не
хранятся, а прежнее лицо файла видно по записям, которые на него ссылаются, — они всегда
показывают текущее содержимое.

## `file_contents` — байты

Отдельная таблица, строка на файл. Список и карточка файла читают `files` и байтов не
касаются; `bytea` не приезжает в память ради имени и размера. Удаление файла стирает
строку `file_contents`, а не обнуляет колонку: надгробие весит строку `files`.
Байты лежат в самой базе (Postgres `bytea`), потому что архив переноса установки
(`app/domain/archive.py`, TRK#201) везёт строки таблиц как есть: файлам не нужен ни
второй формат, ни отдельный том с правилом переноса и копии (TRK#42). Предел размера —
`TRACKER_FILE_MAX_BYTES`.

## `entry_files` — вложения

Запись дела неизменяема (TRK#127), поэтому вложения задаются только при её создании:
строки этой таблицы вставляются сразу за записью и больше не меняются. Триггер
`entries_immutable` стоит на `entries`, а не здесь, но сценарии строк не правят и не
удаляют. `position` — порядок вложений в записи. Ссылка на удалённый файл остаётся
(запись показывает «файл удалён»), поэтому каскадов нет.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.domain.authors import Author, AuthorKind
from app.domain.files import MAX_FILE_NAME_LENGTH, MAX_MIME_TYPE_LENGTH


class File(BaseModel, CreatedByMixin):
    """Карточка файла: живого или надгробия."""

    __tablename__ = "files"
    __table_args__ = (
        # Кто заменил и кто удалил — пара непустых колонок или пара пустых, как у автора.
        CheckConstraint("(replaced_at IS NULL) = (replaced_by_kind IS NULL)", name="replaced_pair"),
        CheckConstraint("(deleted_at IS NULL) = (deleted_by_kind IS NULL)", name="deleted_pair"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        # Список файлов проекта и сортировка по дате добавления, по умолчанию.
        Index("ix_files_project_id_created_at", "project_id", "created_at"),
    )

    # Без `ondelete`: проекты не удаляются, а если однажды — база откажет, и файлы
    # не исчезнут молча.
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_FILE_NAME_LENGTH), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(MAX_MIME_TYPE_LENGTH), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    replaced_by_kind: Mapped[AuthorKind | None] = mapped_column(
        string_enum(AuthorKind, name="file_replaced_by_kind", length=16), nullable=True
    )
    replaced_by_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replaced_at: Mapped[datetime | None] = mapped_column(nullable=True)

    last_opened_at: Mapped[datetime | None] = mapped_column(nullable=True)

    deleted_by_kind: Mapped[AuthorKind | None] = mapped_column(
        string_enum(AuthorKind, name="file_deleted_by_kind", length=16), nullable=True
    )
    deleted_by_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    @property
    def replaced_by(self) -> Author | None:
        """Кто последний раз заменил содержимое; `None`, пока не заменяли."""
        if self.replaced_by_kind is None:
            return None
        return Author(kind=self.replaced_by_kind, signature=self.replaced_by_signature)

    @property
    def deleted_by(self) -> Author | None:
        """Кто удалил файл; `None` у живого."""
        if self.deleted_by_kind is None:
            return None
        return Author(kind=self.deleted_by_kind, signature=self.deleted_by_signature)


class FileContent(BaseModel):
    """Байты файла. Строки нет у надгробия."""

    __tablename__ = "file_contents"

    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), unique=True, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class EntryFile(BaseModel):
    """Вложение: файл приложен к записи дела при её создании."""

    __tablename__ = "entry_files"
    __table_args__ = (
        # Файл приложен к записи один раз.
        Index("uq_entry_files_entry_id_file_id", "entry_id", "file_id", unique=True),
        # «Какие записи ссылаются на файл» — карточка файла считает по этому индексу.
        Index("ix_entry_files_file_id", "file_id"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entries.id"), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
