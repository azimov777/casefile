"""Сборка MCP-сервера: инструменты, ресурсы, нотификации, проверка здоровья.

Сервер собирается фабрикой, а не заводится глобальным объектом: тесты поднимают свой
экземпляр с сессией, привязанной к откатываемой транзакции, — ровно как это делает
`create_app` для REST.

## Что видит клиент

- **Инструменты** — действия: найти, прочитать, изменить, перевести, отчитаться,
  настроить процесс (`app/mcp/tools/`).
- **Ресурсы** — справочная информация: список очередей, словарь статусов, «кто я» и
  инбокс, служащий адресом подписки (`app/mcp/resources.py`).
- **Нотификации** — сигнал «в инбоксе что-то появилось» (`app/mcp/push.py`), поверх
  инбокса, а не вместо него.

## Инструкция сервера — это тоже промпт

`instructions` уезжает клиенту при подключении и читается моделью раньше любого вызова.
Поэтому там не «добро пожаловать», а то, чего не видно из описаний отдельных
инструментов: с чего начинать, как устроена адресация и чем платит за подробность
каждый ответ.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.mcp import resources
from app.mcp.push import InboxPush
from app.mcp.runtime import Runtime, headers_middleware
from app.mcp.tools import register_all

logger = get_logger("mcp")

INSTRUCTIONS = """Task tracker for agents. Work cycle: find issues with `search_issues` \
(a query language string, for example `assignee: me() and status_category: != done`), \
read one with `get_issue`, report with `add_comment`, move it with `list_transitions` \
plus `transition_issue`, and pick up what happened to your work with \
`list_notifications` or `wait_for_notifications`.

Addressing: an issue is `TRK-123`, a queue is `TRK`, a status, type, resolution or \
custom field is a reference — a bare key for a global entry (`open`) and `QUEUE.key` \
for one that belongs to a queue (`TRK.in_review`). Case does not matter when you \
address something that already exists.

Before working in a queue you do not know, read `get_queue_config`: it names the issue \
types, statuses, resolutions and custom fields it accepts, including the required ones.

Every answer costs you context, so tools return the short form by default: search and \
board listings return eight fields per issue, `get_issue` returns them too unless you \
ask for `full` or `history`, and long texts are clipped with the clip reported next to \
the value. Ask for more only when you need it.

Errors are meant to be read: they carry a stable code, a sentence and structured \
details — the character position of a broken query, the field that is missing, the \
transition that is not allowed. Fix the call by the details instead of retrying it \
unchanged.

Changing a process (`create_workflow`, `update_workflow_transition`) touches every \
issue of the queue. Both accept `dry_run: true`, which performs the change, reports \
what it would do and rolls it back."""


def create_server(
    *,
    runtime: Runtime | None = None,
    settings: Settings | None = None,
) -> MCPServer:
    """Собирает сервер со всеми инструментами и ресурсами.

    `runtime` подменяют тесты; в рабочем контуре он берёт `session_scope` — ту же
    границу транзакции, что и REST, воркер и планировщик.
    """
    settings = settings or get_settings()
    runtime = runtime or Runtime()
    bus = InMemorySubscriptionBus()
    push = InboxPush(bus)

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[None]:
        """Жизненный цикл процесса: слушатель инбокса поднимается и гасится вместе с ним."""
        del server
        logger.info("Starting tracker MCP server %s", __version__)
        async with push.running():
            yield
        logger.info("Stopping tracker MCP server")

    server = MCPServer(
        name="tracker",
        title="Tracker",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url=None,
        lifespan=lifespan,
        subscriptions=bus,
        # Заголовки входящего сообщения попадают в контекстную переменную и оттуда — в
        # аутентификацию. Через промежуточный слой, а не через объект контекста, потому
        # что статическому ресурсу контекст не выдаётся вовсе (`app/mcp/runtime.py`).
        middleware=[headers_middleware],
        debug=settings.debug,
    )

    register_all(server, runtime)
    resources.register(server, runtime)
    _register_health(server, runtime)
    return server


def _register_health(server: MCPServer, runtime: Runtime) -> None:
    """Проверка здоровья для Docker: обычный HTTP-маршрут рядом с эндпоинтом MCP.

    Протоколом MCP её не выразить — клиента у healthcheck нет, есть `curl`. Проверка та
    же, что у REST (`app/api/routes/health.py`): живо ли соединение с базой.

    Отдельно про непромигрированную базу. Сервер поднимается **до** миграций, как воркер
    и планировщик, но в таблицы при старте не ходит вовсе: `SELECT 1` их не трогает, а
    единственное соединение, которое открывается сразу, — слушатель оповещений, и он
    переживает недоступную базу строкой в логе. Поэтому отличать «схемы ещё нет» здесь
    не от чего, и ветки под это состояние нет — она была бы недостижимым кодом.
    """

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        del request
        try:
            async with runtime.sessions() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("MCP health check failed")
            return JSONResponse({"status": "error", "database": "error"}, status_code=503)
        return JSONResponse({"status": "ok", "version": __version__, "database": "ok"})
