"""Локальный режим: подключения и ключи, выданные установкой, — на человека машины (TRK-559).

Новый вход OAuth пишет выпускающим человека с ключом `local-ui`; подъём `local-token`
переносит на него уже выданное; ключ `local-agent` выпускает он же. Сетевой режим
(`password`) ничего не переносит. Вход идёт настоящими запросами к MCP, список «своих» —
настоящим `GET /api/v1/tokens?mine=true`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_mcp_oauth import (
    _http,
    _initialize,
    _log_in_again,
    _refresh,
    _server,
    _sign_in,
    _stored,
)

from app import cli
from app.core.config import get_settings
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.session import transaction
from app.domain.authors import AuthorKind
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenKind
from app.mcp.runtime import SessionFactory
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from app.services.setup import (
    DEFAULT_LOCAL_TOKEN_NAME,
    ensure_agent_token,
    ensure_local_token,
)

TOKENS = "/api/v1/tokens"


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


@pytest.fixture
async def ui_secret(db_session: AsyncSession, owner: Participant) -> str:
    """Ключ интерфейса машины у владельца: по нему установка узнаёт человека машины."""
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        name=DEFAULT_LOCAL_TOKEN_NAME,
        kind=TokenKind.SESSION,
    )
    return issued.secret


async def _agent(session: AsyncSession, name: str) -> Participant:
    return await participants_service.register_participant(
        session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.AGENT,
        name=name,
        description="тест",
    )


async def _by_tracker(
    session: AsyncSession, agent: Participant, kind: TokenKind, name: str
) -> Token:
    issued = await tokens_service.issue_token(
        session, actor=TRACKER_ACTOR, participant=agent, name=name, kind=kind
    )
    return issued.token


async def test_a_local_sign_in_is_issued_by_the_person_and_listed_as_theirs(
    mcp_sessions: SessionFactory,
    db_session: AsyncSession,
    owner: Participant,
    ui_secret: str,
    client: AsyncClient,
) -> None:
    async with _http(_server(mcp_sessions)) as mcp:
        client_id, first = await _sign_in(mcp)
        renewed = await _refresh(mcp, client_id, first["refresh_token"])
        assert renewed.status_code == 200, renewed.text
        new_secret = renewed.json()["access_token"]
        assert (await _initialize(mcp, new_secret)).status_code == 200

    issued = await _stored(db_session, first["access_token"])
    assert issued.created_by == owner.author
    # Продление наследует выпускающего: тот же человек.
    assert (await _stored(db_session, new_secret)).created_by == owner.author

    listed = await client.get(TOKENS, params={"mine": "true"}, headers=bearer(ui_secret))
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["data"]}
    assert str(issued.id) in ids


async def test_the_second_sign_in_still_replaces_the_previous_connection(
    mcp_sessions: SessionFactory, db_session: AsyncSession, owner: Participant, ui_secret: str
) -> None:
    """Правило TRK-560 не зависит от того, кто выпускает."""
    async with _http(_server(mcp_sessions)) as mcp:
        client_id, first = await _sign_in(mcp)
        second = await _log_in_again(mcp, client_id)
    assert (await _stored(db_session, first["access_token"])).revoked_at is not None
    live = await _stored(db_session, second["access_token"])
    assert live.revoked_at is None and live.created_by == owner.author


async def test_without_a_person_the_tracker_issues(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    async with _http(_server(mcp_sessions)) as mcp:
        _, issued = await _sign_in(mcp)
    token = await _stored(db_session, issued["access_token"])
    assert token.created_by.kind is AuthorKind.TRACKER


async def test_the_lift_moves_live_connections_and_keys_to_the_person(
    db_session: AsyncSession, owner: Participant
) -> None:
    agent = await _agent(db_session, "claude")
    live_oauth = await _by_tracker(db_session, agent, TokenKind.OAUTH, "oauth: Claude Code")
    live_key = await _by_tracker(db_session, agent, TokenKind.KEY, "local-agent")
    dead = await _by_tracker(db_session, agent, TokenKind.OAUTH, "old")
    await tokens_service.revoke_token(db_session, dead.id, actor=TRACKER_ACTOR)
    session_token = await _by_tracker(db_session, agent, TokenKind.SESSION, "browser")

    result = await ensure_local_token(db_session, known_secret=None, adopt_connections=True)
    for token in (live_oauth, live_key, dead, session_token):
        await db_session.refresh(token)

    assert result.token.participant == owner
    assert live_oauth.created_by == owner.author
    assert live_key.created_by == owner.author
    assert dead.created_by.kind is AuthorKind.TRACKER
    assert session_token.created_by.kind is AuthorKind.TRACKER
    # Хозяина агента перенос не трогает.
    assert agent.author.signature == "claude"

    again = await ensure_local_token(db_session, known_secret=result.secret, adopt_connections=True)
    assert again.secret is None
    assert await _count_by_tracker(db_session) == 3  # отозванный, сеанс и сам ключ local-ui


async def _count_by_tracker(session: AsyncSession) -> int:
    rows = await session.scalars(select(Token).where(Token.created_by_kind == AuthorKind.TRACKER))
    return len(rows.unique().all())


async def test_without_the_flag_nothing_is_moved(
    db_session: AsyncSession, owner: Participant
) -> None:
    agent = await _agent(db_session, "claude")
    token = await _by_tracker(db_session, agent, TokenKind.OAUTH, "oauth: Claude Code")

    await ensure_local_token(db_session, known_secret=None)
    await db_session.refresh(token)

    assert token.created_by.kind is AuthorKind.TRACKER


async def test_the_commands_follow_the_login_mode(
    db_session: AsyncSession,
    owner: Participant,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        await db_session.commit()
        async with transaction(db_session):
            yield db_session

    monkeypatch.setattr(cli, "session_scope", scope)
    agent = await _agent(db_session, "codex")
    token = await _by_tracker(db_session, agent, TokenKind.OAUTH, "oauth: Codex")

    def mode(login: str) -> None:
        settings = get_settings().model_copy(update={"login": login})
        monkeypatch.setattr(cli, "get_settings", lambda: settings)

    parser = cli._build_parser()
    mode("password")
    await cli._local_token(parser.parse_args(["local-token", "--output", str(tmp_path / "ui")]))
    await db_session.refresh(token)
    assert token.created_by.kind is AuthorKind.TRACKER
    await cli._agent_token(parser.parse_args(["agent-token", "--output", str(tmp_path / "a1")]))
    assert await _local_agent_issuer(db_session) is AuthorKind.TRACKER

    mode("local")
    await cli._local_token(parser.parse_args(["local-token", "--output", str(tmp_path / "ui2")]))
    await db_session.refresh(token)
    assert token.created_by == owner.author
    await cli._agent_token(parser.parse_args(["agent-token", "--output", str(tmp_path / "a2")]))
    assert await _local_agent_issuer(db_session) is AuthorKind.HUMAN


async def _local_agent_issuer(session: AsyncSession) -> AuthorKind:
    rows = await session.scalars(
        select(Token).where(Token.name == "local-agent", Token.revoked_at.is_(None))
    )
    return rows.unique().one().created_by_kind


async def test_the_local_agent_key_is_issued_by_the_person(
    db_session: AsyncSession, owner: Participant, ui_secret: str
) -> None:
    result = await ensure_agent_token(db_session, known_secret=None, issued_by_person=True)
    assert result.token.created_by == owner.author

    plain = await ensure_agent_token(db_session, known_secret=None)
    assert plain.token.created_by.kind is AuthorKind.TRACKER
