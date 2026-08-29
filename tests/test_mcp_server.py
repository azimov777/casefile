"""Сам сервер: описания инструментов, ресурсы, нотификации и проверка здоровья.

Описания здесь проверяются наравне с поведением, и это не формальность: описание
инструмента и его параметров — тот промпт, который читает модель, и инструмент без
описания она применит наугад.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.server.subscriptions import InMemorySubscriptionBus
from mcp.shared.subscriptions import ResourceUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.wakeup import WakeupHub
from app.mcp.push import InboxPush, inbox_uri
from app.mcp.runtime import use_headers
from app.mcp.server import INSTRUCTIONS
from app.services import notifications as notifications_service

#: Инструменты, которые меняют данные. Список ведётся руками намеренно: он и есть
#: договор «мутирующее видно по имени», и новый инструмент обязан попасть либо сюда,
#: либо в читающие — молча появиться он не может.
MUTATING = {
    "create_issue",
    "update_issue",
    "assign_issue",
    "transition_issue",
    "add_comment",
    "add_checklist_item",
    "update_checklist_item",
    "check_checklist_item",
    "move_checklist_item",
    "delete_checklist_item",
    "link_issues",
    "unlink_issues",
    "add_issues_to_project",
    "remove_issue_from_project",
    "move_card_to_column",
    "rank_card",
    "configure_automation_rule",
    "run_macro",
    "mark_notifications_read",
    "create_queue",
    "update_queue",
    "set_queue_issue_types",
    "create_status",
    "create_issue_type",
    "create_resolution",
    "create_workflow",
    "replace_workflow",
    "update_workflow_transition",
    "create_field",
    "update_field",
}


async def test_every_tool_explains_itself_and_its_arguments(mcp_server: MCPServer) -> None:
    """Описание — это промпт: без него модель применяет инструмент наугад."""
    tools = await mcp_server.list_tools()

    assert tools, "сервер обязан объявлять инструменты"
    for tool in tools:
        assert tool.description, f"{tool.name} без описания"
        properties = tool.input_schema.get("properties", {})
        undocumented = [
            name
            for name, schema in properties.items()
            if not schema.get("description") and "$ref" not in schema
        ]
        assert not undocumented, f"{tool.name}: параметры без описания — {undocumented}"


async def test_a_mutating_tool_says_so_in_its_description(mcp_server: MCPServer) -> None:
    """«Меняет данные» должно быть видно из описания, а не выясняться по последствиям."""
    tools = {tool.name: tool for tool in await mcp_server.list_tools()}

    unknown = MUTATING - set(tools)
    assert not unknown, f"список мутирующих отстал от сервера: {sorted(unknown)}"
    for name in sorted(MUTATING):
        assert "Mutating" in (tools[name].description or ""), f"{name} не помечен как мутирующий"


async def test_the_search_tool_carries_the_query_language_in_its_description(
    mcp_server: MCPServer,
) -> None:
    """Агент не пойдёт искать документацию: синтаксис обязан лежать в самом описании."""
    tools = {tool.name: tool for tool in await mcp_server.list_tools()}
    query = tools["search_issues"].input_schema["properties"]["query"]["description"]

    assert "me()" in query
    assert "today()" in query
    assert "status_category" in query
    assert "and" in query


async def test_the_instructions_tell_an_agent_where_to_start() -> None:
    """Инструкция сервера читается моделью раньше любого вызова."""
    assert "search_issues" in INSTRUCTIONS
    assert "get_queue_config" in INSTRUCTIONS
    assert "dry_run" in INSTRUCTIONS


async def test_reference_resources_are_readable(
    mcp_read: Callable[[str], Awaitable[Any]],
    queue: Any,
) -> None:
    """Список очередей и словарь статусов — то, что клиент кладёт в контекст один раз."""
    queues = await mcp_read("tracker://queues")
    statuses = await mcp_read("tracker://statuses")
    me = await mcp_read("tracker://me")

    assert [item["key"] for item in queues["queues"]] == ["TRK"]
    assert {"open", "in_progress", "closed"} <= {item["ref"] for item in statuses["statuses"]}
    assert me["key"] == "owner"
    assert me["inbox_resource"] == "tracker://inbox/owner"


async def test_an_inbox_resource_is_read_only_by_its_owner(
    mcp_read: Callable[[str], Awaitable[Any]],
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Чужая лента не читается вовсе: пустая выдача была бы неотличима от своей."""
    await notifications_service.notify_actor(db_session, actor=owner, body="Deadline is tomorrow")

    own = await mcp_read("tracker://inbox/owner")

    assert [item["body"] for item in own["unread"]] == ["Deadline is tomorrow"]

    with pytest.raises(ResourceError) as failure:
        await mcp_read("tracker://inbox/somebody_else")

    assert "permission_denied" in str(failure.value)


async def test_a_resource_without_a_token_refuses_with_the_reason(
    mcp_server: MCPServer,
) -> None:
    """Ресурс отвечает тем же `unauthorized`, что и инструмент, — схема одна."""
    with pytest.raises(ResourceError) as failure:
        await mcp_server.read_resource("tracker://queues")

    assert "unauthorized" in str(failure.value)


async def test_an_inbox_wakeup_becomes_a_subscription_event() -> None:
    """MCP-нотификация — сигнал по адресу инбокса, а не второй канал с содержимым.

    Проверяется мост целиком: пробуждение хаба (в контуре его вызывает `NOTIFY` из
    воркера) обязано превратиться в событие подписки по адресу ресурса инбокса.
    """
    bus = InMemorySubscriptionBus()
    published: list[Any] = []
    bus.subscribe(published.append)
    hub = WakeupHub("test_inbox_channel")
    push = InboxPush(bus, hub=hub)

    async with push.running():
        hub.wake(["alice"])
        await _settle()

    assert published == [ResourceUpdated(uri=inbox_uri("alice"))]


async def test_the_health_route_answers_next_to_the_mcp_endpoint(
    mcp_server: MCPServer,
) -> None:
    """Проверка здоровья нужна Docker, а протоколом MCP её не выразить."""
    from httpx import ASGITransport, AsyncClient

    application = mcp_server.streamable_http_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://mcp.test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_the_token_is_read_from_the_authorization_header(mcp_server: MCPServer) -> None:
    """Схема представления одна с REST: `Authorization: Bearer`, и другой нет."""
    async with use_headers({"authorization": "Basic something"}):
        with pytest.raises(Exception) as failure:
            await mcp_server.call_tool("list_queues", {})

    assert "invalid_scheme" in str(failure.value)


async def _settle() -> None:
    """Даёт отработать задачам публикации: колбэк хаба синхронный и только их ставит."""
    import asyncio

    for _ in range(3):
        await asyncio.sleep(0)
