"""Клиент по документу метаданных (CIMD) и адрес возврата на петле без порта (TRK-449).

Сеть подменена целиком: `ClientDocuments(resolve=…, request=…)` отвечает документами
Claude Code и Codex, снятыми с их адресов 2026-10-01, и считает походы. Цикл входа идёт
настоящими HTTP-запросами к приложению службы через ASGI, как в `test_mcp_oauth.py`.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient, Response
from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from app.core.config import get_settings
from app.db.models.oauth import OAuthClient
from app.db.models.token import Token
from app.domain.client_documents import (
    DOCUMENT_MAX_BYTES,
    DOCUMENT_MAX_LIFETIME,
    DOCUMENT_MIN_LIFETIME,
    check_document_url,
    client_from_document,
    document_lifetime,
    is_public_address,
)
from app.domain.oauth import OAuthRefusal, redirect_matches
from app.domain.tokens import hash_token
from app.mcp.runtime import Runtime, SessionFactory
from app.mcp.server import create_server
from app.services import client_documents as documents_module
from app.services import oauth as oauth_service
from app.services.client_documents import ClientDocuments, DocumentRequest, DocumentResponse
from conftest import MCP_BASE_URL

CLAUDE_ID = "https://claude.ai/oauth/claude-code-client-metadata"
CLAUDE_DOCUMENT = {
    "client_id": CLAUDE_ID,
    "client_name": "Claude Code",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}
CODEX_ID = "https://chatgpt.com/oauth/codex/htDlQS7jDKJy/client.json"
CODEX_DOCUMENT = {
    "client_id": CODEX_ID,
    "client_uri": "https://chatgpt.com/codex",
    "application_type": "native",
    "redirect_uris": [
        "http://127.0.0.1/callback/htDlQS7jDKJy",
        "http://localhost/callback/htDlQS7jDKJy",
    ],
    "token_endpoint_auth_method": "none",
    "token_endpoint_auth_methods_supported": ["none"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "client_name": "Codex",
    "logo_uri": "https://persistent.oaistatic.com/sonic/misc/openai-logo.png",
}
PUBLIC_ADDRESS = "160.79.104.10"
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


# --- Подменённая сеть ----------------------------------------------------------------


@dataclass
class FakeNetwork:
    """DNS и HTTPS клиента: адреса по имени, ответ по пути, журнал походов."""

    addresses: dict[str, list[str]] = field(default_factory=dict)
    responses: dict[str, DocumentResponse] = field(default_factory=dict)
    resolved: list[str] = field(default_factory=list)
    requests: list[DocumentRequest] = field(default_factory=list)

    def serve(self, url: str, document: object, **headers: str) -> None:
        parts = urlsplit(url)
        self.addresses.setdefault(parts.hostname or "", [PUBLIC_ADDRESS])
        self.responses[parts.path] = DocumentResponse(
            status=200,
            headers={"content-type": "application/json"} | headers,
            body=json.dumps(document).encode(),
        )

    async def resolve(self, host: str, port: int) -> list[str]:
        assert port == 443
        self.resolved.append(host)
        return self.addresses.get(host, [])

    async def request(self, request: DocumentRequest) -> DocumentResponse:
        self.requests.append(request)
        return self.responses[request.target]

    def documents(self) -> ClientDocuments:
        return ClientDocuments(resolve=self.resolve, request=self.request)


@pytest.fixture
def network() -> FakeNetwork:
    fake = FakeNetwork()
    fake.serve(CLAUDE_ID, CLAUDE_DOCUMENT, **{"cache-control": "public, max-age=300"})
    fake.serve(CODEX_ID, CODEX_DOCUMENT)
    return fake


def _server(sessions: SessionFactory, network: FakeNetwork) -> MCPServer:
    settings = get_settings().model_copy(update={"oauth_local_consent": True})
    runtime = Runtime(sessions=sessions, documents=network.documents())
    return create_server(runtime=runtime, settings=settings)


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


async def _authorize(
    client: AsyncClient, client_id: str, challenge: str, redirect: str
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
            "scope": "casefile",
        },
    )


def _code(response: Response, redirect: str) -> str:
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(redirect), location
    query = parse_qs(urlsplit(location).query)
    assert "error" not in query, query
    return query["code"][0]


async def _exchange(
    client: AsyncClient, client_id: str, code: str, verifier: str, redirect: str
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


async def _sign_in(client: AsyncClient, client_id: str, redirect: str) -> dict[str, Any]:
    verifier, challenge = _pkce()
    code = _code(await _authorize(client, client_id, challenge, redirect), redirect)
    response = await _exchange(client, client_id, code, verifier, redirect)
    assert response.status_code == 200, response.text
    return response.json()


# --- Проверка 1: CIMD — полный цикл и отказы -----------------------------------------


async def test_metadata_advertise_client_documents_and_public_clients(
    mcp_sessions: SessionFactory, network: FakeNetwork
) -> None:
    """Без `none` в методах Codex отказывается от CIMD (TRK-432#6)."""
    async with _http(_server(mcp_sessions, network)) as client:
        metadata = (await client.get("/.well-known/oauth-authorization-server")).json()

    assert metadata["client_id_metadata_document_supported"] is True
    assert "none" in metadata["token_endpoint_auth_methods_supported"]
    assert metadata["registration_endpoint"].endswith("/register")  # DCR остаётся
    assert metadata["code_challenge_methods_supported"] == ["S256"]


@pytest.mark.parametrize(
    ("client_id", "redirect", "name"),
    [
        (CLAUDE_ID, "http://localhost:54822/callback", "Claude Code"),
        (CODEX_ID, "http://127.0.0.1:61234/callback/htDlQS7jDKJy", "Codex"),
    ],
)
async def test_a_document_client_signs_in_without_registration(
    mcp_sessions: SessionFactory,
    db_session: AsyncSession,
    network: FakeNetwork,
    client_id: str,
    redirect: str,
    name: str,
) -> None:
    """https-`client_id` → документ → `/authorize` с портом на петле → `/token` → `initialize`."""
    async with _http(_server(mcp_sessions, network)) as client:
        issued = await _sign_in(client, client_id, redirect)
        works = await client.post(
            "/mcp",
            headers=ACCEPT | {"authorization": f"Bearer {issued['access_token']}"},
            json=INITIALIZE,
        )

    assert works.status_code == 200, works.text
    assert issued["access_token"].startswith("trk_")
    assert issued["refresh_token"].startswith("trr_")
    token = await db_session.scalar(
        select(Token).where(Token.token_hash == hash_token(issued["access_token"]))
    )
    assert token is not None and token.name == f"oauth: {name}"

    # Документ скачан один раз на весь вход и запомнен строкой клиента.
    host = urlsplit(client_id).hostname
    assert network.resolved == [host]
    assert [(r.address, r.host, r.port) for r in network.requests] == [(PUBLIC_ADDRESS, host, 443)]
    row = await db_session.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    assert row is not None and row.document_expires_at is not None
    assert row.client_metadata["token_endpoint_auth_method"] == "none"


async def test_a_document_client_refreshes_its_token(
    mcp_sessions: SessionFactory, network: FakeNetwork
) -> None:
    redirect = "http://127.0.0.1:50000/callback"
    async with _http(_server(mcp_sessions, network)) as client:
        issued = await _sign_in(client, CLAUDE_ID, redirect)
        response = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "client_id": CLAUDE_ID,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"] != issued["access_token"]


@pytest.mark.parametrize(
    "client_id",
    [
        "http://claude.ai/oauth/claude-code-client-metadata",
        "https://10.0.0.7/client.json",
        "https://127.0.0.1/client.json",
        "https://[::1]/client.json",
        "https://169.254.169.254/latest/meta-data",
        "https://claude.ai:8443/oauth/claude-code-client-metadata",
    ],
)
async def test_a_document_url_off_the_public_https_is_refused_without_a_request(
    mcp_sessions: SessionFactory, network: FakeNetwork, client_id: str
) -> None:
    async with _http(_server(mcp_sessions, network)) as client:
        _, challenge = _pkce()
        response = await _authorize(client, client_id, challenge, "http://127.0.0.1/callback")

    assert response.status_code == 400
    assert "location" not in response.headers
    assert network.resolved == []
    assert network.requests == []


@pytest.mark.parametrize(
    "addresses",
    [
        ["10.1.2.3"],
        ["192.168.0.10"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["100.64.0.1"],
        ["::1"],
        ["fd00::1"],
        ["::ffff:10.0.0.1"],
        [PUBLIC_ADDRESS, "172.16.0.1"],
    ],
)
async def test_a_host_resolving_to_a_private_address_is_never_requested(
    mcp_sessions: SessionFactory, network: FakeNetwork, addresses: list[str]
) -> None:
    """Имя, за которым стоит внутренний адрес, — отказ до соединения (SSRF)."""
    url = "https://attacker.example/client.json"
    network.serve(url, {"client_id": url, "redirect_uris": ["http://127.0.0.1/callback"]})
    network.addresses["attacker.example"] = addresses
    async with _http(_server(mcp_sessions, network)) as client:
        _, challenge = _pkce()
        response = await _authorize(client, url, challenge, "http://127.0.0.1:5000/callback")

    assert response.status_code == 400
    assert network.resolved == ["attacker.example"]
    assert network.requests == []


async def test_a_document_redirect_uri_outside_its_list_is_refused(
    mcp_sessions: SessionFactory, network: FakeNetwork
) -> None:
    async with _http(_server(mcp_sessions, network)) as client:
        _, challenge = _pkce()
        response = await _authorize(client, CLAUDE_ID, challenge, "http://127.0.0.1:5000/elsewhere")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


# --- Кэш документа -------------------------------------------------------------------


async def test_the_document_is_fetched_again_only_after_its_lifetime(
    db_session: AsyncSession, network: FakeNetwork
) -> None:
    documents = network.documents()
    start = datetime.now(UTC)

    first = await oauth_service.find_client(db_session, CLAUDE_ID, documents=documents, now=start)
    cached = await oauth_service.find_client(
        db_session, CLAUDE_ID, documents=documents, now=start + timedelta(minutes=4)
    )
    assert first == cached
    assert len(network.requests) == 1

    # Сервер клиента сказал `max-age=300`: через пять минут документ качается заново, и
    # новый список адресов возврата вытесняет прежний.
    network.serve(
        CLAUDE_ID,
        CLAUDE_DOCUMENT | {"redirect_uris": ["http://127.0.0.1/new"]},
        **{"cache-control": "max-age=300"},
    )
    renewed = await oauth_service.find_client(
        db_session, CLAUDE_ID, documents=documents, now=start + timedelta(minutes=6)
    )
    assert len(network.requests) == 2
    assert renewed is not None and renewed["redirect_uris"] == ["http://127.0.0.1/new"]


async def test_a_stale_document_that_no_longer_loads_is_not_trusted(
    db_session: AsyncSession, network: FakeNetwork
) -> None:
    documents = network.documents()
    start = datetime.now(UTC)
    assert await oauth_service.find_client(db_session, CLAUDE_ID, documents=documents, now=start)

    network.responses["/oauth/claude-code-client-metadata"] = DocumentResponse(
        status=503, headers={}, body=b""
    )
    later = start + timedelta(hours=2)
    assert (
        await oauth_service.find_client(db_session, CLAUDE_ID, documents=documents, now=later)
        is None
    )


async def test_a_url_is_never_looked_up_as_a_dcr_client(
    db_session: AsyncSession, network: FakeNetwork
) -> None:
    """Клиент DCR с `client_id`-адресом не подменит документ: такой строки DCR не бывает."""
    db_session.add(OAuthClient(client_id=CODEX_ID, client_metadata={"redirect_uris": []}))
    await db_session.flush()
    found = await oauth_service.find_client(db_session, CODEX_ID, documents=network.documents())

    assert found is not None and found["client_name"] == "Codex"
    assert len(network.requests) == 1


# --- Загрузчик: ответы сервера клиента -----------------------------------------------


def _answer(status: int = 200, body: bytes = b"{}", **headers: str) -> DocumentResponse:
    return DocumentResponse(
        status=status, headers={"content-type": "application/json"} | headers, body=body
    )


@pytest.mark.parametrize(
    "response",
    [
        _answer(302, location="https://elsewhere.example/doc.json"),
        _answer(404),
        _answer(body=b"x" * (DOCUMENT_MAX_BYTES + 1)),
        _answer(body=b"not json"),
        DocumentResponse(status=200, headers={"content-type": "text/html"}, body=b"{}"),
    ],
    ids=["redirect", "not-found", "too-large", "not-json", "html"],
)
async def test_a_bad_answer_is_refused(response: DocumentResponse) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC_ADDRESS]

    async def request(request: DocumentRequest) -> DocumentResponse:
        return response

    with pytest.raises(OAuthRefusal) as refused:
        await ClientDocuments(resolve=resolve, request=request).fetch(CLAUDE_ID)
    assert refused.value.error == "invalid_client"


async def test_a_path_http_client_refuses_is_a_refusal_not_a_crash() -> None:
    """Пробел в пути: `http.client` бросает `InvalidURL` (это `ValueError`)."""

    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC_ADDRESS]

    async def request(request: DocumentRequest) -> DocumentResponse:
        raise documents_module.http.client.InvalidURL("URL can't contain control characters")

    with pytest.raises(OAuthRefusal):
        await ClientDocuments(resolve=resolve, request=request).fetch(
            "https://claude.ai/a b/client.json"
        )


async def test_a_slow_server_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_module, "DOCUMENT_TIMEOUT_SECONDS", 0.05)

    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC_ADDRESS]

    async def request(request: DocumentRequest) -> DocumentResponse:
        await asyncio.sleep(5)
        raise AssertionError("unreachable")

    with pytest.raises(OAuthRefusal, match="timed out"):
        await ClientDocuments(resolve=resolve, request=request).fetch(CLAUDE_ID)


def test_the_blocking_reader_stops_at_the_size_limit_and_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Настоящий читатель ответа: предел размера и часы, без сети (подменён сокет)."""

    class Response:
        status = 200

        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = chunks

        def read1(self, size: int) -> bytes:
            return self._chunks.pop(0)[:size] if self._chunks else b""

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Content-Type", "application/json")]

    class Connection:
        def __init__(self, chunks: list[bytes]) -> None:
            self.response = Response(chunks)

        def request(self, *args: object, **kwargs: object) -> None: ...

        def getresponse(self) -> Response:
            return self.response

        def close(self) -> None: ...

    target = DocumentRequest(address=PUBLIC_ADDRESS, host="claude.ai", port=443, target="/x")
    big = [b"a" * 1024] * 20

    monkeypatch.setattr(
        documents_module, "_PinnedHTTPSConnection", lambda request, timeout: Connection(big)
    )
    read = documents_module._get_blocking(target, time.monotonic() + 5)
    assert len(read.body) == DOCUMENT_MAX_BYTES + 1
    assert read.headers == {"content-type": "application/json"}

    monkeypatch.setattr(
        documents_module, "_PinnedHTTPSConnection", lambda request, timeout: Connection([b"{"])
    )
    with pytest.raises(TimeoutError):
        documents_module._get_blocking(target, time.monotonic() - 1)


# --- Правила документа ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://claude.ai/doc",
        "https://user:pw@claude.ai/doc",
        "https://claude.ai/doc#frag",
        "https://claude.ai",
        "https://claude.ai/",
        "https://claude.ai/a/../doc",
        "https://claude.ai:8443/doc",
        "https://10.0.0.1/doc",
        "https://[fe80::1]/doc",
    ],
)
def test_a_document_url_is_refused(url: str) -> None:
    with pytest.raises(OAuthRefusal):
        check_document_url(url)


def test_a_public_document_url_passes() -> None:
    check_document_url(CODEX_ID)
    check_document_url("https://example.com:443/client?x=1")


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("160.79.104.10", True),
        ("2606:4700::6810:84e5", True),
        ("10.0.0.1", False),
        ("172.31.255.255", False),
        ("192.168.1.1", False),
        ("127.0.0.53", False),
        ("0.0.0.0", False),
        ("169.254.169.254", False),
        ("100.100.0.1", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1%en0", False),
        ("fc00::1", False),
        ("::ffff:127.0.0.1", False),
        ("::ffff:8.8.8.8", True),
        ("not-an-address", False),
    ],
)
def test_public_addresses(address: str, public: bool) -> None:
    assert is_public_address(address) is public


@pytest.mark.parametrize(
    "document",
    [
        [],
        CLAUDE_DOCUMENT | {"client_id": "https://evil.example/doc"},
        CLAUDE_DOCUMENT | {"client_secret": "s"},
        CLAUDE_DOCUMENT | {"token_endpoint_auth_method": "client_secret_basic"},
        {k: v for k, v in CLAUDE_DOCUMENT.items() if k != "redirect_uris"},
        CLAUDE_DOCUMENT | {"redirect_uris": ["http://evil.example/callback"]},
        CLAUDE_DOCUMENT | {"redirect_uris": "http://127.0.0.1/callback"},
    ],
    ids=["not-object", "other-id", "secret", "secret-method", "no-uris", "http-off-loop", "str"],
)
def test_a_document_is_refused(document: object) -> None:
    with pytest.raises(OAuthRefusal) as refused:
        client_from_document(CLAUDE_ID, document)
    assert refused.value.error == "invalid_client"


def test_a_document_becomes_a_public_client_with_the_casefile_scope() -> None:
    client = client_from_document(CODEX_ID, CODEX_DOCUMENT)
    assert client["token_endpoint_auth_method"] == "none"
    assert client["scope"] == "casefile"
    assert client["redirect_uris"] == CODEX_DOCUMENT["redirect_uris"]


@pytest.mark.parametrize(
    ("header", "lifetime"),
    [
        (None, timedelta(hours=1)),
        ("public, max-age=300", timedelta(minutes=5)),
        ("max-age=3600", timedelta(hours=1)),
        ("max-age=10", DOCUMENT_MIN_LIFETIME),
        ("max-age=9999999", DOCUMENT_MAX_LIFETIME),
        ("no-store", DOCUMENT_MIN_LIFETIME),
    ],
)
def test_document_lifetime(header: str | None, lifetime: timedelta) -> None:
    assert document_lifetime(header) == lifetime


# --- Проверка 2: адрес возврата на петле без порта ----------------------------------


@pytest.mark.parametrize(
    ("registered", "requested", "matches"),
    [
        ("http://127.0.0.1/callback", "http://127.0.0.1:43117/callback", True),
        ("http://127.0.0.1:1234/callback", "http://127.0.0.1:43117/callback", True),
        ("http://localhost/callback", "http://localhost:54822/callback", True),
        ("http://[::1]/callback", "http://[::1]:5000/callback", True),
        ("http://127.0.0.1/callback", "http://127.0.0.1:43117/elsewhere", False),
        ("http://127.0.0.1/callback", "http://localhost:43117/callback", False),
        ("http://127.0.0.1/callback?a=1", "http://127.0.0.1:5/callback?a=2", False),
        ("https://app.example/cb", "https://app.example/cb", True),
        ("https://app.example/cb", "https://app.example:8443/cb", False),
        ("http://127.0.0.1/cb", "https://127.0.0.1:5000/cb", False),
        ("https://127.0.0.1/cb", "https://127.0.0.1:5000/cb", False),
    ],
)
def test_redirect_matching(registered: str, requested: str, matches: bool) -> None:
    assert redirect_matches(registered, requested) is matches


async def _register(client: AsyncClient, redirect_uris: list[str]) -> str:
    response = await client.post(
        "/register",
        json={
            "redirect_uris": redirect_uris,
            "client_name": "Codex",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


@pytest.mark.parametrize(
    "registered", ["http://127.0.0.1/callback", "http://127.0.0.1:1234/callback"]
)
async def test_a_dcr_client_is_answered_on_any_loopback_port(
    mcp_sessions: SessionFactory, network: FakeNetwork, registered: str
) -> None:
    redirect = "http://127.0.0.1:43117/callback"
    async with _http(_server(mcp_sessions, network)) as client:
        client_id = await _register(client, [registered])
        issued = await _sign_in(client, client_id, redirect)

    assert issued["access_token"].startswith("trk_")
    assert network.requests == []  # клиент DCR документов не качает


async def test_a_port_changed_between_authorize_and_token_is_refused(
    mcp_sessions: SessionFactory, network: FakeNetwork
) -> None:
    """Порт свободен при регистрации, но код привязан к адресу, данному в `/authorize`."""
    redirect = "http://127.0.0.1:43117/callback"
    async with _http(_server(mcp_sessions, network)) as client:
        client_id = await _register(client, ["http://127.0.0.1/callback"])
        verifier, challenge = _pkce()
        code = _code(await _authorize(client, client_id, challenge, redirect), redirect)
        response = await _exchange(
            client, client_id, code, verifier, "http://127.0.0.1:43118/callback"
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


async def test_a_non_loopback_redirect_is_compared_exactly(
    mcp_sessions: SessionFactory, network: FakeNetwork
) -> None:
    registered = "https://app.example/callback"
    async with _http(_server(mcp_sessions, network)) as client:
        client_id = await _register(client, [registered])
        _, challenge = _pkce()
        other_port = await _authorize(
            client, client_id, challenge, "https://app.example:8443/callback"
        )
        exact = await _authorize(client, client_id, challenge, registered)

    assert other_port.status_code == 400
    assert other_port.json()["error"] == "invalid_request"
    # Точный адрес сверку прошёл; дальше согласие без страницы не даётся вне петли.
    assert exact.status_code == 302
    assert parse_qs(urlsplit(exact.headers["location"]).query)["error"] == ["access_denied"]
