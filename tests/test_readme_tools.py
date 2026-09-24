"""Сторож README: список инструментов и готовый конфиг `mcpServers` (TRK-121).

Каталоги MCP (mcp.so, Glama) собирают карточку сервера из README: раздел `## Tools`
даёт список инструментов с описаниями, туда же смотрит и человек на GitHub. Разойдись
список с сервером — каталог покажет то, чего сервер не умеет, или промолчит про то, что
умеет (`TRK-85#33`: без раздела `## Tools` каталог отвечает «No tools detected»).
Сверяются **множества** имён, а не глазами (`docs/CONVENTIONS.md`, «Документация»).

`## Tools` называет инструменты обоих наборов токена (`task` и `main`) — README не
подписывается никаким токеном, поэтому в нём должен быть весь список, который отдаёт
`MCPServer.list_tools()` без фильтра `tools/list` (`app/mcp/toolset.py`).
"""

import json
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"

#: Строка списка раздела `## Tools`: `- \`имя\` — описание`. Имя — первый бэктик-токен
#: строки, ровно как в картах `AGENTS.md` (`docs/CONVENTIONS.md`, «Перед работой»).
TOOL_IN_README = re.compile(r"^- `([a-z][a-z0-9_]*)` — ", re.MULTILINE)


def _section(text: str, heading: str) -> str:
    """Раздел README по заголовку второго уровня, до следующего такого заголовка."""
    _, separator, rest = text.partition(f"\n## {heading}\n")
    assert separator, f"в README не стало раздела «{heading}»"
    return rest.split("\n## ", 1)[0]


async def test_the_tools_section_names_every_registered_tool(mcp_server: MCPServer) -> None:
    """Обзорная проверка 1: `## Tools` README не расходится с зарегистрированными
    инструментами.

    `list_tools()` зовётся на самом объекте сервера, без сессии клиента и без фильтра по
    набору токена (`app/mcp/toolset.py`, `Toolset.middleware`), поэтому сравнение идёт
    против полного списка — того же, что видел бы держатель набора `main`.
    """
    registered = {tool.name for tool in await mcp_server.list_tools()}
    listed = set(TOOL_IN_README.findall(_section(README.read_text(encoding="utf-8"), "Tools")))

    assert listed, "в README не нашлось ни одной строки вида «- `имя` — …»"
    assert listed == registered, (
        "README и сервер разошлись: "
        f"README называет лишнее {sorted(listed - registered)}, "
        f"сервер называет лишнее {sorted(registered - listed)}"
    )


def test_the_mcp_servers_json_block_points_at_the_default_mcp_address() -> None:
    """Обзорная проверка 2 (часть, проверяемая без живого клиента): JSON-блок
    `mcpServers` в «Connect your agent» разбирается и указывает на HTTP MCP с
    заголовком авторизации. Что блок подключает настоящий клиент — проверяется руками
    (`docs notes`, дело задачи), эту часть тестом на подстановку в чужой процесс не
    накрыть.
    """
    text = README.read_text(encoding="utf-8")
    connect = _section(text, "Connect your agent")
    _, separator, rest = connect.partition("```json\n")
    assert separator, "в разделе «Connect your agent» не стало JSON-блока mcpServers"
    block = rest.split("\n```", 1)[0]

    config = json.loads(block)
    server = config["mcpServers"]["casefile"]
    assert server["type"] == "http"
    assert server["url"] == "http://localhost:8100/mcp"
    assert server["headers"]["Authorization"] == "Bearer <token>"
