"""Выборки и вставки по токенам доступа."""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.pagination import Page, paginate


def owned_by(owner: Participant) -> ColumnElement[bool]:
    """Свои токены участника: говорят от его имени или выпущены им.

    Зеркало `Token.belongs_to` на стороне базы — предикат один и живёт парой
    (`docs/CONCEPT.md`, 3.1). Пространство (TRK-107) добавится сюда ещё одним условием.
    """
    author = owner.author
    return or_(
        Token.participant_id == owner.id,
        and_(
            Token.created_by_kind == author.kind,
            Token.created_by_signature == author.signature,
        ),
    )


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
        owner: Participant | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Token]:
        """Страница токенов установки — всех или только своих у `owner`."""
        statement = select(Token)
        if owner is not None:
            statement = statement.where(owned_by(owner))
        return await paginate(self._session, statement, Token, limit=limit, cursor=cursor)

    async def list_live_owned_by(self, owner: Participant) -> Sequence[Token]:
        """Неотозванные свои токены участника: их отзывает отключение его учётной записи."""
        statement = select(Token).where(owned_by(owner), Token.revoked_at.is_(None))
        return (await self._session.scalars(statement)).unique().all()

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

    async def list_live_sessions_of(
        self,
        participant_id: uuid.UUID,
        *,
        keep: uuid.UUID | None = None,
    ) -> Sequence[Token]:
        """Неотозванные сеансы браузера участника.

        Нужны учётным записям (`app/services/accounts.py`): смена и сброс пароля отзывают
        сеансы человека (отключение отзывает больше — `list_live_owned_by`). `keep` —
        токен, который остаётся живым: смена своего пароля не выбрасывает из той вкладки,
        где её сделали.
        """
        statement = select(Token).where(
            Token.participant_id == participant_id,
            Token.revoked_at.is_(None),
            Token.expires_at.is_not(None),
        )
        if keep is not None:
            statement = statement.where(Token.id != keep)
        return (await self._session.scalars(statement)).unique().all()

    async def add(self, token: Token) -> Token:
        self._session.add(token)
        await self._session.flush()
        return token
