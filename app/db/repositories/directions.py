"""Выборки и вставки по направлениям."""

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.direction import Direction
from app.db.models.project import Project
from app.db.pagination import Page, paginate


class DirectionRepository:
    """Доступ к таблице `directions`. Проект направления приезжает тем же запросом
    (`Direction.project`, `lazy="joined"`): без его ключа у направления нет адреса."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: uuid.UUID, key: str) -> Direction | None:
        """Направление проекта по уже канонизированному ключу (нижний регистр)."""
        statement = select(Direction).where(
            Direction.project_id == project_id, Direction.key == key
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def get_by_address(self, project_key: str, key: str) -> Direction | None:
        """Направление по адресу из канонических частей — для ссылок `TRK/promotion#3`."""
        statement = (
            select(Direction)
            .join(Project, Project.id == Direction.project_id)
            .where(Project.key == project_key, Direction.key == key)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def list_for_project(
        self, project_id: uuid.UUID, *, include_archived: bool = False
    ) -> list[Direction]:
        """Все направления проекта по ключу; архивные — только если их просили.

        Целиком, а не страницей: список едет в чтении проекта (`get_project`), а
        направлений у проекта единицы — это части продукта, а не ход работы.
        """
        statement = select(Direction).where(Direction.project_id == project_id)
        if not include_archived:
            statement = statement.where(Direction.archived_at.is_(None))
        return list((await self._session.scalars(statement.order_by(Direction.key))).all())

    async def list_page(
        self,
        project_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Direction]:
        """Страница направлений проекта общей пагинацией — для коллекции REST."""
        statement = select(Direction).where(Direction.project_id == project_id)
        if not include_archived:
            statement = statement.where(Direction.archived_at.is_(None))
        return await paginate(self._session, statement, Direction, limit=limit, cursor=cursor)

    async def first_archived(
        self, direction_ids: Collection[uuid.UUID]
    ) -> tuple[str, str, datetime] | None:
        """Ключ проекта, ключ и время архивирования первого архивного среди названных.

        Колонки, а не объект — по той же причине, что `ProjectRepository.first_archived`:
        запрос под очередью изменений видит состояние после зафиксировавшихся соседей и
        не трогает объекты в карте сессии.
        """
        if not direction_ids:
            return None
        statement = (
            select(Project.key, Direction.key, Direction.archived_at)
            .join(Project, Project.id == Direction.project_id)
            .where(Direction.id.in_(direction_ids), Direction.archived_at.is_not(None))
            .order_by(Project.key, Direction.key)
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None or row[2] is None:
            return None
        return row[0], row[1], row[2]

    async def add(self, direction: Direction) -> Direction:
        self._session.add(direction)
        await self._session.flush()
        return direction
