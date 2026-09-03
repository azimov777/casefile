"""Вставки и выборки по записям дела.

Методов правки и удаления здесь нет и не будет: записи неизменяемы
(`CONCEPT.md`, 3.4). Ошибочная запись исправляется следующей записью.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.task import Task
from app.db.pagination import (
    Page,
    decode_sort_cursor,
    encode_sort_cursor,
    resolve_limit,
)
from app.domain.authors import Author
from app.domain.case import FIRST_ENTRY_NUMBER, EntryHeading


class EntryRepository:
    """Доступ к таблице `entries`: добавить и прочитать."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allocate_no(self, task_id: uuid.UUID) -> int:
        """Следующий номер записи в задаче — без дыр и без гонок.

        Сначала блокируется строка задачи (`SELECT ... FOR UPDATE`), потом считается
        `max(no) + 1`. Блокировка держится до конца транзакции, поэтому две
        параллельные записи в одну задачу получают разные номера: вторая ждёт коммита
        первой и уже видит её строку. Откатившаяся транзакция ничего не вставила и
        номер не теряет — в отличие от счётчика на задаче, который оставил бы дыру.

        Цена — сериализация записей **в одну задачу** до конца транзакции. Для дела это
        и есть нужное свойство: страницы подшиваются по одной.
        """
        lock = select(Task.id).where(Task.id == task_id).with_for_update()
        if await self._session.scalar(lock) is None:
            # Строка исчезнуть не может — задачи не удаляются, — но молчаливый `None`
            # превратился бы в запись без задачи.
            raise RuntimeError(f"Task {task_id} disappeared while allocating an entry number")
        highest = select(func.coalesce(func.max(Entry.no), FIRST_ENTRY_NUMBER - 1)).where(
            Entry.task_id == task_id
        )
        return int(await self._session.scalar(highest)) + 1

    async def add(self, entry: Entry) -> Entry:
        """Отправляет INSERT. Номер `no` вызывающий берёт у `allocate_no` заранее.

        Две функции, а не одна с побочным эффектом: номер — часть содержимого записи,
        и его выдача не должна прятаться внутри «добавить».
        """
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def list_page(
        self,
        task_id: uuid.UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Entry]:
        """Страница записей задачи в порядке `no`.

        Порядок — номер в задаче, а не `(created_at, id)` общей пагинации: записи одной
        транзакции получают одно `created_at`, и только `no` даёт тот порядок, в котором
        их подшивали. Курсор — общий `encode_sort_cursor` из модуля пагинации: свой
        разбор курсора здесь запрещён правилом «одна реализация пагинации».
        """
        size = resolve_limit(limit)
        statement = select(Entry).where(Entry.task_id == task_id)
        if cursor is not None:
            (after_no,), _ = decode_sort_cursor(cursor, arity=1)
            statement = statement.where(Entry.no > after_no)
        statement = statement.order_by(Entry.no).limit(size + 1)
        rows = list(await self._session.scalars(statement))
        if len(rows) <= size:
            return Page(items=rows, next_cursor=None)
        page = rows[:size]
        last = page[-1]
        return Page(items=page, next_cursor=encode_sort_cursor([last.no], last.id))

    async def headings(self, task_id: uuid.UUID) -> list[EntryHeading]:
        """Опись дела: заголовки всех записей задачи, без тел и без нагрузки.

        Выбираются только нужные колонки: тела записей бывают длинными, а опись
        входит в каждый пакет преемника и обязана оставаться дешёвой.
        """
        statement = (
            select(
                Entry.no,
                Entry.type,
                Entry.created_by_kind,
                Entry.created_by_signature,
                Entry.created_at,
                Entry.title,
            )
            .where(Entry.task_id == task_id)
            .order_by(Entry.no)
        )
        rows: list[Any] = list(await self._session.execute(statement))
        return [
            EntryHeading(
                no=row.no,
                type=row.type,
                author=Author(kind=row.created_by_kind, signature=row.created_by_signature),
                created_at=row.created_at,
                title=row.title,
            )
            for row in rows
        ]
