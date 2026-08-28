"""Выборки и изменения по сохранённым фильтрам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.saved_filter import SavedFilter
from app.db.pagination import Page, paginate


class SavedFilterRepository:
    """Доступ к таблице `saved_filters`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, filter_id: uuid.UUID) -> SavedFilter | None:
        return await self._session.get(SavedFilter, filter_id)

    async def get_by_name(self, owner_id: uuid.UUID, name: str) -> SavedFilter | None:
        """Фильтр владельца по имени: имя уникально у владельца, а не на установку."""
        statement = select(SavedFilter).where(
            SavedFilter.owner_id == owner_id,
            SavedFilter.name == name,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[SavedFilter]:
        """Страница фильтров: без владельца — все, с владельцем — только его.

        Отбор по владельцу необязателен намеренно: в v1 ролей нет, фильтры общие, и
        список всех — это способ найти чужой полезный фильтр, а не утечка.
        """
        statement = select(SavedFilter)
        if owner_id is not None:
            statement = statement.where(SavedFilter.owner_id == owner_id)
        return await paginate(self._session, statement, SavedFilter, limit=limit, cursor=cursor)

    async def add(self, saved_filter: SavedFilter) -> SavedFilter:
        self._session.add(saved_filter)
        await self._session.flush()
        return saved_filter

    async def delete(self, saved_filter: SavedFilter) -> None:
        await self._session.delete(saved_filter)
        await self._session.flush()

    async def flush(self) -> None:
        """Фиксирует правку объекта в базе, не закрывая транзакцию."""
        await self._session.flush()
