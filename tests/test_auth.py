"""Аутентификация по токену: сценарий, общий для REST, MCP и командной строки.

Здесь же проверяется главное новое правило фундамента: общий агентский токен не называет
автора сам, и подпись ему даёт заголовок `X-Actor-Label`.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.domain.authors import AuthorKind
from app.domain.errors import ActorLabelRequiredError, InvalidActorLabelError
from app.domain.tokens import TokenScope
from app.services import tokens as service
from app.services.auth import LAST_USED_THROTTLE, Actor, authenticate


async def test_a_participant_token_signs_with_the_participant_name(
    db_session: AsyncSession,
    owner: Participant,
    main_secret: str,
) -> None:
    actor = await authenticate(db_session, main_secret)

    assert actor.author.kind is AuthorKind.HUMAN
    assert actor.author.signature == owner.name
    assert actor.scope is TokenScope.MAIN
    assert actor.participant is not None and actor.participant.id == owner.id


async def test_surrounding_whitespace_does_not_break_the_token(
    db_session: AsyncSession,
    main_secret: str,
) -> None:
    actor = await authenticate(db_session, f" {main_secret}\n")

    assert actor.author.signature == "owner"


@pytest.mark.parametrize(
    ("secret", "reason"),
    [("", "missing_token"), ("   ", "missing_token"), ("trk_nonsense", "unknown_token")],
)
async def test_bad_secret_is_rejected(db_session: AsyncSession, secret: str, reason: str) -> None:
    with pytest.raises(UnauthorizedError) as error:
        await authenticate(db_session, secret)

    assert error.value.code == "unauthorized"
    assert error.value.details["reason"] == reason


async def test_revoked_token_stops_working(
    db_session: AsyncSession,
    owner: Participant,
    main_actor: Actor,
) -> None:
    issued = await service.issue_token(
        db_session, actor=main_actor, participant=owner, scope=TokenScope.TASK, name="second"
    )
    await service.revoke_token(db_session, issued.token.id, actor=main_actor)

    with pytest.raises(UnauthorizedError) as error:
        await authenticate(db_session, issued.secret)

    assert error.value.details["reason"] == "token_revoked"
    # Сообщение то же, что у неизвестного токена: подтверждать существование
    # отозванного секрета не нужно.
    assert error.value.message == "Token is unknown or revoked"


# --- Общий агентский токен ---------------------------------------------------------


async def test_a_shared_token_without_a_label_is_refused(
    db_session: AsyncSession,
    shared_secret: str,
) -> None:
    """Токен настоящий, но приписать действие некому — значит запрос не аутентифицирован."""
    with pytest.raises(ActorLabelRequiredError) as error:
        await authenticate(db_session, shared_secret)

    assert error.value.code == "actor_label_required"
    assert error.value.status_code == 401


async def test_a_shared_token_signs_with_the_label(
    db_session: AsyncSession,
    shared_secret: str,
) -> None:
    actor = await authenticate(db_session, shared_secret, label="Nightly_Agent")

    assert actor.author.kind is AuthorKind.AGENT
    assert actor.author.signature == "nightly_agent"
    assert actor.participant is None


async def test_a_malformed_label_is_rejected(
    db_session: AsyncSession,
    shared_secret: str,
) -> None:
    with pytest.raises(InvalidActorLabelError):
        await authenticate(db_session, shared_secret, label="nightly agent")


async def test_a_participant_token_ignores_the_label(
    db_session: AsyncSession,
    main_secret: str,
) -> None:
    """Подпись именного токена всегда его собственная: подделать её меткой нельзя.

    Метка при этом не отвергается, а игнорируется: клиент, который шлёт её всегда, не
    должен держать две конфигурации ради одного заголовка.
    """
    actor = await authenticate(db_session, main_secret, label="someone_else")

    assert actor.author.signature == "owner"


# --- Отметка последнего использования ----------------------------------------------


async def test_first_use_is_recorded(
    db_session: AsyncSession,
    main_actor: Actor,
    main_secret: str,
) -> None:
    moment = datetime.now(UTC)

    await authenticate(db_session, main_secret, now=moment)

    page = await service.list_tokens(db_session, actor=main_actor)
    assert [token.last_used_at for token in page.items] == [moment]


async def test_last_used_is_throttled(
    db_session: AsyncSession,
    main_actor: Actor,
    main_secret: str,
) -> None:
    """Иначе любое чтение через API превращалось бы в запись строки в базе."""
    first = datetime.now(UTC)
    await authenticate(db_session, main_secret, now=first)

    await authenticate(db_session, main_secret, now=first + timedelta(seconds=1))
    page = await service.list_tokens(db_session, actor=main_actor)
    assert page.items[0].last_used_at == first

    await authenticate(db_session, main_secret, now=first + LAST_USED_THROTTLE)
    page = await service.list_tokens(db_session, actor=main_actor)
    assert page.items[0].last_used_at == first + LAST_USED_THROTTLE


async def test_an_expired_session_token_stops_working(
    db_session: AsyncSession, owner: Participant
) -> None:
    """Срок бывает только у токена сеанса: после него — `token_expired`, до — обычный вход."""
    issued = await service.issue_token(
        db_session,
        actor=Actor(author=owner.author, scope=TokenScope.MAIN, participant=owner),
        participant=owner,
        scope=TokenScope.MAIN,
        name="browser-session",
    )
    deadline = datetime.now(UTC) + timedelta(hours=1)
    issued.token.expires_at = deadline
    await db_session.flush()

    before = await authenticate(db_session, issued.secret, now=deadline - timedelta(seconds=1))
    with pytest.raises(UnauthorizedError) as expired:
        await authenticate(db_session, issued.secret, now=deadline)

    assert before.author == owner.author
    assert expired.value.details == {"reason": "token_expired"}
