"""Выборки и вставки по токенам доступа."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_token import ApiToken
from app.db.pagination import Page, paginate


class ApiTokenRepository:
    """Доступ к таблице `api_tokens`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        """Поиск токена при аутентификации: одно обращение по уникальному индексу.

        Актор приезжает тем же запросом — связь объявлена с `lazy="joined"`.
        """
        statement = select(ApiToken).where(ApiToken.token_hash == token_hash)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_for_actor(self, actor_id: uuid.UUID, token_id: uuid.UUID) -> ApiToken | None:
        """Токен по идентификатору, но только среди токенов указанного актора.

        Проверка владельца встроена в запрос: иначе её пришлось бы не забыть в каждом
        сценарии, а забытая — превращается в возможность отозвать чужой токен.
        """
        statement = select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.actor_id == actor_id,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page_for_actor(
        self,
        actor_id: uuid.UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[ApiToken]:
        statement = select(ApiToken).where(ApiToken.actor_id == actor_id)
        return await paginate(self._session, statement, ApiToken, limit=limit, cursor=cursor)

    async def add(self, token: ApiToken) -> ApiToken:
        self._session.add(token)
        await self._session.flush()
        return token
