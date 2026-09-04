"""Сборка MCP-сервера: инструменты, промпт дисциплины, инструкции и проверка здоровья.

Сервер собирается фабрикой, а не заводится глобальным объектом: тесты поднимают свой
экземпляр с сессией, привязанной к откатываемой транзакции, — ровно как это делает
`create_app` для REST.

## Три вещи, которые сервер отдаёт агенту

1. **Инструменты** рабочего цикла (`app/mcp/tools/`). Состав `tools/list` зависит от
   набора токена; отказ на вызове недоступного инструмента приходит из той же единой
   точки прав, что и в REST (`app/mcp/toolset.py`).
2. **Промпт `tracker-discipline`** — текст скила целиком. Показывать ли его модели,
   решает клиент; надёжный путь — скил, установленный в харнесс (`CONCEPT.md`, 5.3).
3. **`instructions`** — раздел «Кратко» из того же скила. Он уезжает клиенту при
   подключении и читается моделью раньше любого вызова, поэтому там дисциплина, а не
   «добро пожаловать».

Второго исходного текста дисциплины в коде нет: и промпт, и инструкции читают
`skill/tracker-agent/SKILL.md` (`app/mcp/skill.py`).

## Чего сервер не делает

Не поднимает слушателя оповещений журнала: это дело процесса, а не сборки
(`app/mcp/__main__.py`). Разница существенна — тест поднимает сервер десятками, и подъём
слушателя в сборке дал бы десятки соединений к базе и, хуже, занятого слушателя не на той
базе, из-за которого ожидание ленты молча перешло бы на контрольный опрос.
"""

from mcp.server.mcpserver import MCPServer
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.mcp.runtime import Runtime, headers_middleware
from app.mcp.skill import INSTRUCTIONS, PROMPT_NAME, SKILL_TEXT
from app.mcp.tools import register_tools
from app.mcp.toolset import Toolset

logger = get_logger("mcp")

__all__ = ["INSTRUCTIONS", "create_server"]


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
    tools = Toolset(server=_bare_server(settings), runtime=runtime, settings=settings)

    register_tools(tools)
    _register_prompt(tools.server)
    _register_health(tools.server, runtime)
    # Промежуточный слой ставится после регистрации: он спрашивает у набора состав
    # инструментов, и пустой набор оставил бы `tools/list` пустым навсегда.
    tools.server.middleware.append(tools.middleware())
    return tools.server


def _bare_server(settings: Settings) -> MCPServer:
    """Сервер без инструментов: имя, версия, инструкция и разбор заголовков."""
    return MCPServer(
        name="tracker",
        title="Tracker",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url=None,
        # Заголовки входящего сообщения попадают в контекстную переменную и оттуда — в
        # аутентификацию. Через промежуточный слой, а не через объект контекста, потому
        # что статическому ресурсу контекст не выдаётся вовсе (`app/mcp/runtime.py`).
        # Этот слой стоит **первым**: фильтр `tools/list` разбирает токен и без
        # заголовков не увидел бы его вовсе.
        middleware=[headers_middleware],
        debug=settings.debug,
    )


def _register_prompt(server: MCPServer) -> None:
    """Промпт дисциплины: текст скила целиком, без аргументов.

    Аргументов у промпта нет намеренно. Дисциплина одна на всех агентов и не зависит ни
    от задачи, ни от очереди: параметр здесь означал бы, что бывают задачи, где сводку
    можно не писать.
    """

    @server.prompt(
        name=PROMPT_NAME,
        title="Дисциплина работы над задачей",
        description=(
            "Как вести дело по задаче, чтобы преемник продолжил работу без твоего "
            "контекста. Полный текст скила `tracker-agent`"
        ),
    )
    async def tracker_discipline() -> str:
        return SKILL_TEXT


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
