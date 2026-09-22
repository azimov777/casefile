"""Выборки и вставки по токенам доступа."""

import uuid
from collections.abc import Sequence

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

    async def list_live_named(self, participant_id: uuid.UUID, name: str) -> Sequence[Token]:
        """Неотозванные токены участника с этим именем.

        Нужны выдаче ключа локальной установке (`app/services/setup.py`,
        `ensure_local_token`): она выпускает замену и обязана тем же действием отозвать
        прежнюю. Иначе на машине копились бы действующие секреты, которых никто не
        знает, — а секрет выпущенного токена не показывается второй раз даже владельцу.

        Имя здесь — обычная колонка без уникальности: у участника может быть сколько
        угодно токенов с одним именем, и выборка возвращает все.
        """
        statement = select(Token).where(
            Token.participant_id == participant_id,
            Token.name == name,
            Token.revoked_at.is_(None),
        )
        return (await self._session.scalars(statement)).unique().all()

    async def list_live_of(
        self,
        participant_id: uuid.UUID,
        *,
        sessions_only: bool,
        keep: uuid.UUID | None = None,
    ) -> Sequence[Token]:
        """Неотозванные токены участника — все или только сеансы браузера.

        Нужны учётным записям (`app/services/accounts.py`): отключение отзывает все
        токены человека, смена и сброс пароля — его сеансы. `keep` — токен, который
        остаётся живым: смена своего пароля не выбрасывает из той вкладки, где её сделали.
        """
        statement = select(Token).where(
            Token.participant_id == participant_id,
            Token.revoked_at.is_(None),
        )
        if sessions_only:
            statement = statement.where(Token.expires_at.is_not(None))
        if keep is not None:
            statement = statement.where(Token.id != keep)
        return (await self._session.scalars(statement)).unique().all()

    async def add(self, token: Token) -> Token:
        self._session.add(token)
        await self._session.flush()
        return token
