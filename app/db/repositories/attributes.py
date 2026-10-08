"""Выборки, вставки и снятие атрибутов проекта и области."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.area import Area
from app.db.models.attribute import AreaAttribute, Attribute, ProjectAttribute
from app.db.models.project import Project


def _owned(owner: Project | Area) -> tuple[type[Attribute], ColumnElement[bool]]:
    """Таблица атрибутов владельца и условие «атрибуты этого владельца».

    Механика одна (TRK#84, TRK#57), таблицы две (`app/db/models/attribute.py`):
    выбор делается здесь, один раз, а не ветвлением в каждом методе.
    """
    if isinstance(owner, Area):
        return AreaAttribute, AreaAttribute.area_id == owner.id
    return ProjectAttribute, ProjectAttribute.project_id == owner.id


class AttributeRepository:
    """Доступ к таблицам `project_attributes` и `area_attributes`.

    Имя сравнивается в нижнем регистре тем же выражением, что стоит под уникальным
    индексом: запрос по имени идёт по индексу, а не по всей таблице.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_name(self, owner: Project | Area, lookup_name: str) -> Attribute | None:
        """Атрибут владельца по имени, уже приведённому к нижнему регистру доменом."""
        model, owned = _owned(owner)
        statement = select(model).where(owned, func.lower(model.name) == lookup_name)
        return (await self._session.scalars(statement)).one_or_none()

    async def list_for(self, owner: Project | Area) -> list[Attribute]:
        """Все атрибуты владельца по имени без учёта регистра: порядок не зависит от истории."""
        model, owned = _owned(owner)
        statement = select(model).where(owned).order_by(func.lower(model.name))
        return list((await self._session.scalars(statement)).all())

    async def add(self, owner: Project | Area, *, name: str, value: str) -> Attribute:
        """Заводит строку атрибута владельца и отправляет INSERT."""
        attribute: Attribute = (
            AreaAttribute(area_id=owner.id, name=name, value=value)
            if isinstance(owner, Area)
            else ProjectAttribute(project_id=owner.id, name=name, value=value)
        )
        self._session.add(attribute)
        await self._session.flush()
        return attribute

    async def remove(self, attribute: Attribute) -> None:
        """Снимает строку. История остаётся в деле владельца — запись подшивает сценарий."""
        await self._session.delete(attribute)
        await self._session.flush()
