"""Аутентификация по токену: сценарий, общий для REST, MCP и командной строки."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.actor import Actor
from app.domain.actors import ActorType
from app.services import actors as service
from app.services.auth import LAST_USED_THROTTLE, authenticate_by_token


async def test_valid_token_resolves_to_its_actor(
    db_session: AsyncSession,
    owner: Actor,
    owner_secret: str,
) -> None:
    actor = await authenticate_by_token(db_session, owner_secret)

    assert actor.id == owner.id


async def test_surrounding_whitespace_does_not_break_the_token(
    db_session: AsyncSession,
    owner: Actor,
    owner_secret: str,
) -> None:
    actor = await authenticate_by_token(db_session, f" {owner_secret}\n")

    assert actor.id == owner.id


@pytest.mark.parametrize(
    ("secret", "reason"),
    [("", "missing_token"), ("   ", "missing_token"), ("trk_nonsense", "unknown_token")],
)
async def test_bad_secret_is_rejected(db_session: AsyncSession, secret: str, reason: str) -> None:
    with pytest.raises(UnauthorizedError) as error:
        await authenticate_by_token(db_session, secret)

    assert error.value.code == "unauthorized"
    assert error.value.details["reason"] == reason


async def test_revoked_token_stops_working(
    db_session: AsyncSession,
    owner: Actor,
    owner_secret: str,
) -> None:
    issued = await service.issue_token(db_session, owner, initiator=owner, name="second")
    await service.revoke_token(db_session, owner, issued.token.id, initiator=owner)

    with pytest.raises(UnauthorizedError) as error:
        await authenticate_by_token(db_session, issued.secret)

    assert error.value.details["reason"] == "token_revoked"
    # Сообщение то же, что у неизвестного токена: подтверждать существование
    # отозванного секрета не нужно.
    assert error.value.message == "Token is unknown or revoked"


async def test_inactive_actor_cannot_authenticate(
    db_session: AsyncSession,
    owner: Actor,
    system_actor: Actor,
) -> None:
    """Отключение актора — способ убрать агента, не удаляя его следы в истории."""
    agent = await service.create_actor(
        db_session,
        initiator=owner,
        actor_type=ActorType.AGENT,
        key="retired_bot",
        display_name="Отставной",
    )
    issued = await service.issue_token(db_session, agent, initiator=system_actor, name="ci")
    await service.update_actor(db_session, agent, initiator=owner, is_active=False)

    with pytest.raises(UnauthorizedError) as error:
        await authenticate_by_token(db_session, issued.secret)

    assert error.value.details["reason"] == "actor_inactive"


async def test_first_use_is_recorded(
    db_session: AsyncSession,
    owner: Actor,
    owner_secret: str,
) -> None:
    moment = datetime.now(UTC)

    await authenticate_by_token(db_session, owner_secret, now=moment)

    page = await service.list_tokens(db_session, owner, initiator=owner)
    assert page.items[0].last_used_at == moment


async def test_last_used_is_throttled(
    db_session: AsyncSession,
    owner: Actor,
    owner_secret: str,
) -> None:
    """Иначе любое чтение через API превращалось бы в запись строки в базе."""
    first = datetime.now(UTC)
    await authenticate_by_token(db_session, owner_secret, now=first)

    await authenticate_by_token(db_session, owner_secret, now=first + timedelta(seconds=1))
    page = await service.list_tokens(db_session, owner, initiator=owner)
    assert page.items[0].last_used_at == first

    await authenticate_by_token(db_session, owner_secret, now=first + LAST_USED_THROTTLE)
    page = await service.list_tokens(db_session, owner, initiator=owner)
    assert page.items[0].last_used_at == first + LAST_USED_THROTTLE
