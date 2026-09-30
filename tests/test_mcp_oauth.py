"""Вход агента через OAuth 2.1 в службе mcp (TRK-448): DCR, PKCE S256, `/token`, refresh.

Цикл проходится настоящими HTTP-запросами к приложению службы через ASGI, как его
прошёл бы Claude Code или Codex: регистрация, `/authorize`, `/token`, `tools/list`
выданным токеном. Сервер собирается с включённым временным правилом согласия
(`TRACKER_OAUTH_LOCAL_CONSENT`): без него `/authorize` отказывает, и это проверено
отдельно.
"""

import base64
import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient, Response
from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from app.core.config import Settings, get_settings
from app.db.models.oauth import OAuthCode, OAuthRefreshToken
from app.db.models.token import Token
from app.domain.tokens import TokenKind, hash_token
from app.mcp.runtime import Runtime, SessionFactory
from app.mcp.server import create_server
from conftest import MCP_BASE_URL, connect_mcp

REDIRECT = "http://127.0.0.1:43117/callback"
ACCEPT = {"accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "tests", "version": "0"},
    },
}


def _settings(
    *, consent: bool = True, public_url: str | None = None, ttl: timedelta | None = None
) -> Settings:
    update: dict[str, Any] = {"oauth_local_consent": consent}
    if public_url is not None:
        update["mcp_public_url"] = public_url
    if ttl is not None:
        update["oauth_access_ttl"] = ttl
    return get_settings().model_copy(update=update)


def _server(sessions: SessionFactory, **settings: Any) -> MCPServer:
    return create_server(runtime=Runtime(sessions=sessions), settings=_settings(**settings))


@asynccontextmanager
async def _http(server: MCPServer) -> AsyncIterator[AsyncClient]:
    application: Starlette = server.streamable_http_app()
    async with (
        application.router.lifespan_context(application),
        AsyncClient(transport=ASGITransport(app=application), base_url=MCP_BASE_URL) as client,
    ):
        yield client


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _register(client: AsyncClient, **metadata: Any) -> dict[str, Any]:
    body = {
        "redirect_uris": [REDIRECT],
        "client_name": "Codex",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    } | metadata
    response = await client.post("/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _authorize(
    client: AsyncClient, client_id: str, challenge: str, *, redirect: str = REDIRECT
) -> Response:
    return await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st-1",
        },
    )


def _query(response: Response) -> dict[str, str]:
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(REDIRECT), location
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


async def _exchange(
    client: AsyncClient, client_id: str, code: str, verifier: str, *, redirect: str = REDIRECT
) -> Response:
    return await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


async def _refresh(client: AsyncClient, client_id: str, refresh: str) -> Response:
    return await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id},
    )


async def _sign_in(client: AsyncClient) -> tuple[str, dict[str, Any]]:
    """Полный вход: регистрация, код, обмен. Возвращает `client_id` и ответ `/token`."""
    registered = await _register(client)
    verifier, challenge = _pkce()
    code = _query(await _authorize(client, registered["client_id"], challenge))["code"]
    response = await _exchange(client, registered["client_id"], code, verifier)
    assert response.status_code == 200, response.text
    return registered["client_id"], response.json()


async def _initialize(client: AsyncClient, secret: str) -> Response:
    return await client.post(
        "/mcp", headers=ACCEPT | {"authorization": f"Bearer {secret}"}, json=INITIALIZE
    )


# --- Проверка 1: полный цикл и отказы -----------------------------------------------


async def test_full_cycle_gives_a_participant_token_that_lists_tools(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    """DCR → `/authorize` с PKCE S256 → `/token` → `tools/list` выданным токеном."""
    server = _server(mcp_sessions)
    async with _http(server) as client:
        metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert metadata["code_challenge_methods_supported"] == ["S256"]

        registered = await _register(client)
        # Клиент публичный: секрета нет ни в ответе, ни в базе (TRK-448#9).
        assert registered["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in registered

        verifier, challenge = _pkce()
        answer = _query(await _authorize(client, registered["client_id"], challenge))
        assert answer["state"] == "st-1"
        assert answer["code"].startswith("trc_")

        response = await _exchange(client, registered["client_id"], answer["code"], verifier)
        assert response.status_code == 200, response.text
        issued = response.json()

    assert issued["access_token"].startswith("trk_")
    assert issued["refresh_token"].startswith("trr_")
    assert issued["token_type"].lower() == "bearer"
    ttl = _settings().oauth_access_ttl
    assert issued["expires_in"] == int(ttl.total_seconds())

    # Подключение, а не ключ: вид `oauth`, срок, участник `agent`.
    token = await db_session.scalar(
        select(Token).where(Token.token_hash == hash_token(issued["access_token"]))
    )
    assert token is not None
    assert token.kind is TokenKind.OAUTH
    assert token.expires_at is not None
    # `created_at` — время начала транзакции теста, срок — время выпуска: разница мала.
    assert abs(token.expires_at - token.created_at - ttl) < timedelta(minutes=1)
    assert token.participant is not None and token.participant.name == "agent"
    assert token.name == "oauth: Codex"

    # Код и refresh — только хешем.
    assert (
        await db_session.scalar(select(OAuthCode).where(OAuthCode.code_hash == answer["code"]))
        is None
    )
    assert await db_session.scalar(
        select(OAuthCode).where(OAuthCode.code_hash == hash_token(answer["code"]))
    )
    assert await db_session.scalar(
        select(OAuthRefreshToken).where(
            OAuthRefreshToken.token_hash == hash_token(issued["refresh_token"])
        )
    )

    async with connect_mcp(server, issued["access_token"]) as session:
        listed = await session.list_tools()
    names = {tool.name for tool in listed.tools}
    assert {"get_task", "create_task"} <= names


async def test_the_access_ttl_setting_sets_expires_in_and_the_deadline(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    """`TRACKER_OAUTH_ACCESS_TTL` владельца установки — час: `expires_in` 3600 и срок в базе."""
    async with _http(_server(mcp_sessions, ttl=timedelta(hours=1))) as client:
        _, issued = await _sign_in(client)

    assert issued["expires_in"] == 3600
    token = await db_session.scalar(
        select(Token).where(Token.token_hash == hash_token(issued["access_token"]))
    )
    assert token is not None and token.expires_at is not None
    assert abs(token.expires_at - token.created_at - timedelta(hours=1)) < timedelta(minutes=1)


def test_the_access_ttl_defaults_to_thirty_days_and_reads_iso_durations() -> None:
    assert Settings.model_fields["oauth_access_ttl"].default == timedelta(days=30)
    for value, ttl in (("PT1H", timedelta(hours=1)), ("P7D", timedelta(days=7))):
        assert Settings(**{"oauth_access_ttl": value}).oauth_access_ttl == ttl


async def test_a_wrong_code_verifier_is_refused(mcp_sessions: SessionFactory) -> None:
    async with _http(_server(mcp_sessions)) as client:
        registered = await _register(client)
        _, challenge = _pkce()
        code = _query(await _authorize(client, registered["client_id"], challenge))["code"]
        response = await _exchange(client, registered["client_id"], code, "x" * 50)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_a_code_is_single_use_and_its_replay_revokes_the_token(
    mcp_sessions: SessionFactory,
) -> None:
    """Повтор кода отказывает и отзывает токен, выданный по нему (RFC 6749 §10.5)."""
    async with _http(_server(mcp_sessions)) as client:
        registered = await _register(client)
        verifier, challenge = _pkce()
        code = _query(await _authorize(client, registered["client_id"], challenge))["code"]
        first = await _exchange(client, registered["client_id"], code, verifier)
        assert first.status_code == 200, first.text
        second = await _exchange(client, registered["client_id"], code, verifier)
        replayed = await _initialize(client, first.json()["access_token"])

    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"
    assert replayed.status_code == 401
    assert replayed.json()["details"] == {"reason": "token_revoked"}


async def test_an_expired_code_is_refused(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    async with _http(_server(mcp_sessions)) as client:
        registered = await _register(client)
        verifier, challenge = _pkce()
        code = _query(await _authorize(client, registered["client_id"], challenge))["code"]
        row = await db_session.scalar(
            select(OAuthCode).where(OAuthCode.code_hash == hash_token(code))
        )
        assert row is not None
        row.expires_at = row.created_at.replace(year=2000)
        await db_session.commit()
        response = await _exchange(client, registered["client_id"], code, verifier)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_a_foreign_redirect_uri_is_refused(mcp_sessions: SessionFactory) -> None:
    """Адрес возврата сверяется точно: на `/authorize` и при обмене."""
    other = "http://127.0.0.1:43117/elsewhere"
    async with _http(_server(mcp_sessions)) as client:
        registered = await _register(client)
        verifier, challenge = _pkce()
        at_authorize = await _authorize(client, registered["client_id"], challenge, redirect=other)
        code = _query(await _authorize(client, registered["client_id"], challenge))["code"]
        at_token = await _exchange(client, registered["client_id"], code, verifier, redirect=other)

    assert at_authorize.status_code == 400
    assert at_authorize.json()["error"] == "invalid_request"
    assert at_token.status_code == 400
    assert at_token.json()["error"] == "invalid_request"


async def test_a_code_of_another_client_is_refused(mcp_sessions: SessionFactory) -> None:
    async with _http(_server(mcp_sessions)) as client:
        mine = await _register(client)
        theirs = await _register(client, client_name="Other")
        verifier, challenge = _pkce()
        code = _query(await _authorize(client, mine["client_id"], challenge))["code"]
        response = await _exchange(client, theirs["client_id"], code, verifier)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_http_outside_loopback_is_refused_at_registration(
    mcp_sessions: SessionFactory,
) -> None:
    async with _http(_server(mcp_sessions)) as client:
        response = await client.post(
            "/register",
            json={
                "redirect_uris": ["http://evil.example/callback"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_a_client_asking_for_a_secret_is_registered_public(
    mcp_sessions: SessionFactory,
) -> None:
    """Секрет клиента не выдаётся и не хранится: метод заменён на `none` (TRK-448#9)."""
    async with _http(_server(mcp_sessions)) as client:
        registered = await _register(client, token_endpoint_auth_method="client_secret_post")
        verifier, challenge = _pkce()
        code = _query(await _authorize(client, registered["client_id"], challenge))["code"]
        response = await _exchange(client, registered["client_id"], code, verifier)

    assert registered["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in registered
    assert response.status_code == 200, response.text


async def test_without_local_consent_authorize_is_denied(mcp_sessions: SessionFactory) -> None:
    """По умолчанию согласия без страницы нет: `access_denied` на адрес возврата."""
    async with _http(_server(mcp_sessions, consent=False)) as client:
        registered = await _register(client)
        _, challenge = _pkce()
        answer = _query(await _authorize(client, registered["client_id"], challenge))

    assert answer["error"] == "access_denied"
    assert "code" not in answer


async def test_consent_is_not_given_to_a_redirect_off_loopback(
    mcp_sessions: SessionFactory,
) -> None:
    https = "https://client.example/callback"
    async with _http(_server(mcp_sessions)) as client:
        registered = await _register(client, redirect_uris=[https])
        _, challenge = _pkce()
        response = await _authorize(client, registered["client_id"], challenge, redirect=https)

    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == ["access_denied"]


async def test_plain_http_outside_loopback_keeps_the_resource_without_authorization(
    mcp_sessions: SessionFactory, main_secret: str
) -> None:
    """Установка в сети по http поднимается: без `/authorize`, токен в заголовке работает."""
    server = _server(mcp_sessions, public_url="http://192.168.1.20:8100/mcp")
    async with _http(server) as client:
        authorize = await client.get("/authorize")
        works = await _initialize(client, main_secret)

    assert authorize.status_code == 404
    assert works.status_code == 200, works.text


# --- Проверка 2: refresh, перезапуск, отзыв -----------------------------------------


async def test_refresh_rotates_the_pair_and_retires_the_previous_token(
    mcp_sessions: SessionFactory,
) -> None:
    async with _http(_server(mcp_sessions)) as client:
        client_id, first = await _sign_in(client)
        response = await _refresh(client, client_id, first["refresh_token"])
        assert response.status_code == 200, response.text
        second = response.json()
        old = await _initialize(client, first["access_token"])
        new = await _initialize(client, second["access_token"])

    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]
    assert old.status_code == 401
    assert new.status_code == 200, new.text


async def test_an_expired_connection_is_refused_and_its_refresh_gives_a_new_pair(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    """Срок вышел: `401 token_expired` на `/mcp`; refresh даёт рабочую пару и отзывает старую."""
    async with _http(_server(mcp_sessions)) as client:
        client_id, first = await _sign_in(client)
        token = await db_session.scalar(
            select(Token).where(Token.token_hash == hash_token(first["access_token"]))
        )
        assert token is not None
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()

        expired = await _initialize(client, first["access_token"])
        refreshed = await _refresh(client, client_id, first["refresh_token"])
        assert refreshed.status_code == 200, refreshed.text
        second = refreshed.json()
        works = await _initialize(client, second["access_token"])

    assert expired.status_code == 401
    assert expired.json()["details"] == {"reason": "token_expired"}
    assert "token_expired" in expired.headers["www-authenticate"]
    assert second["access_token"] != first["access_token"]
    assert second["expires_in"] == first["expires_in"]
    assert works.status_code == 200, works.text
    await db_session.refresh(token)
    assert token.revoked_at is not None
    renewed = await db_session.scalar(
        select(Token).where(Token.token_hash == hash_token(second["access_token"]))
    )
    assert renewed is not None
    assert renewed.kind is TokenKind.OAUTH
    assert renewed.expires_at is not None and renewed.expires_at > datetime.now(UTC)


async def test_a_replayed_refresh_token_revokes_the_whole_chain(
    mcp_sessions: SessionFactory,
) -> None:
    """Погашенный refresh предъявлен снова — признак кражи: цепочка отзывается целиком."""
    async with _http(_server(mcp_sessions)) as client:
        client_id, first = await _sign_in(client)
        second = (await _refresh(client, client_id, first["refresh_token"])).json()
        replay = await _refresh(client, client_id, first["refresh_token"])
        current = await _initialize(client, second["access_token"])
        after = await _refresh(client, client_id, second["refresh_token"])

    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    assert current.status_code == 401
    assert after.status_code == 400


async def test_a_restarted_service_keeps_the_client_and_the_refresh_token(
    mcp_sessions: SessionFactory,
) -> None:
    """Клиенты, коды и refresh живут в базе: новый экземпляр службы их знает."""
    async with _http(_server(mcp_sessions)) as client:
        client_id, first = await _sign_in(client)
        registered_again = await _register(client)  # второй клиент — до «перезапуска»
        verifier, challenge = _pkce()
        code = _query(await _authorize(client, registered_again["client_id"], challenge))["code"]

    async with _http(_server(mcp_sessions)) as client:
        refreshed = await _refresh(client, client_id, first["refresh_token"])
        exchanged = await _exchange(client, registered_again["client_id"], code, verifier)
        assert refreshed.status_code == 200, refreshed.text
        works = await _initialize(client, refreshed.json()["access_token"])

    assert exchanged.status_code == 200, exchanged.text
    assert works.status_code == 200, works.text


async def test_revoking_through_the_tokens_registry_cuts_the_client_off(
    mcp_sessions: SessionFactory,
    auth_client: AsyncClient,
) -> None:
    """Отзыв в «Доступах» (`DELETE /api/v1/tokens/{id}`): `401 token_revoked`, refresh мёртв."""
    async with _http(_server(mcp_sessions)) as client:
        client_id, issued = await _sign_in(client)

        listed = (await auth_client.get("/api/v1/tokens", params={"limit": 100})).json()["data"]
        mine = [row for row in listed if row["name"] == "oauth: Codex" and not row["revoked_at"]]
        assert len(mine) == 1, listed
        assert mine[0]["kind"] == "oauth"
        assert mine[0]["expires_at"] is not None
        revoked = await auth_client.delete(f"/api/v1/tokens/{mine[0]['id']}")
        assert revoked.status_code == 204, revoked.text

        refused = await _initialize(client, issued["access_token"])
        refresh = await _refresh(client, client_id, issued["refresh_token"])

    assert refused.status_code == 401
    assert refused.json()["details"] == {"reason": "token_revoked"}
    assert "resource_metadata=" in refused.headers["www-authenticate"]
    assert refresh.status_code == 400
    assert refresh.json()["error"] == "invalid_grant"


@pytest.mark.parametrize("secret", ["", "   "])
async def test_an_empty_bearer_still_gets_the_plain_challenge(
    mcp_sessions: SessionFactory, secret: str
) -> None:
    async with _http(_server(mcp_sessions)) as client:
        response = await client.post(
            "/mcp", headers=ACCEPT | {"authorization": f"Bearer {secret}"}, json=INITIALIZE
        )

    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]
