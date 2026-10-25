"""Выборки и изменения по связям областей `see_also`.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
Области и их проекты приезжают теми же запросами (`AreaLink.source`/`target` — `selectin`,
`Area.project` — `joined`): без ключа проекта у области нет адреса.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.area_link import AreaLink
from app.db.models.project import Project


class AreaLinkRepository:
    """Доступ к таблице `area_links`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, *, source_id: uuid.UUID, target_id: uuid.UUID) -> AreaLink | None:
        """Связь по направленной паре: источник и цель не переставляются."""
        statement = select(AreaLink).where(
            AreaLink.source_area_id == source_id, AreaLink.target_area_id == target_id
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_outgoing(self, area_id: uuid.UUID) -> list[AreaLink]:
        """Связи, где область — источник (`see_also`), по адресу цели."""
        target = Area.__table__.alias("target_area")
        target_project = Project.__table__.alias("target_project")
        statement = (
            select(AreaLink)
            .join(target, target.c.id == AreaLink.target_area_id)
            .join(target_project, target_project.c.id == target.c.project_id)
            .where(AreaLink.source_area_id == area_id)
            .order_by(target_project.c.key, target.c.key)
        )
        return list((await self._session.scalars(statement)).unique())

    async def list_incoming(self, area_id: uuid.UUID) -> list[AreaLink]:
        """Связи, где область — цель (`see_also_from`), по адресу источника."""
        source = Area.__table__.alias("source_area")
        source_project = Project.__table__.alias("source_project")
        statement = (
            select(AreaLink)
            .join(source, source.c.id == AreaLink.source_area_id)
            .join(source_project, source_project.c.id == source.c.project_id)
            .where(AreaLink.target_area_id == area_id)
            .order_by(source_project.c.key, source.c.key)
        )
        return list((await self._session.scalars(statement)).unique())

    async def add(self, link: AreaLink) -> AreaLink:
        """Кладёт связь в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(link)
        await self._session.flush()
        return link

    async def delete(self, link: AreaLink) -> None:
        await self._session.delete(link)
        await self._session.flush()
