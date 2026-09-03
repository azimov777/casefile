"""Сценарии по токенам: выпуск именного и общего, список, отзыв."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.participant import Participant
from app.domain.errors import TokenNotFoundError
from app.domain.tokens import TOKEN_PREFIX, TokenScope, hash_token
from app.services import tokens as service
from app.services.auth import Actor, authenticate


async def test_issuing_returns_the_secret_and_stores_only_its_hash(
    db_session: AsyncSession,
    main_actor: Actor,
    owner: Participant,
) -> None:
    issued = await service.issue_token(
        db_session, actor=main_actor, participant=owner, scope=TokenScope.TASK, name="ci"
    )

    assert issued.secret.startswith(TOKEN_PREFIX)
    assert issued.token.token_hash == hash_token(issued.secret)
    assert issued.token.participant is not None
    assert issued.token.participant.id == owner.id
    assert issued.token.created_by.signature == "owner"


async def test_a_token_without_a_participant_is_a_shared_one(
    db_session: AsyncSession,
    main_actor: Actor,
) -> None:
    """Отсутствие участника — вид доступа, а не недосмотр вызывающего."""
    issued = await service.issue_token(
        db_session, actor=main_actor, scope=TokenScope.TASK, name="agents"
    )

    assert issued.token.is_shared
    assert issued.token.participant is None


async def test_issuing_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    owner: Participant,
) -> None:
    with pytest.raises(PermissionDeniedError) as error:
        await service.issue_token(
            db_session, actor=task_actor, participant=owner, scope=TokenScope.MAIN, name="ci"
        )

    assert error.value.details["action"] == "token.issue"


async def test_the_list_never_contains_a_secret(
    db_session: AsyncSession,
    main_actor: Actor,
    main_secret: str,
) -> None:
    """Обзорная проверка 7 на уровне сценария: секрета в хранилище нет вовсе."""
    page = await service.list_tokens(db_session, actor=main_actor)

    assert page.items
    for token in page.items:
        assert main_secret not in token.token_hash
        assert not hasattr(token, "secret")


async def test_revoking_is_idempotent(
    db_session: AsyncSession,
    main_actor: Actor,
    owner: Participant,
) -> None:
    """Клиент, не получивший ответ, повторяет запрос — и не должен получить ошибку."""
    issued = await service.issue_token(
        db_session, actor=main_actor, participant=owner, scope=TokenScope.TASK, name="ci"
    )

    first = await service.revoke_token(db_session, issued.token.id, actor=main_actor)
    second = await service.revoke_token(db_session, issued.token.id, actor=main_actor)

    assert first.revoked_at is not None
    assert second.revoked_at == first.revoked_at


async def test_revoking_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    main_actor: Actor,
    owner: Participant,
) -> None:
    issued = await service.issue_token(
        db_session, actor=main_actor, participant=owner, scope=TokenScope.TASK, name="ci"
    )

    with pytest.raises(PermissionDeniedError):
        await service.revoke_token(db_session, issued.token.id, actor=task_actor)


async def test_revoking_an_unknown_token_is_not_found(
    db_session: AsyncSession,
    main_actor: Actor,
) -> None:
    with pytest.raises(TokenNotFoundError) as error:
        await service.revoke_token(db_session, uuid.uuid4(), actor=main_actor)

    assert error.value.code == "token_not_found"


async def test_a_freshly_issued_token_authenticates(
    db_session: AsyncSession,
    main_actor: Actor,
    owner: Participant,
) -> None:
    """Сквозная проверка выпуска: секрет из ответа действительно открывает вход."""
    issued = await service.issue_token(
        db_session, actor=main_actor, participant=owner, scope=TokenScope.MAIN, name="ci"
    )

    actor = await authenticate(db_session, issued.secret)

    assert actor.scope is TokenScope.MAIN
    assert actor.author.signature == owner.name
