"""Выборки и вставки по областям."""

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.project import Project
from app.db.pagination import Page, paginate


class AreaRepository:
    """Доступ к таблице `areas`. Проект области приезжает тем же запросом
    (`Area.project`, `lazy="joined"`): без его ключа у области нет адреса."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: uuid.UUID, key: str) -> Area | None:
        """Область проекта по уже канонизированному ключу (нижний регистр)."""
        statement = select(Area).where(Area.project_id == project_id, Area.key == key)
        return (await self._session.scalars(statement)).one_or_none()

    async def get_by_address(self, project_key: str, key: str) -> Area | None:
        """Область по адресу из канонических частей — для ссылок `TRK/promotion#3`."""
        statement = (
            select(Area)
            .join(Project, Project.id == Area.project_id)
            .where(Project.key == project_key, Area.key == key)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def list_for_project(
        self, project_id: uuid.UUID, *, include_archived: bool = False
    ) -> list[Area]:
        """Все области проекта по ключу; архивные — только если их просили.

        Целиком, а не страницей: список едет в чтении проекта (`get_project`), а
        областей у проекта единицы — это части продукта, а не ход работы.
        """
        statement = select(Area).where(Area.project_id == project_id)
        if not include_archived:
            statement = statement.where(Area.archived_at.is_(None))
        return list((await self._session.scalars(statement.order_by(Area.key))).all())

    async def list_page(
        self,
        project_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Area]:
        """Страница областей проекта общей пагинацией — для коллекции REST."""
        statement = select(Area).where(Area.project_id == project_id)
        if not include_archived:
            statement = statement.where(Area.archived_at.is_(None))
        return await paginate(self._session, statement, Area, limit=limit, cursor=cursor)

    async def first_archived(
        self, area_ids: Collection[uuid.UUID]
    ) -> tuple[str, str, datetime] | None:
        """Ключ проекта, ключ и время архивирования первого архивного среди названных.

        Колонки, а не объект — по той же причине, что `ProjectRepository.first_archived`:
        запрос под очередью изменений видит состояние после зафиксировавшихся соседей и
        не трогает объекты в карте сессии.
        """
        if not area_ids:
            return None
        statement = (
            select(Project.key, Area.key, Area.archived_at)
            .join(Project, Project.id == Area.project_id)
            .where(Area.id.in_(area_ids), Area.archived_at.is_not(None))
            .order_by(Project.key, Area.key)
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None or row[2] is None:
            return None
        return row[0], row[1], row[2]

    async def add(self, area: Area) -> Area:
        self._session.add(area)
        await self._session.flush()
        return area
