"""Выборки, вставки и снятие атрибутов проекта."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.attribute import ProjectAttribute


class AttributeRepository:
    """Доступ к таблице `project_attributes`.

    Имя сравнивается в нижнем регистре тем же выражением, что стоит под уникальным
    индексом: запрос по имени идёт по индексу, а не по всей таблице.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_name(self, project_id: uuid.UUID, lookup_name: str) -> ProjectAttribute | None:
        """Атрибут по имени, уже приведённому к нижнему регистру доменом."""
        statement = select(ProjectAttribute).where(
            ProjectAttribute.project_id == project_id,
            func.lower(ProjectAttribute.name) == lookup_name,
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> list[ProjectAttribute]:
        """Все атрибуты проекта по имени без учёта регистра: порядок не зависит от истории."""
        statement = (
            select(ProjectAttribute)
            .where(ProjectAttribute.project_id == project_id)
            .order_by(func.lower(ProjectAttribute.name))
        )
        return list((await self._session.scalars(statement)).all())

    async def add(self, attribute: ProjectAttribute) -> ProjectAttribute:
        self._session.add(attribute)
        await self._session.flush()
        return attribute

    async def remove(self, attribute: ProjectAttribute) -> None:
        """Снимает строку. История остаётся в деле проекта — запись подшивает сценарий."""
        await self._session.delete(attribute)
        await self._session.flush()
