"""Сведения установки: `GET /api/v1/installation` и настройка публичного адреса MCP.

Адрес MCP в контракте — настройка установки, а не догадка по заголовкам запроса
(`docs/CONCEPT.md`, 5.1; решение TRK-65#9). Поэтому проверяется две вещи: что умолчание
верно для локальной установки и двигается вместе с портом MCP, и что заданный адрес
доезжает до ответа как есть — каким бы ни был адрес самого API.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_session
from app.domain.authors import ACTOR_LABEL_HEADER
from app.domain.tokens import hash_token
from app.main import create_app

#: Поля ответа. Список закрытый: сведения установки — не место для всего подряд, и
#: поле, добавленное мимо него, обязано уронить тест, а не тихо уехать во фронтенд.
INSTALLATION_FIELDS = ["mcp_url"]

#: Адрес за прокси с TLS: другие схема, хост, порт и путь, чем у привязки процесса.
PROXIED = "https://casefile.example.com/agents/mcp"


@asynccontextmanager
async def client_of(settings: Settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Клиент приложения, собранного с этими настройками, на транзакции теста.

    Своё приложение, а не общая фикстура `app`: ответ обязан браться из настроек того
    приложения, которое обслуживает запрос, и тест это и проверяет.
    """
    application = create_app(settings)
    application.dependency_overrides[get_session] = lambda: db_session
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as http_client:
        yield http_client


# --- Настройка --------------------------------------------------------------------


def test_the_default_address_is_localhost_on_the_mcp_port_and_path() -> None:
    """Без настройки адрес — `localhost` на порту и пути самого процесса MCP."""
    settings = Settings(mcp_public_url=None, mcp_port=8100, mcp_path="/mcp")

    assert settings.effective_mcp_public_url == "http://localhost:8100/mcp"


def test_the_default_address_follows_the_mcp_port_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сдвинутый `TRACKER_MCP_PORT` сдвигает и адрес, а пустая настройка — это «не задано».

    Ровно так переменные приезжают из compose: порт — подстановкой, публичный адрес —
    подстановкой с пустым умолчанием, то есть пустой строкой, а не отсутствием.
    """
    monkeypatch.setenv("TRACKER_MCP_PORT", "18565")
    monkeypatch.setenv("TRACKER_MCP_PATH", "/mcp")
    monkeypatch.setenv("TRACKER_MCP_PUBLIC_URL", "")

    settings = Settings()

    assert settings.mcp_public_url is None
    assert settings.effective_mcp_public_url == "http://localhost:18565/mcp"


def test_a_set_address_wins_over_the_port_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заданный адрес отдаётся целиком, и привязка процесса его не трогает."""
    monkeypatch.setenv("TRACKER_MCP_PORT", "18565")
    monkeypatch.setenv("TRACKER_MCP_PUBLIC_URL", PROXIED)

    settings = Settings()

    assert settings.effective_mcp_public_url == PROXIED


@pytest.mark.parametrize(
    "value",
    [
        "localhost:8100/mcp",
        "ftp://casefile.example.com/mcp",
        "https://owner:secret@casefile.example.com/mcp",
    ],
    ids=["no-scheme", "not-http", "credentials"],
)
def test_an_address_that_is_not_a_plain_http_url_is_refused(value: str) -> None:
    """Не HTTP-адрес и адрес с паролем отклоняются при чтении настроек, а не в ответе.

    Пароль в адресе стал бы общим для всякого, кто видит интерфейс: адрес открыт любому
    ключу и уезжает в каждый фрагмент конфигурации клиента.
    """
    with pytest.raises(ValidationError, match="mcp_public_url"):
        Settings(mcp_public_url=value)


# --- Ответ ------------------------------------------------------------------------


async def test_installation_answers_with_the_default_address(
    db_session: AsyncSession,
    task_secret: str,
) -> None:
    """Обзорная проверка 1: умолчание доезжает до ответа, и ключа `task` для него хватает."""
    settings = Settings(mcp_public_url=None, mcp_port=8123, mcp_path="/mcp")

    async with client_of(settings, db_session) as client:
        response = await client.get(
            "/api/v1/installation", headers={"Authorization": f"Bearer {task_secret}"}
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert sorted(data) == INSTALLATION_FIELDS
    assert data["mcp_url"] == "http://localhost:8123/mcp"


async def test_installation_answers_with_the_set_address_not_the_request_host(
    db_session: AsyncSession,
    task_secret: str,
) -> None:
    """Обзорная проверка 1: заданный адрес — как есть, заголовки запроса его не меняют.

    Запрос приходит с `Host` и `X-Forwarded-*` интерфейса: адрес, угаданный по ним, был бы
    адресом интерфейса, а не MCP, и его подставлял бы тот, кто пишет заголовки.
    """
    settings = Settings(mcp_public_url=PROXIED)

    async with client_of(settings, db_session) as client:
        response = await client.get(
            "/api/v1/installation",
            headers={
                "Authorization": f"Bearer {task_secret}",
                "Host": "localhost:8080",
                "X-Forwarded-Host": "attacker.example.net",
                "X-Forwarded-Proto": "http",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["mcp_url"] == PROXIED


async def test_installation_is_the_same_for_every_token(
    client: AsyncClient,
    settings: Settings,
    task_secret: str,
    main_secret: str,
    shared_secret: str,
) -> None:
    """Сведения установки не зависят от того, кто спрашивает, и секрета в них нет.

    Три токена — именной `task`, именной `main` и общий агентский с меткой — получают один
    и тот же ответ, и ни в одном нет ни значения токена, ни его хеша.
    """
    callers = [
        {"Authorization": f"Bearer {task_secret}"},
        {"Authorization": f"Bearer {main_secret}"},
        {"Authorization": f"Bearer {shared_secret}", ACTOR_LABEL_HEADER: "nightly_agent"},
    ]
    responses = [await client.get("/api/v1/installation", headers=headers) for headers in callers]

    assert all(response.status_code == 200 for response in responses), [
        response.text for response in responses
    ]
    assert {response.text for response in responses} == {responses[0].text}
    assert responses[0].json()["data"]["mcp_url"] == settings.effective_mcp_public_url
    for response in responses:
        assert "trk_" not in response.text
        for secret in (task_secret, main_secret, shared_secret):
            assert hash_token(secret) not in response.text


async def test_installation_requires_a_token(client: AsyncClient) -> None:
    """Как и всё под `/api/v1`: адрес MCP без ключа не отдаётся."""
    response = await client.get("/api/v1/installation")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthorized"
