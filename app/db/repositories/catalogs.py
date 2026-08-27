"""Выборки и вставки по справочникам: статусы, типы задач, резолюции.

Один репозиторий на три таблицы: у них общая форма, а различия (категория у статуса,
иконка у типа) на запросы не влияют. Конкретная модель передаётся в конструктор.

Параметр типа объявлен через ограничения (`EntryT: (Status, IssueType, Resolution)`),
а не через общий базовый класс: `CatalogEntryMixin` — примесь, а не отображаемая
таблица, и вывести из неё, что у объекта есть `created_at` и `id`, нельзя.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import IssueType, Resolution, Status
from app.db.pagination import Page, paginate


class CatalogRepository[EntryT: (Status, IssueType, Resolution)]:
    """Доступ к одной из таблиц справочников."""

    def __init__(self, session: AsyncSession, model: type[EntryT]) -> None:
        self._session = session
        self._model = model

    async def get_by_id(self, entry_id: uuid.UUID) -> EntryT | None:
        return await self._session.get(self._model, entry_id)

    async def get(self, key: str, queue_id: uuid.UUID | None) -> EntryT | None:
        """Запись по ключу в точно указанной области.

        `queue_id=None` ищет именно глобальную запись, а не «любую с таким ключом»:
        глобальный `open` и локальный `TRK.open` — две разные записи, и подмена одной
        другой сделала бы конфигурацию очереди непредсказуемой.
        """
        statement = select(self._model).where(self._model.key == key)
        if queue_id is None:
            statement = statement.where(self._model.queue_id.is_(None))
        else:
            statement = statement.where(self._model.queue_id == queue_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        queue_id: uuid.UUID | None = None,
        include_global: bool = True,
        is_active: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[EntryT]:
        """Страница справочника.

        Без очереди видны только глобальные записи: локальные принадлежат своей
        очереди и вне её контекста смысла не имеют.
        """
        statement = select(self._model).where(*self._scope_conditions(queue_id, include_global))
        if is_active is not None:
            statement = statement.where(self._model.is_active.is_(is_active))
        return await paginate(self._session, statement, self._model, limit=limit, cursor=cursor)

    async def list_available(self, queue_id: uuid.UUID) -> list[EntryT]:
        """Все активные записи, доступные в очереди: глобальные плюс её собственные.

        Без пагинации намеренно: это конфигурация очереди, она собирается целиком и
        одним запросом — ради этого эндпоинт конфигурации и существует.
        """
        statement = (
            select(self._model)
            .where(
                *self._scope_conditions(queue_id, include_global=True),
                self._model.is_active.is_(True),
            )
            .order_by(self._model.created_at, self._model.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def list_global_active(self) -> list[EntryT]:
        """Глобальные активные записи в порядке создания: заготовка для новой очереди."""
        statement = (
            select(self._model)
            .where(self._model.queue_id.is_(None), self._model.is_active.is_(True))
            .order_by(self._model.created_at, self._model.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def add(self, entry: EntryT) -> EntryT:
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def delete(self, entry: EntryT) -> None:
        await self._session.delete(entry)
        await self._session.flush()

    def _scope_conditions(self, queue_id: uuid.UUID | None, include_global: bool) -> list[object]:
        if queue_id is None:
            return [self._model.queue_id.is_(None)]
        if include_global:
            return [or_(self._model.queue_id.is_(None), self._model.queue_id == queue_id)]
        return [self._model.queue_id == queue_id]
