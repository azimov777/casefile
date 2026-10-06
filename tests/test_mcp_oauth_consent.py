"""Кому выдать подключение при входе OAuth: локально — сразу, в сети — страница входа (TRK-450).

Локально (`TRACKER_LOGIN` пуст, порты на петле) `/authorize` согласует сразу и выбирает
участника по клиенту: Claude Code → `claude`, Codex → `codex`, прочие → `agent`,
недостающий заводится сам (`TRK-446#14`). В сети (`TRACKER_LOGIN=password`, адрес по
https) браузер уходит на страницу входа службы mcp: почта и пароль, выбор участника из
своих агентов и агентов без хозяина, по умолчанию `claude_alice` (`TRK-475#14`);
выпускающий — вошедший человек.

Цикл идёт настоящими HTTP-запросами к приложению службы через ASGI, как браузер и клиент.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient, Response
from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from app.core.config import Settings, get_settings
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.repositories import ParticipantRepository
from app.domain.oauth import client_family
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenKind, hash_token
from app.mcp.consent import CSRF_COOKIE, SESSION_COOKIE
from app.mcp.runtime import Runtime, SessionFactory
from app.mcp.server import create_server
from app.services import accounts as accounts_service
from app.services import participants as participants_service
from app.services.auth import TRACKER_ACTOR
from conftest import MCP_BASE_URL
from test_mcp_oauth import (
    ACCEPT,
    INITIALIZE,
    REDIRECT,
    _exchange,
    _initialize,
    _pkce,
    _query,
    _refresh,
    _register,
)

PUBLIC = "https://casefile.example.com"
PUBLIC_MCP = f"{PUBLIC}/mcp"
PASSWORD = "correct horse battery staple"


def _settings(**update: Any) -> Settings:
    return get_settings().model_copy(update=update)


def _local(sessions: SessionFactory, *, bind: str = "127.0.0.1") -> MCPServer:
    settings = _settings(login="local", bind=bind)
    return create_server(runtime=Runtime(sessions=sessions), settings=settings)


def _network(sessions: SessionFactory, *, public_url: str = PUBLIC_MCP) -> MCPServer:
    settings = _settings(login="password", bind="0.0.0.0", mcp_public_url=public_url)
    return create_server(runtime=Runtime(sessions=sessions), settings=settings)


@asynccontextmanager
async def _http(server: MCPServer, base_url: str = MCP_BASE_URL) -> AsyncIterator[AsyncClient]:
    application: Starlette = server.streamable_http_app()
    async with (
        application.router.lifespan_context(application),
        AsyncClient(transport=ASGITransport(app=application), base_url=base_url) as client,
    ):
        yield client


async def _authorize(client: AsyncClient, client_id: str, challenge: str) -> Response:
    return await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st-1",
        },
    )


async def _participant(db_session: AsyncSession, name: str) -> Participant | None:
    return await ParticipantRepository(db_session).get_by_name(name)


async def _token(db_session: AsyncSession, secret: str) -> Token:
    token = await db_session.scalar(select(Token).where(Token.token_hash == hash_token(secret)))
    assert token is not None
    return token


async def _person(db_session: AsyncSession, name: str) -> Participant:
    created = await accounts_service.create_account(
        db_session,
        actor=TRACKER_ACTOR,
        email=f"{name}@example.com",
        name=name,
        password=PASSWORD,
    )
    return created.account.participant


# --- Проверка 1: локальный режим — согласие сразу, участник по клиенту --------------


@pytest.mark.parametrize(
    ("client_name", "expected"),
    [("Claude Code", "claude"), ("Codex", "codex"), ("Cursor", "agent")],
)
async def test_local_sign_in_is_granted_at_once_to_the_participant_of_the_client(
    mcp_sessions: SessionFactory, db_session: AsyncSession, client_name: str, expected: str
) -> None:
    """Правило `TRK-446#14`: участник по клиенту, недостающий заводится сам, без хозяина."""
    assert await _participant(db_session, expected) is None

    async with _http(_local(mcp_sessions)) as client:
        registered = await _register(client, client_name=client_name)
        issued = []
        for _ in range(2):  # второй вход — тот же участник, не новый
            verifier, challenge = _pkce()
            answer = _query(await _authorize(client, registered["client_id"], challenge))
            response = await _exchange(client, registered["client_id"], answer["code"], verifier)
            assert response.status_code == 200, response.text
            issued.append(response.json()["access_token"])
        works = await _initialize(client, issued[-1])  # первое заменено вторым (TRK-560)

    assert works.status_code == 200, works.text
    participant = await _participant(db_session, expected)
    assert participant is not None
    assert participant.kind is ParticipantKind.AGENT
    assert participant.owner_id is None
    for secret in issued:
        token = await _token(db_session, secret)
        assert token.kind is TokenKind.OAUTH
        assert token.participant_id == participant.id
        assert token.created_by_kind.value == "tracker"


def test_the_client_is_known_by_its_document_address_or_its_name() -> None:
    claude = "https://claude.ai/oauth/claude-code-client-metadata"
    codex = "https://chatgpt.com/oauth/codex/abc123/client.json"
    assert client_family(claude, None) == "claude"
    assert client_family(codex, "anything") == "codex"
    assert client_family("3f2c", "Claude Code (casefile)") == "claude"
    assert client_family("3f2c", "codex") == "codex"
    assert client_family("3f2c", "Cursor") == "agent"
    assert client_family("https://example.com/claude-code.json", None) == "agent"


async def test_local_sign_in_does_not_take_the_name_of_a_person(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.HUMAN, name="claude"
    )
    async with _http(_local(mcp_sessions)) as client:
        registered = await _register(client, client_name="Claude Code")
        _, challenge = _pkce()
        answer = _query(await _authorize(client, registered["client_id"], challenge))

    assert answer["error"] == "access_denied"
    assert "code" not in answer


async def test_local_sign_in_is_refused_when_ports_are_published_beyond_loopback(
    mcp_sessions: SessionFactory,
) -> None:
    async with _http(_local(mcp_sessions, bind="0.0.0.0")) as client:
        registered = await _register(client, client_name="Claude Code")
        _, challenge = _pkce()
        answer = _query(await _authorize(client, registered["client_id"], challenge))

    assert answer["error"] == "access_denied"
    assert "CASEFILE_LOGIN=password" in answer["error_description"]


# --- Проверка 2: сетевой режим — страница входа, выбор участника, выпускающий ---------


def _page_fields(page: str) -> dict[str, str]:
    """Скрытые поля формы страницы: параметры запроса и токен CSRF."""
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page))


def _options(page: str) -> dict[str, bool]:
    """Участники на выбор: имя → выбран ли по умолчанию."""
    found = re.findall(r'name="participant" value="([^"]+)"( checked)?', page)
    return {name: bool(mark) for name, mark in found}


async def _to_page(client: AsyncClient) -> tuple[str, str, Response]:
    """Регистрация и `/authorize`: возвращает `client_id`, верификатор PKCE и страницу."""
    registered = await _register(client, client_name="Claude Code")
    verifier, challenge = _pkce()
    authorize = await _authorize(client, registered["client_id"], challenge)
    assert authorize.status_code == 302, authorize.text
    location = authorize.headers["location"]
    assert location.startswith(f"{PUBLIC}/oauth/consent?"), location
    assert "iss=" not in location  # `iss` ставит страница при возврате, не переход на неё
    page = await client.get(location)
    return registered["client_id"], verifier, page


async def _sign_in_on_page(client: AsyncClient, page: Response, email: str) -> Response:
    fields = _page_fields(page.text) | {
        "action": "login",
        "email": email,
        "password": PASSWORD,
    }
    # Браузер шлёт с формой `Origin` своей страницы: при `Referrer-Policy: no-referrer`
    # он был бы `null`, поэтому страница отдаёт `same-origin`.
    assert page.headers["referrer-policy"] == "same-origin"
    signed = await client.post("/oauth/consent", data=fields, headers={"origin": PUBLIC})
    assert signed.status_code == 303, signed.text
    return await client.get(signed.headers["location"])


async def _connect_as(
    client: AsyncClient, email: str, participant: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Весь вход человека в сети: страница, пароль, согласие, обмен кода."""
    client_id, verifier, page = await _to_page(client)
    choice = await _sign_in_on_page(client, page, email)
    fields = _page_fields(choice.text) | {"action": "allow"}
    if participant is not None:
        fields["participant"] = participant
    allowed = await client.post("/oauth/consent", data=fields)
    assert allowed.status_code == 303, allowed.text
    answer = _query_of(allowed)
    response = await _exchange(client, client_id, answer["code"], verifier)
    assert response.status_code == 200, response.text
    return client_id, response.json()


def _query_of(response: Response) -> dict[str, str]:
    location = response.headers["location"]
    assert location.startswith(REDIRECT), location
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


async def test_network_sign_in_goes_through_the_page_and_the_person_issues_the_connection(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    alice = await _person(db_session, "alice")
    bob = await _person(db_session, "bob")
    await participants_service.agent_of(db_session, client="claude", owner=bob)
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )
    assert await _participant(db_session, "claude_alice") is None

    async with _http(_network(mcp_sessions), base_url=PUBLIC) as client:
        client_id, verifier, page = await _to_page(client)
        # Без входа — страница входа, а не код.
        assert page.status_code == 200, page.text
        assert 'name="email"' in page.text and 'name="password"' in page.text
        assert "Claude Code" in page.text
        assert page.cookies.get(CSRF_COOKIE)

        wrong = await client.post(
            "/oauth/consent",
            data=_page_fields(page.text)
            | {"action": "login", "email": "alice@example.com", "password": "not the password"},
        )
        assert wrong.status_code == 401
        assert SESSION_COOKIE not in client.cookies

        choice = await _sign_in_on_page(client, page, "alice@example.com")
        assert choice.status_code == 200, choice.text
        options = _options(choice.text)
        # Свои агенты и агенты без хозяина; `claude_alice` заведён и выбран по умолчанию.
        assert options == {"claude_alice": True, "helper": False}
        assert "claude_bob" not in choice.text

        allowed = await client.post(
            "/oauth/consent", data=_page_fields(choice.text) | {"action": "allow"}
        )
        assert allowed.status_code == 303, allowed.text
        answer = _query_of(allowed)
        assert answer["state"] == "st-1"
        # RFC 9207: ответ со страницы согласия несёт `iss` — issuer метаданных (TRK-483).
        metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert answer["iss"] == metadata["issuer"]
        response = await _exchange(client, client_id, answer["code"], verifier)
        assert response.status_code == 200, response.text
        issued = response.json()
        works = await _initialize(client, issued["access_token"])

    assert works.status_code == 200, works.text
    agent = await _participant(db_session, "claude_alice")
    assert agent is not None and agent.owner_id == alice.id
    token = await _token(db_session, issued["access_token"])
    assert token.kind is TokenKind.OAUTH
    assert token.participant_id == agent.id
    # Выпускающий — вошедший человек: `tokens.created_by` = alice.
    assert token.created_by_kind.value == "human"
    assert token.created_by_signature == "alice"


async def test_network_sign_in_gives_the_chosen_participant_and_never_a_foreign_one(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    await _person(db_session, "alice")
    bob = await _person(db_session, "bob")
    await participants_service.agent_of(db_session, client="claude", owner=bob)
    helper = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )

    async with _http(_network(mcp_sessions), base_url=PUBLIC) as client:
        _, chosen = await _connect_as(client, "alice@example.com", participant="helper")

        # Чужого агента не выбрать и подменой поля формы.
        _, _, page = await _to_page(client)  # кука сеанса уже есть: сразу выбор
        forged = await client.post(
            "/oauth/consent",
            data=_page_fields(page.text) | {"action": "allow", "participant": "claude_bob"},
        )

    token = await _token(db_session, chosen["access_token"])
    assert token.participant_id == helper.id
    assert token.created_by_signature == "alice"
    assert forged.status_code == 303
    refused = _query_of(forged)
    assert refused["error"] == "access_denied"
    assert "code" not in refused


async def test_the_page_refuses_forged_forms_foreign_hosts_and_unknown_clients(
    mcp_sessions: SessionFactory, db_session: AsyncSession, main_secret: str
) -> None:
    await _person(db_session, "alice")
    async with _http(_network(mcp_sessions), base_url=PUBLIC) as client:
        _, _, page = await _to_page(client)
        fields = _page_fields(page.text) | {
            "action": "login",
            "email": "alice@example.com",
            "password": PASSWORD,
        }
        without_csrf = await client.post("/oauth/consent", data=fields | {"csrf": "forged"})
        foreign_origin = await client.post(
            "/oauth/consent", data=fields, headers={"origin": "https://evil.example"}
        )
        foreign_host = await client.get(
            "/oauth/consent", params=_page_fields(page.text), headers={"host": "evil.example"}
        )
        unknown_client = await client.get(
            "/oauth/consent", params=_page_fields(page.text) | {"client_id": "nobody"}
        )
        foreign_redirect = await client.get(
            "/oauth/consent",
            params=_page_fields(page.text) | {"redirect_uri": "https://evil.example/cb"},
        )
        denied = await client.post("/oauth/consent", data=fields | {"action": "deny"})
        metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
        # Эндпоинт MCP в сети тоже отвечает только на своём узле (allowed hosts).
        mcp_foreign_host = await client.post(
            "/mcp",
            json=INITIALIZE,
            headers=ACCEPT | {"host": "evil.example", "authorization": f"Bearer {main_secret}"},
        )

    assert mcp_foreign_host.status_code == 421
    assert without_csrf.status_code == 403
    assert foreign_origin.status_code == 403
    assert foreign_host.status_code == 400
    assert unknown_client.status_code == 400
    # Незарегистрированный адрес возврата — страница ошибки, никакого перенаправления.
    assert foreign_redirect.status_code == 400
    assert "location" not in foreign_redirect.headers
    assert SESSION_COOKIE not in client.cookies
    assert _query_of(denied)["error"] == "access_denied"
    assert _query_of(denied)["iss"] == metadata["issuer"]


async def test_network_sign_in_is_not_served_over_http_outside_loopback(
    mcp_sessions: SessionFactory,
) -> None:
    """http вне петли: сервера авторизации и страницы нет — только токен в заголовке."""
    server = _network(mcp_sessions, public_url="http://casefile.example.com/mcp")
    async with _http(server, base_url="http://casefile.example.com") as client:
        authorize = await client.get("/authorize")
        page = await client.get("/oauth/consent")
        registered = await client.post("/register", json={"redirect_uris": [REDIRECT]})

    assert authorize.status_code == 404
    assert page.status_code == 404
    assert registered.status_code == 404


# --- Проверка 3: своё видит и отзывает, отключение отрезает подключение ---------------


async def _bearer(client: AsyncClient, email: str) -> dict[str, str]:
    """Сеанс человека, как у вкладки интерфейса: вход почтой и паролем через REST."""
    response = await client.post("/api/v1/session", json={"email": email, "password": PASSWORD})
    assert response.status_code in {200, 201}, response.text
    return {"Authorization": f"Bearer {response.json()['data']['token']}"}


async def test_a_connection_is_seen_by_its_person_and_the_admin_and_dies_with_the_account(
    mcp_sessions: SessionFactory, db_session: AsyncSession, client: AsyncClient, main_secret: str
) -> None:
    alice = await _person(db_session, "alice")
    await _person(db_session, "bob")
    admin = {"Authorization": f"Bearer {main_secret}"}

    async with _http(_network(mcp_sessions), base_url=PUBLIC) as mcp:
        client_id, issued = await _connect_as(mcp, "alice@example.com")
        token = await _token(db_session, issued["access_token"])

        def ids(response: Response) -> set[str]:
            assert response.status_code == 200, response.text
            return {row["id"] for row in response.json()["data"]}

        listing = {"limit": 100}
        seen_by_bob = ids(
            await client.get(
                "/api/v1/tokens", params=listing, headers=await _bearer(client, "bob@example.com")
            )
        )
        seen_by_alice = ids(
            await client.get(
                "/api/v1/tokens", params=listing, headers=await _bearer(client, "alice@example.com")
            )
        )
        seen_by_admin = ids(await client.get("/api/v1/tokens", params=listing, headers=admin))

        account = await accounts_service.account_of(db_session, alice)
        assert account is not None
        disabled = await client.patch(
            f"/api/v1/accounts/{account.id}", json={"disabled": True}, headers=admin
        )
        assert disabled.status_code == 200, disabled.text

        refused = await _initialize(mcp, issued["access_token"])
        refresh = await _refresh(mcp, client_id, issued["refresh_token"])

    assert str(token.id) not in seen_by_bob
    assert str(token.id) in seen_by_alice
    assert str(token.id) in seen_by_admin
    assert refused.status_code == 401
    assert refused.json()["details"] == {"reason": "token_revoked"}
    assert refresh.status_code == 400
    assert refresh.json()["error"] == "invalid_grant"


# --- Проверка 4: метаданные за прокси с TLS -------------------------------------------


async def test_metadata_behind_a_tls_proxy_names_the_public_https_address(
    mcp_sessions: SessionFactory,
) -> None:
    async with _http(_network(mcp_sessions), base_url=PUBLIC) as client:
        server = (await client.get("/.well-known/oauth-authorization-server")).json()
        resource = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
        challenge = (await client.post("/mcp", json={})).headers["www-authenticate"]

    assert server["issuer"].rstrip("/") == PUBLIC
    assert server["authorization_endpoint"] == f"{PUBLIC}/authorize"
    assert server["token_endpoint"] == f"{PUBLIC}/token"
    assert resource["resource"] == PUBLIC_MCP
    assert [url.rstrip("/") for url in resource["authorization_servers"]] == [PUBLIC]
    assert f'resource_metadata="{PUBLIC}/.well-known/oauth-protected-resource/mcp"' in challenge
