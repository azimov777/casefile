"""Выборки и вставки по токенам доступа."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.token import Token
from app.db.pagination import Page, paginate


class TokenRepository:
    """Доступ к таблице `tokens`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: str) -> Token | None:
        """Поиск токена при аутентификации: одно обращение по уникальному индексу.

        Участник приезжает тем же запросом — связь объявлена с `lazy="joined"`.
        """
        statement = select(Token).where(Token.token_hash == token_hash)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_by_id(self, token_id: uuid.UUID) -> Token | None:
        statement = select(Token).where(Token.id == token_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Token]:
        return await paginate(self._session, select(Token), Token, limit=limit, cursor=cursor)

    async def any_exists(self) -> bool:
        """Есть ли в установке хоть один токен.

        На этом стоит первичная инициализация: она обязана понимать, свежая перед ней
        база или работающая установка. Вопрос именно про токен, а не про участника:
        участник без токена доступа не даёт, и запертая установка осталась бы запертой.
        """
        return await self._session.scalar(select(Token.id).limit(1)) is not None

    async def add(self, token: Token) -> Token:
        self._session.add(token)
        await self._session.flush()
        return token
