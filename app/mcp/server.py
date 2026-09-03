"""Сборка MCP-сервера: пока только каркас и проверка здоровья.

Сервер собирается фабрикой, а не заводится глобальным объектом: тесты поднимают свой
экземпляр с сессией, привязанной к откатываемой транзакции, — ровно как это делает
`create_app` для REST.

## Инструментов сейчас нет, и это состояние, а не поломка

Старый набор инструментов снесён вместе со старым доменом (задача 20), новый строится
задачей 28. До неё сервер отвечает на `initialize` и отдаёт пустой `tools/list`:
клиент подключается, видит сервер живым и не получает ни одного действия. Так и должно
быть — заглушка, изображающая работу, обошлась бы дороже честной пустоты.

От сервера при этом остаётся всё, что не зависит от набора инструментов: контекст
вызова с сессией и актором (`app/mcp/runtime.py`), разбор заголовка авторизации,
перевод доменных ошибок в ошибки протокола (`app/mcp/errors.py`) и проверка здоровья
для Docker.

## Инструкция сервера — это тоже промпт

`instructions` уезжает клиенту при подключении и читается моделью раньше любого вызова.
Поэтому там не «добро пожаловать», а то, чего не видно из описаний отдельных
инструментов. Пока инструментов нет, там сказано ровно это.
"""

from mcp.server.mcpserver import MCPServer
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.mcp.runtime import Runtime, headers_middleware

logger = get_logger("mcp")

INSTRUCTIONS = """Task tracker for agents. This server is being rebuilt and exposes no \
tools yet: `tools/list` is empty on purpose, not by failure. Authentication already \
works the same way it does for the REST API — `Authorization: Bearer <actor API token>` \
on every message."""


def create_server(
    *,
    runtime: Runtime | None = None,
    settings: Settings | None = None,
) -> MCPServer:
    """Собирает сервер.

    `runtime` подменяют тесты; в рабочем контуре он берёт `session_scope` — ту же
    границу транзакции, что и REST.
    """
    settings = settings or get_settings()
    runtime = runtime or Runtime()

    server = MCPServer(
        name="tracker",
        title="Tracker",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url=None,
        # Заголовки входящего сообщения попадают в контекстную переменную и оттуда — в
        # аутентификацию. Через промежуточный слой, а не через объект контекста, потому
        # что статическому ресурсу контекст не выдаётся вовсе (`app/mcp/runtime.py`).
        middleware=[headers_middleware],
        debug=settings.debug,
    )

    _register_health(server, runtime)
    return server


def _register_health(server: MCPServer, runtime: Runtime) -> None:
    """Проверка здоровья для Docker: обычный HTTP-маршрут рядом с эндпоинтом MCP.

    Протоколом MCP её не выразить — клиента у healthcheck нет, есть `curl`. Проверка та
    же, что у REST (`app/api/routes/health.py`): живо ли соединение с базой.

    Отдельно про непромигрированную базу. Сервер поднимается **до** миграций, но в
    таблицы при старте не ходит вовсе: `SELECT 1` их не трогает. Поэтому отличать «схемы
    ещё нет» здесь не от чего, и ветки под это состояние нет — она была бы недостижимым
    кодом.
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
