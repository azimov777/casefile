"""Сценарии по токенам доступа."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.pagination import Page
from app.db.repositories import TokenRepository
from app.domain.errors import TokenNotFoundError
from app.domain.tokens import TokenScope, generate_token, hash_token
from app.services.auth import Actor
from app.services.permissions import ensure_scope


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """Результат выпуска токена: запись в базе и её секрет.

    Секрет существует только здесь и в ответе на запрос выпуска. Второй раз его
    получить нельзя — в базе лежит хеш.
    """

    token: Token
    secret: str


async def list_tokens(
    session: AsyncSession,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Token]:
    """Все токены установки, включая отозванные: отзыв — часть истории, а не удаление.

    Чтение открыто обоим наборам, как и у остальных реестров фундамента. Секрета в
    списке нет и быть не может — в базе лежит только хеш.
    """
    ensure_scope(actor, TokenScope.TASK, action="token.list")
    return await TokenRepository(session).list_page(limit=limit, cursor=cursor)


async def issue_token(
    session: AsyncSession,
    *,
    actor: Actor,
    scope: TokenScope,
    name: str,
    participant: Participant | None = None,
) -> IssuedToken:
    """Выпускает токен и возвращает его секрет — единственный раз за всю жизнь токена.

    Без участника получается **общий агентский** токен: им ходят временные агенты,
    подписываясь заголовком `X-Actor-Label`. Это не недосмотр вызывающего, а отдельный
    вид доступа, поэтому участник — необязательный параметр, а не проверяемое условие.
    """
    ensure_scope(actor, TokenScope.MAIN, action="token.issue")

    secret = generate_token()
    # Связь задаётся объектом, а не внешним ключом: у только что созданной строки связь
    # иначе не загружена, и обращение к ней при сборке ответа падает `MissingGreenlet`
    # — далеко от места ошибки. Внешний ключ SQLAlchemy заполнит сам.
    token = await TokenRepository(session).add(
        Token(
            participant=participant,
            scope=scope,
            name=name.strip(),
            token_hash=hash_token(secret),
            **created_by_columns(actor.author),
        )
    )
    return IssuedToken(token=token, secret=secret)


async def revoke_token(session: AsyncSession, token_id: uuid.UUID, *, actor: Actor) -> Token:
    """Отзывает токен. Повторный отзыв ничего не меняет и ошибкой не считается.

    Отзыв идемпотентен намеренно: клиент, не получивший ответ и повторивший запрос,
    не должен получать ошибку на действие, которое уже выполнено.
    """
    ensure_scope(actor, TokenScope.MAIN, action="token.revoke")

    token = await TokenRepository(session).get_by_id(token_id)
    if token is None:
        raise TokenNotFoundError(details={"token_id": str(token_id)})

    if not token.is_revoked:
        token.revoked_at = datetime.now(UTC)
        await session.flush()
    return token
