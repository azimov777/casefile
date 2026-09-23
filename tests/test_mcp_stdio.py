"""Транспорт stdio: тот же сервер, токен процесса вместо заголовка запроса.

Два уровня, и каждый ловит своё. В процессе (`Client(server)`, память вместо труб)
проверяется, что сообщение без HTTP-запроса берёт токен у `Runtime.headers` и дальше идёт
тем же путём: тот же набор инструментов, та же подпись автора, тот же отказ. Настоящим
дочерним процессом `python -m app.mcp --stdio` проверяется то, чего в процессе не видно:
разбор ключа, отказ на старте без токена и чистота stdout — строка журнала в нём сломала
бы разбор у любого клиента stdio.
"""

import json
import os
import sys
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from tests.conftest import Connect, tool_text

from app.db.models.task import Task
from app.mcp.runtime import Runtime, SessionFactory
from app.mcp.server import create_server
from mcp import Client

#: Команда процесса stdio — та же, что пишут в настройки клиента.
STDIO_COMMAND = [sys.executable, "-m", "app.mcp", "--stdio"]


def stdio_server(sessions: SessionFactory, secret: str) -> MCPServer:
    """Сервер, собранный так же, как в `run_stdio`: токен — заголовок процесса."""
    return create_server(
        runtime=Runtime(sessions=sessions, headers={"authorization": f"Bearer {secret}"})
    )


async def test_stdio_lists_the_same_tools_as_http(
    mcp_sessions: SessionFactory,
    mcp_session: Connect,
    main_secret: str,
) -> None:
    """Набор инструментов по токену тот же, каким бы транспортом ни пришёл запрос."""
    async with mcp_session(main_secret) as http:
        over_http = {tool.name for tool in (await http.list_tools()).tools}

    async with Client(stdio_server(mcp_sessions, main_secret)) as stdio:
        over_stdio = {tool.name for tool in (await stdio.list_tools()).tools}

    assert over_stdio == over_http


async def test_stdio_offers_the_discipline_prompt(
    mcp_sessions: SessionFactory,
    main_secret: str,
) -> None:
    async with Client(stdio_server(mcp_sessions, main_secret)) as stdio:
        prompts = {prompt.name for prompt in (await stdio.list_prompts()).prompts}

    assert "tracker-discipline" in prompts


async def test_a_stdio_call_is_signed_by_the_token_participant(
    mcp_sessions: SessionFactory,
    task_secret: str,
    task: Task,
) -> None:
    """Запись от stdio-процесса подписана тем, чей токен у процесса, — как и по HTTP."""
    key = task.key
    async with Client(stdio_server(mcp_sessions, task_secret)) as stdio:
        result = await stdio.call_tool(
            "add_entry", {"key": key, "type": "note", "title": "Запись через stdio"}
        )

    assert not result.is_error, tool_text(result)
    assert result.structured_content is not None
    assert result.structured_content["author"] == {"kind": "human", "signature": "owner"}


async def test_a_stdio_call_with_a_bad_token_is_refused(mcp_sessions: SessionFactory) -> None:
    """Негодный токен — тот же `unauthorized`, что и в HTTP, а не молчаливый пропуск."""
    async with Client(stdio_server(mcp_sessions, "not-a-token")) as stdio:
        result = await stdio.call_tool("list_queues", {})

    assert result.is_error
    assert "unauthorized" in tool_text(result)


def process_env(database_url: str, **extra: str) -> dict[str, str]:
    """Окружение дочернего процесса: база теста и без токена, если его не передали."""
    env = {k: v for k, v in os.environ.items() if k != "TRACKER_MCP_TOKEN"}
    env["TRACKER_DATABASE_URL"] = database_url
    env.update(extra)
    return env


async def test_the_stdio_process_refuses_to_start_without_a_token(
    test_database_url: str,
) -> None:
    """Без `TRACKER_MCP_TOKEN` процесс не стартует, причина — в stderr, stdout пуст."""
    finished = await anyio.run_process(
        STDIO_COMMAND, env=process_env(test_database_url), check=False
    )

    assert finished.returncode == 1
    assert b"TRACKER_MCP_TOKEN is required for --stdio" in finished.stderr
    assert finished.stdout == b""


def rpc(message_id: int | None, method: str, params: dict[str, Any] | None = None) -> bytes:
    """Одна строка JSON-RPC, как её пишет клиент stdio."""
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if message_id is not None:
        message["id"] = message_id
    if params is not None:
        message["params"] = params
    return (json.dumps(message) + "\n").encode()


async def test_the_stdio_process_writes_only_protocol_to_stdout(
    test_database_url: str,
) -> None:
    """Настоящий процесс: рукопожатие, отказ по токену, и в stdout — только JSON-RPC.

    Токен заведомо негодный: процесс видит базу теста, но не транзакцию теста, и
    заведённого фикстурой токена не нашёл бы. Отказ здесь и нужен — он доказывает, что
    токен процесса дошёл до разбора, а строка журнала о запросе ушла в stderr.
    """
    env = process_env(test_database_url, TRACKER_MCP_TOKEN="not-a-token")
    requests = b"".join(
        [
            rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "tests", "version": "0"},
                },
            ),
            rpc(None, "notifications/initialized"),
            rpc(2, "tools/list"),
        ]
    )
    async with await anyio.open_process(STDIO_COMMAND, env=env) as process:
        assert process.stdin is not None
        assert process.stdout is not None
        await process.stdin.send(requests)
        received = b""
        with anyio.fail_after(45):
            while received.count(b"\n") < 2:
                received += await process.stdout.receive()
        await process.stdin.aclose()
        with anyio.fail_after(15):
            async for chunk in process.stdout:
                received += chunk
            await process.wait()

    lines = [line for line in received.decode().splitlines() if line]
    replies = {reply["id"]: reply for reply in map(json.loads, lines) if "id" in reply}
    assert all(json.loads(line)["jsonrpc"] == "2.0" for line in lines)
    assert replies[1]["result"]["serverInfo"]["name"] == "tracker"
    assert "unauthorized" in json.dumps(replies[2]["error"])
