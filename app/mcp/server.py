"""Сборка MCP-сервера: инструменты, инструкции и проверка здоровья.

Сервер собирается фабрикой, а не заводится глобальным объектом: тесты поднимают свой
экземпляр с сессией, привязанной к откатываемой транзакции, — ровно как это делает
`create_app` для REST.

## Три вещи, которые сервер отдаёт агенту

1. **Инструменты** рабочего цикла (`app/mcp/tools/`). Любой действующий доступ видит
   весь `tools/list` (`app/mcp/toolset.py`).
2. **`instructions`** — как пользоваться сервером, своим текстом в
   `app/mcp/instructions.md`: что такое трекер, что видит человек, что считать
   заданием, цикл работы. Они уезжают клиенту при подключении и читаются моделью
   раньше любого вызова. Механики отдельных инструментов в них нет: она в метадате
   (`CONCEPT.md`, 5.2). Договор работы — только здесь и в метадате: решение владельца
   `TRK-140#8`.
3. **Скил** `skills/casefile/SKILL.md` — не договор, а то, что MCP не доставит (подключение,
   401, сторож журнала, установка самого скила). Отдаётся расширением SEP-2640
   (`app/mcp/skills.py`) и ресурсом `skill://casefile/SKILL.md` (`CONCEPT.md`, 5.3).

## Почему instructions — отдельный файл и держат длину

Claude Code обрезает `instructions` на 2048-м символе строки JS (единица UTF-16, не
байт; переменная клиента `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`) и дописывает
«… [truncated]». Всё после обрезки модель не видит, и никто об этом не узнает: сервер
здоров, агент работает без хвоста правил. Поэтому длину стережёт тест
(`tests/test_mcp_instructions.py`), а текст лежит своим файлом, а не строкой в коде
сборки: правят его как текст, а не как код (`TRK-142`).

Файл читается при импорте: без него процесс не поднимется, а не отдаст пустые
`instructions`.

## Чего сервер не делает

Не поднимает слушателя оповещений журнала: это дело процесса, а не сборки
(`app/mcp/__main__.py`). Разница существенна — тест поднимает сервер десятками, и подъём
слушателя в сборке дал бы десятки соединений к базе и, хуже, занятого слушателя не на той
базе, из-за которого ожидание ленты молча перешло бы на контрольный опрос.
"""

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.mcp.oauth import (
    CasefileAuthorization,
    PresentedToken,
    RefusalReasons,
    auth_settings,
    authorization_enabled,
)
from app.mcp.runtime import Runtime, headers_middleware
from app.mcp.skills import SKILLS_DIR, CasefileSkills, advertise_on_handshake
from app.mcp.tools import register_tools
from app.mcp.toolset import Toolset
from app.services.oauth import DefaultAgentConsent

logger = get_logger("mcp")

__all__ = ["INSTRUCTIONS", "INSTRUCTIONS_PATH", "create_server"]

#: Текст `instructions`: лежит рядом со сборкой и уезжает в образ вместе с `app/`.
INSTRUCTIONS_PATH = Path(__file__).with_name("instructions.md")

#: То, что сервер отдаёт в `initialize`. Концевой перевод строки файла клиенту не нужен.
INSTRUCTIONS = INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()


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
    tools = Toolset(server=_bare_server(settings, runtime), runtime=runtime, settings=settings)

    register_tools(tools)
    _register_health(tools.server, runtime)
    tools.server.middleware.append(tools.middleware())
    tools.server.middleware.append(advertise_on_handshake)
    return tools.server


class CasefileServer(MCPServer):
    """Сервер SDK, у приложения которого снаружи стоит слой причин отказа `401`.

    Слой внешний, а не промежуточный слой сообщений: `401` отвечает транспорт до
    протокола, и дописать в него причину можно только поверх всего приложения
    (`app/mcp/oauth.py`, `RefusalReasons`).
    """

    def streamable_http_app(self, **kwargs: Any) -> Starlette:
        application = super().streamable_http_app(**kwargs)
        application.add_middleware(RefusalReasons)
        return application


def _bare_server(settings: Settings, runtime: Runtime) -> MCPServer:
    """Сервер без инструментов: имя, версия, инструкция, разбор заголовков и вход OAuth."""
    # Защищённый ресурс OAuth и сервер авторизации при нём (`app/mcp/oauth.py`). SDK не
    # принимает провайдера и проверяющего вместе: с провайдером токен проверяет он сам.
    if authorization_enabled(settings):
        auth: dict[str, Any] = {
            "auth_server_provider": CasefileAuthorization(
                runtime.sessions, DefaultAgentConsent(enabled=settings.oauth_local_consent)
            )
        }
    else:
        auth = {"token_verifier": PresentedToken(runtime.sessions)}
    return CasefileServer(
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
        extensions=[CasefileSkills(SKILLS_DIR)],
        auth=auth_settings(settings),
        debug=settings.debug,
        **auth,
    )


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
