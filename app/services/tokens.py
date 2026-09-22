"""Сценарии по токенам доступа.

## Кто что видит и отзывает

Свой токен участника — тот, что говорит от его имени, или тот, что он выпустил
(`Token.belongs_to`, `docs/CONCEPT.md`, 3.1; решение `TRK-114#12`). Человек выпускает
токены своим агентам сам, видит и отзывает свои; администратор и сам трекер — все токены
установки. Нового набора под это нет: набор отвечает за право на задачи, а «чей токен» —
вопрос строки, и решается он здесь, после `ensure_scope`.

Выпуск сверх набора `main` требует действующей учётной записи у выпускающего: выдача
доступов остаётся за человеком. Иначе агент с токеном `main`, полученным от человека,
выпускал бы ключи, которые не принадлежат этому человеку и переживают его отключение.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.author import created_by_columns
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.pagination import Page
from app.db.repositories import TokenRepository
from app.domain.errors import TokenNotFoundError
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope, generate_token, hash_token
from app.services.accounts import active_account_of, is_admin
from app.services.auth import TRACKER_ACTOR, Actor
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
    mine: bool = False,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Token]:
    """Токены, включая отозванные: отзыв — часть истории, а не удаление.

    Администратор и трекер видят все токены установки, остальные — свои; `mine` сужает
    до своих и администратора. У того, за кем нет участника (временный агент с общим
    токеном), своих токенов нет — список пуст. Чтение открыто обоим наборам. Секрета в
    списке нет и быть не может — в базе лежит только хеш.
    """
    ensure_scope(actor, TokenScope.TASK, action="token.list")
    tokens = TokenRepository(session)
    if not mine and await is_admin(session, actor):
        return await tokens.list_page(limit=limit, cursor=cursor)
    if actor.participant is None:
        return Page(items=[], next_cursor=None)
    return await tokens.list_page(owner=actor.participant, limit=limit, cursor=cursor)


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
    await _ensure_may_issue(session, actor, participant)

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
    own = actor.participant is not None and token.belongs_to(actor.participant)
    if not own and not await is_admin(session, actor):
        raise PermissionDeniedError(
            message="Only the owner of a token or an administrator can revoke it",
            details={"action": "token.revoke", "reason": "not_own_token"},
        )

    if not token.is_revoked:
        token.revoked_at = datetime.now(UTC)
        await session.flush()
    return token


async def _ensure_may_issue(
    session: AsyncSession, actor: Actor, participant: Participant | None
) -> None:
    """Выпускает человек с действующей учётной записью или сам трекер.

    Чужим именем — только администратор.

    Отказы — `permission_denied` с `details.action: token.issue` и причиной:
    `account_required` — за токеном запроса нет действующей учётной записи (агент с
    токеном `main`); `foreign_human` — ключ говорил бы от имени другого человека, а
    выпускающий не администратор: иначе любой вошедший подписывался бы чужим именем.
    """
    if actor == TRACKER_ACTOR:
        return
    account = await active_account_of(session, actor)
    if account is None:
        raise PermissionDeniedError(
            message="Only a person signed in with an account can issue tokens",
            details={"action": "token.issue", "reason": "account_required"},
        )
    foreign_human = (
        participant is not None
        and participant.kind is ParticipantKind.HUMAN
        and participant.id != account.participant_id
    )
    if foreign_human and not account.is_admin:
        raise PermissionDeniedError(
            message="Only an administrator can issue a token that speaks for another person",
            details={"action": "token.issue", "reason": "foreign_human"},
        )
