"""Каркас MCP-сервера: подключение, пустой набор инструментов, доступ и здоровье.

Инструментов у сервера сейчас нет: старый набор снесён задачей 20, новый строится
задачей 28. Поэтому тесты здесь проверяют не действия, а то, что каркас жив, — иначе
поломку заметят только в задаче 28, когда чинить придётся сразу и каркас, и инструменты.

Пустой `tools/list` проверяется прямо, а не «между делом»: пустота обязана быть
состоянием, а не последствием того, что регистрация тихо упала.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.domain.authors import AuthorKind
from app.domain.tokens import TokenScope
from app.mcp.runtime import Runtime, SessionFactory, bearer_token, use_headers
from app.mcp.server import INSTRUCTIONS


async def test_the_server_exposes_no_tools_yet(mcp_server: MCPServer) -> None:
    """Пустой список — объявленное состояние, а не молча упавшая регистрация."""
    assert await mcp_server.list_tools() == []


async def test_the_instructions_say_the_server_has_no_tools() -> None:
    """Инструкция читается моделью раньше любого вызова и не должна обещать лишнего."""
    assert "no tools" in INSTRUCTIONS
    assert "Authorization: Bearer" in INSTRUCTIONS


async def test_a_client_can_initialize_a_session(mcp_server: MCPServer) -> None:
    """`initialize` отвечает и отдаёт возможности сервера.

    Через настоящий HTTP-транспорт, а не вызовом метода: `initialize` — это рукопожатие
    протокола, и сломать его можно сборкой сервера, ничего не трогая в обработчиках.

    Две детали, без которых тест падает не по делу. Жизненный цикл приложения надо
    открыть руками: `ASGITransport` его не запускает, а менеджер сессий streamable HTTP
    заводит свою группу задач именно там и без неё отвечает
    `Task group is not initialized`. И заголовок `accept` обязан называть оба типа:
    сервер отвечает либо телом JSON, либо потоком событий, и клиент должен принимать оба.

    Адрес — `localhost` **с портом**: у эндпоинта MCP стоит защита от DNS rebinding,
    её список разрешённых значений `Host` — это `localhost:*` и `127.0.0.1:*`, и адрес
    без порта под шаблон не подходит. Чужой `Host` отвергается как
    `421 Misdirected Request`. У проверки здоровья такой защиты нет — это обычный
    маршрут Starlette, — поэтому соседний тест ходит куда угодно, а этот обязан
    прикидываться локальным клиентом.
    """
    application = mcp_server.streamable_http_app()
    transport = ASGITransport(app=application)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(transport=transport, base_url="http://localhost:8100") as client,
    ):
        response = await client.post(
            "/mcp",
            headers={"accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "tests", "version": "0"},
                },
            },
        )

    assert response.status_code == 200, response.text
    assert "tracker" in response.text


async def test_the_health_route_answers_next_to_the_mcp_endpoint(
    mcp_server: MCPServer,
) -> None:
    """Проверка здоровья нужна Docker, а протоколом MCP её не выразить."""
    transport = ASGITransport(app=mcp_server.streamable_http_app())
    async with AsyncClient(transport=transport, base_url="http://mcp.test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_the_token_is_read_from_the_authorization_header() -> None:
    """Схема представления одна с REST: `Authorization: Bearer`, и другой нет."""
    assert bearer_token({"authorization": "Bearer secret"}) == "secret"

    with pytest.raises(UnauthorizedError) as missing:
        bearer_token(None)
    assert missing.value.details["reason"] == "missing_token"

    with pytest.raises(UnauthorizedError) as scheme:
        bearer_token({"authorization": "Basic something"})
    assert scheme.value.details["reason"] == "invalid_scheme"


async def test_a_call_resolves_the_author_behind_the_token(
    mcp_sessions: SessionFactory,
    owner: Participant,
    main_secret: str,
) -> None:
    """Контекст вызова отдаёт сессию и автора: на этом стоят все будущие инструменты."""
    runtime = Runtime(sessions=mcp_sessions)

    async with (
        use_headers({"authorization": f"Bearer {main_secret}"}),
        runtime.call() as (session, actor),
    ):
        assert isinstance(session, AsyncSession)
        assert actor.author.signature == owner.name
        assert actor.scope is TokenScope.MAIN


async def test_a_shared_token_takes_its_signature_from_the_message_header(
    mcp_sessions: SessionFactory,
    shared_secret: str,
) -> None:
    """Тот же заголовок, что и в REST: вторая схема представления проектом запрещена."""
    runtime = Runtime(sessions=mcp_sessions)

    async with (
        use_headers({"authorization": f"Bearer {shared_secret}", "x-actor-label": "Nightly_Agent"}),
        runtime.call() as (_, actor),
    ):
        assert actor.author.kind is AuthorKind.AGENT
        assert actor.author.signature == "nightly_agent"


async def test_a_shared_token_without_a_label_refuses_the_call(
    mcp_sessions: SessionFactory,
    shared_secret: str,
) -> None:
    """Отказ приезжает агенту текстом с кодом — тем же, что и в REST."""
    runtime = Runtime(sessions=mcp_sessions)

    with pytest.raises(Exception) as failure:
        async with use_headers({"authorization": f"Bearer {shared_secret}"}), runtime.call():
            pass

    assert "actor_label_required" in str(failure.value)


async def test_a_call_without_a_token_refuses_with_the_reason(
    mcp_sessions: SessionFactory,
) -> None:
    """Отказ приезжает агенту текстом с кодом, а не сбоем протокола."""
    runtime = Runtime(sessions=mcp_sessions)

    with pytest.raises(Exception) as failure:
        async with use_headers(None), runtime.call():
            pass

    assert "unauthorized" in str(failure.value)
