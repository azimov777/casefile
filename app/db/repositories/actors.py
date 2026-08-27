"""Выборки и вставки по акторам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение
(`get_session` или `session_scope`). `flush` вызывать можно и нужно — он отправляет
INSERT в базу, не фиксируя транзакцию, чтобы сценарий сразу увидел нарушение
ограничения и получил заполненные значения по умолчанию.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.pagination import Page, paginate
from app.domain.actors import ActorType


class ActorRepository:
    """Доступ к таблице `actors`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, actor_id: uuid.UUID) -> Actor | None:
        return await self._session.get(Actor, actor_id)

    async def get_by_key(self, key: str) -> Actor | None:
        statement = select(Actor).where(Actor.key == key)
        return (await self._session.scalars(statement)).one_or_none()

    async def existing_keys(self, keys: set[str]) -> set[str]:
        """Какие из ключей принадлежат существующим акторам.

        Одним запросом на весь набор, а не по ключу за раз: значения кастомных полей
        со ссылками на акторов проверяются пачкой при каждом сохранении задачи, и
        отдельный `SELECT` на каждую ссылку превратил бы это в десяток запросов.
        Отвечает про существование, а не про активность: отключённый актор остаётся
        законной ссылкой в уже записанных данных.
        """
        if not keys:
            return set()
        statement = select(Actor.key).where(Actor.key.in_(keys))
        return set((await self._session.scalars(statement)).all())

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        actor_type: ActorType | None = None,
        is_active: bool | None = None,
    ) -> Page[Actor]:
        statement = select(Actor)
        if actor_type is not None:
            statement = statement.where(Actor.type == actor_type)
        if is_active is not None:
            statement = statement.where(Actor.is_active.is_(is_active))
        return await paginate(self._session, statement, Actor, limit=limit, cursor=cursor)

    async def add(self, actor: Actor) -> Actor:
        """Кладёт актора в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(actor)
        await self._session.flush()
        return actor
