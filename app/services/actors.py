"""Сценарии по акторам и токенам.

Один сценарий — одна функция, вызываемая и из REST, и из MCP, и из командной строки.
Транзакцию функции не фиксируют: коммитит вход в приложение (`get_session` для запроса,
`session_scope` для воркера и команды). `flush` внутри есть — он нужен, чтобы объект
получил идентификатор и значения по умолчанию до конца транзакции.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.api_token import ApiToken
from app.db.pagination import Page
from app.db.repositories import ActorRepository, ApiTokenRepository
from app.domain.actors import (
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_KEY,
    ActorType,
    validate_actor_key,
)
from app.domain.errors import (
    ActorInactiveError,
    ActorKeyTakenError,
    ActorNotFoundError,
    ApiTokenNotFoundError,
    SystemActorProtectedError,
)
from app.domain.tokens import generate_token, hash_token
from app.services.permissions import ensure_allowed


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """Результат выпуска токена: запись в базе и её секрет.

    Секрет существует только здесь и в ответе на запрос выпуска. Второй раз его
    получить нельзя — в базе лежит хеш.
    """

    token: ApiToken
    secret: str


async def get_actor_by_key(session: AsyncSession, key: str) -> Actor:
    """Актор по ключу или `actor_not_found`."""
    actor = await ActorRepository(session).get_by_key(key.strip().lower())
    if actor is None:
        raise ActorNotFoundError(details={"key": key})
    return actor


async def get_system_actor(session: AsyncSession) -> Actor:
    """Системный актор: от его имени работают автоматика и фоновые процессы.

    Строка создаётся миграцией, поэтому здесь только чтение по известному
    идентификатору. Если её нет — база не домигрирована, и это ошибка установки,
    а не ситуация, которую сценарий должен как-то обходить.
    """
    actor = await ActorRepository(session).get_by_id(SYSTEM_ACTOR_ID)
    if actor is None:
        raise ActorNotFoundError(
            details={"key": SYSTEM_ACTOR_KEY, "reason": "database_is_not_migrated"},
        )
    return actor


async def read_actor(session: AsyncSession, key: str, *, initiator: Actor) -> Actor:
    """Чтение одного актора.

    Отдельно от `get_actor_by_key`: тот только ищет строку и вызывается из других
    сценариев, а этот — точка входа интерфейса, и он обязан пройти проверку прав.
    """
    ensure_allowed(initiator, "actor.read")
    return await get_actor_by_key(session, key)


async def list_actors(
    session: AsyncSession,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
    actor_type: ActorType | None = None,
    is_active: bool | None = None,
) -> Page[Actor]:
    """Страница списка акторов с фильтрами по типу и активности."""
    ensure_allowed(initiator, "actor.list")
    return await ActorRepository(session).list_page(
        limit=limit,
        cursor=cursor,
        actor_type=actor_type,
        is_active=is_active,
    )


async def create_actor(
    session: AsyncSession,
    *,
    initiator: Actor,
    actor_type: ActorType,
    key: str,
    display_name: str,
) -> Actor:
    """Заводит человека или агента.

    Тип `system` снаружи недоступен: системный актор один, создаётся миграцией, и
    второй такой сломал бы предположение автоматики о том, от чьего имени она ходит.
    """
    ensure_allowed(initiator, "actor.create")
    if actor_type is ActorType.SYSTEM:
        raise SystemActorProtectedError(
            details={"reason": "cannot_create", "type": ActorType.SYSTEM.value},
        )

    normalized_key = validate_actor_key(key)
    repository = ActorRepository(session)
    if await repository.get_by_key(normalized_key) is not None:
        raise ActorKeyTakenError(details={"key": normalized_key})

    return await repository.add(
        Actor(type=actor_type, key=normalized_key, display_name=display_name.strip())
    )


async def update_actor(
    session: AsyncSession,
    actor: Actor,
    *,
    initiator: Actor,
    display_name: str | None = None,
    is_active: bool | None = None,
) -> Actor:
    """Меняет отображаемое имя и признак активности.

    `None` означает «поле не передано»: у обоих полей нет осмысленного значения `null`,
    поэтому отдельный признак «передано как null» здесь не нужен. Настоящее различение
    «не передано» и «передано null» появится в задаче 05, где оно действительно нужно.
    """
    ensure_allowed(initiator, "actor.update", target=actor)
    if actor.is_system:
        raise SystemActorProtectedError(details={"reason": "cannot_update", "key": actor.key})

    if display_name is not None:
        actor.display_name = display_name.strip()
    if is_active is not None:
        actor.is_active = is_active
    await session.flush()
    return actor


async def list_tokens(
    session: AsyncSession,
    actor: Actor,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[ApiToken]:
    """Токены актора, включая отозванные: отзыв — часть истории, а не удаление."""
    ensure_allowed(initiator, "token.list", target=actor)
    return await ApiTokenRepository(session).list_page_for_actor(
        actor.id, limit=limit, cursor=cursor
    )


async def issue_token(
    session: AsyncSession,
    actor: Actor,
    *,
    initiator: Actor,
    name: str,
) -> IssuedToken:
    """Выпускает токен и возвращает его секрет — единственный раз за всю жизнь токена."""
    ensure_allowed(initiator, "token.issue", target=actor)
    if actor.is_system:
        raise SystemActorProtectedError(details={"reason": "cannot_issue_token", "key": actor.key})
    if not actor.is_active:
        raise ActorInactiveError(details={"key": actor.key, "reason": "cannot_issue_token"})

    secret = generate_token()
    token = await ApiTokenRepository(session).add(
        ApiToken(actor_id=actor.id, name=name.strip(), token_hash=hash_token(secret))
    )
    return IssuedToken(token=token, secret=secret)


async def revoke_token(
    session: AsyncSession,
    actor: Actor,
    token_id: uuid.UUID,
    *,
    initiator: Actor,
) -> ApiToken:
    """Отзывает токен. Повторный отзыв ничего не меняет и ошибкой не считается.

    Отзыв идемпотентен намеренно: клиент, не получивший ответ и повторивший запрос,
    не должен получать ошибку на действие, которое уже выполнено.
    """
    ensure_allowed(initiator, "token.revoke", target=actor)
    token = await ApiTokenRepository(session).get_for_actor(actor.id, token_id)
    if token is None:
        raise ApiTokenNotFoundError(details={"token_id": str(token_id), "actor": actor.key})

    if not token.is_revoked:
        token.revoked_at = datetime.now(UTC)
        await session.flush()
    return token


async def ensure_actor(
    session: AsyncSession,
    *,
    actor_type: ActorType,
    key: str,
    display_name: str,
) -> tuple[Actor, bool]:
    """Возвращает актора с таким ключом, создавая его при необходимости.

    Нужна команде инициализации: та должна быть идемпотентной, чтобы повторный запуск
    не падал. Проверку прав не делает — вызывается до того, как в системе есть хоть
    один токен, инициатора у неё нет.
    """
    repository = ActorRepository(session)
    existing = await repository.get_by_key(validate_actor_key(key))
    if existing is not None:
        return existing, False

    actor = await repository.add(
        Actor(type=actor_type, key=validate_actor_key(key), display_name=display_name.strip())
    )
    return actor, True
