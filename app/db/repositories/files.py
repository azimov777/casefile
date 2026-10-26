"""Выборки и вставки по файлам, их байтам и вложениям записей дела.

Байты читаются и пишутся только здесь и только по явному запросу (`content`,
`set_content`): карточка, список и подсчёт ссылок до таблицы `file_contents` не доходят.
"""

import uuid
from collections.abc import Collection, Sequence
from typing import Any

from sqlalchemy import Select, delete, distinct, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.entry import Entry
from app.db.models.file import EntryFile, File, FileContent
from app.db.models.project import Project
from app.db.pagination import (
    Page,
    decode_sort_cursor,
    encode_sort_cursor,
    resolve_limit,
)
from app.db.repositories.projects import in_active_project
from app.db.sql import LIKE_ESCAPE, ilike_contains
from app.domain.files import FileSort


class FileRepository:
    """Доступ к таблицам `files`, `file_contents` и `entry_files`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, file_id: uuid.UUID, *, for_update: bool = False) -> File | None:
        statement = select(File).where(File.id == file_id)
        if for_update:
            # Объект перечитывается под блокировкой: карта сессии могла держать старое.
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return (await self._session.scalars(statement)).one_or_none()

    async def get_many(self, file_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, File]:
        if not file_ids:
            return {}
        statement = select(File).where(File.id.in_(file_ids))
        return {file.id: file for file in await self._session.scalars(statement)}

    async def project_keys(self, project_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Ключи проектов одним запросом: идентификатор → ключ."""
        if not project_ids:
            return {}
        rows = await self._session.execute(
            select(Project.id, Project.key).where(Project.id.in_(project_ids))
        )
        return dict(rows.tuples().all())

    async def add(self, file: File, data: bytes) -> File:
        self._session.add(file)
        await self._session.flush()
        self._session.add(FileContent(file_id=file.id, data=data))
        await self._session.flush()
        return file

    async def content(self, file_id: uuid.UUID) -> bytes | None:
        """Байты файла; `None` у надгробия."""
        return await self._session.scalar(
            select(FileContent.data).where(FileContent.file_id == file_id)
        )

    async def set_content(self, file_id: uuid.UUID, data: bytes) -> None:
        """Кладёт новые байты на место прежних. Прежние не хранятся."""
        row = (
            await self._session.scalars(
                select(FileContent)
                .where(FileContent.file_id == file_id)
                .execution_options(populate_existing=True)
            )
        ).one()
        row.data = data
        await self._session.flush()

    async def erase_content(self, file_id: uuid.UUID) -> None:
        """Стирает строку с байтами: от файла остаётся надгробие."""
        await self._session.execute(delete(FileContent).where(FileContent.file_id == file_id))

    async def reference_counts(
        self, file_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """Сколько записей и различных задач ссылаются на файлы: id → (записи, задачи)."""
        if not file_ids:
            return {}
        statement = (
            select(
                EntryFile.file_id,
                func.count(distinct(EntryFile.entry_id)),
                func.count(distinct(Entry.task_id)),
            )
            .join(Entry, Entry.id == EntryFile.entry_id)
            .where(EntryFile.file_id.in_(file_ids))
            .group_by(EntryFile.file_id)
        )
        return {
            file_id: (entries, tasks)
            for file_id, entries, tasks in await self._session.execute(statement)
        }

    async def add_attachments(self, entry_id: uuid.UUID, file_ids: Sequence[uuid.UUID]) -> None:
        for position, file_id in enumerate(file_ids, start=1):
            self._session.add(EntryFile(entry_id=entry_id, file_id=file_id, position=position))
        await self._session.flush()

    async def attachments(
        self, entry_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """Файлы записей в порядке вложения: запись → идентификаторы файлов."""
        if not entry_ids:
            return {}
        rows = await self._session.execute(
            select(EntryFile.entry_id, EntryFile.file_id)
            .where(EntryFile.entry_id.in_(entry_ids))
            .order_by(EntryFile.entry_id, EntryFile.position)
        )
        grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
        for entry_id, file_id in rows:
            grouped.setdefault(entry_id, []).append(file_id)
        return grouped

    async def matching(
        self,
        *,
        project_id: uuid.UUID | None,
        query: str | None,
        mime_type: str | None,
    ) -> list[File]:
        """Все живые файлы под отбор списка, без страниц: для удаления по отбору.

        Условия те же, что у `list_page` (без проекта — архивные скрыты, TRK#99); надгробия
        не входят: удалять в них нечего. Порядок по `id` — один и тот же при каждом вызове.
        """
        statement: Select[Any] = select(File).where(File.deleted_at.is_(None))
        if project_id is not None:
            statement = statement.where(File.project_id == project_id)
        else:
            statement = statement.where(in_active_project(File.project_id))
        if query:
            statement = statement.where(ilike_contains(File.name, query))
        if mime_type:
            statement = statement.where(_mime_condition(mime_type))
        return list(await self._session.scalars(statement.order_by(File.id)))

    async def list_page(
        self,
        *,
        project_id: uuid.UUID | None,
        query: str | None,
        mime_type: str | None,
        sort: FileSort,
        descending: bool,
        include_deleted: bool,
        limit: int | None,
        cursor: str | None,
    ) -> Page[File]:
        """Страница файлов.

        Без `project_id` файлы архивных проектов скрыты (TRK#99): их видно, только когда
        проект назван. Ключ порядка один, тайбрейкер — `id` в том же направлении; для
        «последнего открытия» файл, который не открывали, ставится по дате добавления
        (`coalesce`), чтобы ключ не был пустым и курсор не ломался на границе.
        """
        size = resolve_limit(limit)
        key = _sort_expression(sort)
        statement: Select[Any] = select(File, key)
        if project_id is not None:
            statement = statement.where(File.project_id == project_id)
        else:
            statement = statement.where(in_active_project(File.project_id))
        if not include_deleted:
            statement = statement.where(File.deleted_at.is_(None))
        if query:
            statement = statement.where(ilike_contains(File.name, query))
        if mime_type:
            statement = statement.where(_mime_condition(mime_type))
        order = (key.desc(), File.id.desc()) if descending else (key.asc(), File.id.asc())
        if cursor is not None:
            values, item_id = decode_sort_cursor(cursor, arity=1)
            after = tuple_(key, File.id)
            marker = (values[0], item_id)
            statement = statement.where(after < marker if descending else after > marker)
        rows = list(await self._session.execute(statement.order_by(*order).limit(size + 1)))
        page = rows[:size]
        items = [row[0] for row in page]
        if len(rows) <= size:
            return Page(items=items, next_cursor=None)
        last = page[-1]
        return Page(items=items, next_cursor=encode_sort_cursor([last[1]], last[0].id))


def _sort_expression(sort: FileSort) -> ColumnElement[Any]:
    match sort:
        case FileSort.ADDED:
            return File.created_at
        case FileSort.OPENED:
            return func.coalesce(File.last_opened_at, File.created_at)
        case FileSort.SIZE:
            return File.size_bytes
        case FileSort.TYPE:
            return File.mime_type


def _mime_condition(value: str) -> ColumnElement[bool]:
    """Отбор по типу: `image/png` — точно; `image` или `image/*` — всё семейство."""
    wanted = value.strip().lower()
    if "/" in wanted and not wanted.endswith("/*"):
        return File.mime_type == wanted
    family = wanted.removesuffix("/*")
    escaped = (
        family.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )
    return File.mime_type.like(f"{escaped}/%", escape=LIKE_ESCAPE)
