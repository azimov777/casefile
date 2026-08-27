"""Сценарии по акторам и токенам: успех и основные отказы."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.pagination import MAX_PAGE_SIZE, InvalidPageSizeError
from app.domain.actors import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_KEY, ActorType
from app.domain.errors import (
    ActorInactiveError,
    ActorKeyTakenError,
    ActorNotFoundError,
    ApiTokenNotFoundError,
    SystemActorProtectedError,
)
from app.domain.tokens import hash_token
from app.services import actors as service


async def test_system_actor_is_seeded_by_migration(db_session: AsyncSession) -> None:
    """Идентификатор системного актора в коде и в миграции — одно и то же значение.

    Литерал в миграции продублирован намеренно (миграция не должна зависеть от кода),
    и разъехаться этим двум значениям нельзя: на системного актора будут ссылаться
    журнал изменений, outbox и автоматика.
    """
    system = await service.get_system_actor(db_session)

    assert system.id == SYSTEM_ACTOR_ID
    assert system.key == SYSTEM_ACTOR_KEY
    assert system.type is ActorType.SYSTEM


async def test_page_size_is_checked_outside_http_too(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Проверка живёт в сценарии, а не только в параметре запроса.

    Иначе MCP и фоновые вызовы, идущие мимо FastAPI, получили бы другое поведение
    на том же самом входе.
    """
    with pytest.raises(InvalidPageSizeError) as error:
        await service.list_actors(db_session, initiator=owner, limit=MAX_PAGE_SIZE + 1)

    assert error.value.details["max"] == MAX_PAGE_SIZE


async def test_create_actor_normalizes_key(db_session: AsyncSession, owner: Actor) -> None:
    actor = await service.create_actor(
        db_session,
        initiator=owner,
        actor_type=ActorType.AGENT,
        key="  Release_Bot ",
        display_name="  Релизный бот  ",
    )

    assert actor.key == "release_bot"
    assert actor.display_name == "Релизный бот"
    assert actor.is_active is True


async def test_duplicate_key_is_rejected(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(ActorKeyTakenError):
        await service.create_actor(
            db_session,
            initiator=owner,
            actor_type=ActorType.AGENT,
            key=owner.key,
            display_name="Двойник",
        )


async def test_system_actor_cannot_be_created(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(SystemActorProtectedError):
        await service.create_actor(
            db_session,
            initiator=owner,
            actor_type=ActorType.SYSTEM,
            key="fake_system",
            display_name="Подделка",
        )


async def test_system_actor_cannot_be_updated(
    db_session: AsyncSession,
    owner: Actor,
    system_actor: Actor,
) -> None:
    """Отключённый системный актор остановил бы автоматику — запрет стоит в сценарии."""
    with pytest.raises(SystemActorProtectedError):
        await service.update_actor(db_session, system_actor, initiator=owner, is_active=False)


async def test_system_actor_cannot_get_a_token(
    db_session: AsyncSession,
    owner: Actor,
    system_actor: Actor,
) -> None:
    with pytest.raises(SystemActorProtectedError):
        await service.issue_token(db_session, system_actor, initiator=owner, name="fake")


async def test_update_touches_only_passed_fields(db_session: AsyncSession, owner: Actor) -> None:
    actor = await service.create_actor(
        db_session,
        initiator=owner,
        actor_type=ActorType.AGENT,
        key="partial_bot",
        display_name="Бот",
    )

    await service.update_actor(db_session, actor, initiator=owner, is_active=False)

    assert actor.is_active is False
    assert actor.display_name == "Бот"


async def test_missing_actor_reports_the_key(db_session: AsyncSession) -> None:
    with pytest.raises(ActorNotFoundError) as error:
        await service.get_actor_by_key(db_session, "ghost")

    assert error.value.details["key"] == "ghost"


async def test_issued_token_is_stored_only_as_a_hash(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    issued = await service.issue_token(db_session, owner, initiator=owner, name="laptop")

    assert issued.token.token_hash == hash_token(issued.secret)
    assert issued.secret not in issued.token.token_hash


async def test_inactive_actor_gets_no_tokens(db_session: AsyncSession, owner: Actor) -> None:
    actor = await service.create_actor(
        db_session,
        initiator=owner,
        actor_type=ActorType.AGENT,
        key="sleeping_bot",
        display_name="Спящий",
    )
    await service.update_actor(db_session, actor, initiator=owner, is_active=False)

    with pytest.raises(ActorInactiveError):
        await service.issue_token(db_session, actor, initiator=owner, name="nope")


async def test_revoke_is_idempotent(db_session: AsyncSession, owner: Actor) -> None:
    """Повторный отзыв не меняет отметку: клиент, повторивший запрос, не получает ошибку."""
    issued = await service.issue_token(db_session, owner, initiator=owner, name="laptop")

    first = await service.revoke_token(db_session, owner, issued.token.id, initiator=owner)
    revoked_at = first.revoked_at
    second = await service.revoke_token(db_session, owner, issued.token.id, initiator=owner)

    assert revoked_at is not None
    assert second.revoked_at == revoked_at


async def test_token_of_another_actor_cannot_be_revoked(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Проверка владельца встроена в запрос, а не оставлена на внимательность сценария."""
    stranger = await service.create_actor(
        db_session,
        initiator=owner,
        actor_type=ActorType.AGENT,
        key="stranger_bot",
        display_name="Чужой",
    )
    issued = await service.issue_token(db_session, owner, initiator=owner, name="laptop")

    with pytest.raises(ApiTokenNotFoundError):
        await service.revoke_token(db_session, stranger, issued.token.id, initiator=owner)


async def test_unknown_token_id_is_not_found(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(ApiTokenNotFoundError):
        await service.revoke_token(db_session, owner, uuid.uuid4(), initiator=owner)


async def test_revoked_tokens_stay_in_the_list(db_session: AsyncSession, owner: Actor) -> None:
    """Отзыв — не удаление: по записи видно, чем ходили раньше."""
    issued = await service.issue_token(db_session, owner, initiator=owner, name="laptop")
    await service.revoke_token(db_session, owner, issued.token.id, initiator=owner)

    page = await service.list_tokens(db_session, owner, initiator=owner)

    assert [token.id for token in page.items] == [issued.token.id]
    assert page.items[0].revoked_at is not None
