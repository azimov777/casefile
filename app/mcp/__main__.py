"""MCP-сервер трекера: отдельный процесс, отдельный порт.

Запуск: `python -m app.mcp`. В Compose это сервис `mcp` в обоих контурах.

Отдельный сервис, а не маршрут внутри API. Причин две. Клиент MCP держит соединение
открытым и ждёт на нём: долгое ожидание ленты висит десятками секунд, и такие соединения
нельзя ставить в очередь к обычным запросам фронтенда. Плюс сервер обязан подниматься и
масштабироваться отдельно: агентов может быть десять при одном фронтенде и наоборот.

## Два транспорта: HTTP основной, stdio — альтернатива

**Streamable HTTP** — путь установки: одна служба на всех агентов, токен в заголовке
`Authorization` каждого запроса. Адрес по умолчанию `0.0.0.0:8100/mcp`, настраивается
`TRACKER_MCP_HOST`, `TRACKER_MCP_PORT` и `TRACKER_MCP_PATH`.

**stdio** (`python -m app.mcp --stdio`) — тот же сервер, который клиент запускает сам как
дочерний процесс и говорит с ним через stdin/stdout: для клиентов и каталогов, умеющих
только команду (Glama гоняет её под `mcp-proxy`, TRK-125). Инструменты, промпт и ответы те
же; база та же — процесс ходит в неё, как и HTTP-служба, по `TRACKER_DATABASE_URL`.
Нотификации сервера протокол несёт и по stdio, `wait_journal` работает так же.

Заголовков у сообщения stdio нет, поэтому процесс представляется одним токеном
`TRACKER_MCP_TOKEN` на всё время жизни: он становится заголовком `Authorization` процесса
(`Runtime.headers`) и проходит тот же разбор, что и в HTTP. Без токена процесс не
стартует — в этом режиме без него не прошёл бы ни один вызов, и клиенту честнее показать
причину сразу, чем отвечать `unauthorized` на каждый. Метки временного агента
(`X-Actor-Label`) в stdio нет: токен процесса — токен одного участника.

stdout в этом режиме занят протоколом целиком. Журнал и так пишет в stderr
(`app/core/logging.py`), и печатать в stdout здесь нельзя ничего: строка, не являющаяся
JSON-RPC, ломает разбор у клиента.

Процесс поднимается **до** миграций: схемы в первые секунды контура может не быть. В базу
при старте он не ходит вовсе, поэтому непромигрированную базу переживает без единой
ошибки.

## Почему uvicorn поднимается здесь руками, а не `run_streamable_http_async`

Ради одного: у обёртки SDK нет `timeout_graceful_shutdown`, а без него остановка ждёт
закрытия соединений **без срока**. Соединения у MCP долгие — сессия streamable HTTP
живёт всё время работы агента, — и на практике это означало остановку убийством: Docker
дожидался `stop_grace_period` и слал `SIGKILL`, обрывая заодно и вызов инструмента,
который в этот момент писал в базу.

Всё остальное берётся у SDK как есть: приложение собирает `streamable_http_app`, и
своего транспорта здесь не заводится.

## Слушателя оповещений журнала поднимает процесс, и без него ожидание молча деградирует

`journal_wakeup.start()` открывает соединение `LISTEN/NOTIFY`, из-за которого
`wait_journal` возвращается **сразу** после подшивки записи. Это отдельный процесс от
HTTP-сервера, и его жизненный цикл (`app/main.py`) здесь не выполняется — значит, вызов
нужен свой. Без него `wait_journal` не сломается: он перейдёт на контрольный опрос и
станет отвечать с задержкой до `TRACKER_JOURNAL_WAIT_POLL_INTERVAL` секунд. Сбой
молчаливый — проверка «пустой ответ по таймауту» его не увидит, — поэтому подъём вынесен
в именованный менеджер `journal_listener`, и его же зовёт тест.

Сборкой сервера слушатель не поднимается намеренно: `create_server` вызывается в тестах
десятками раз, и соединение к базе на каждый экземпляр — это, во-первых, лишние
соединения, а во-вторых, занятый слушатель не на той базе, из-за которого настоящий тест
ожидания проверял бы опрос вместо оповещения.
"""

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.shutdown import shutdown
from app.db.session import dispose_engine
from app.db.wakeup import journal_wakeup
from app.mcp.runtime import Runtime
from app.mcp.server import create_server

logger = get_logger("mcp")

#: Сколько остановка ждёт незавершённые вызовы, прежде чем снять их. Последний рубеж, а
#: не основной механизм: ожидание ленты кончается само по сигналу, а вызов инструмента
#: успевает дописать. Число меньше `stop_grace_period` сервиса `mcp` в Compose (30 с) —
#: иначе Docker убил бы процесс раньше, чем uvicorn успел остановиться сам.
GRACEFUL_SHUTDOWN_TIMEOUT = 20.0


@asynccontextmanager
async def journal_listener(dsn: str | None = None) -> AsyncIterator[None]:
    """Слушатель оповещений журнала на время жизни процесса.

    Адрес по умолчанию — основная база установки. Параметр нужен тому, кто слушает не
    её: тест идёт на отдельной базе, и слушатель основной не услышал бы в нём ничего.

    Не подключился — в логе строка, ожидание переходит на контрольный опрос; ронять
    из-за этого сервер нельзя: контур поднимается раньше, чем база готова.
    """
    await journal_wakeup.start(dsn)
    try:
        yield
    finally:
        await journal_wakeup.close()


def stdio_headers(settings: Settings) -> dict[str, str]:
    """Заголовки процесса stdio из `TRACKER_MCP_TOKEN`; без токена процесс не стартует.

    `SystemExit` со строкой печатает её в stderr и завершает процесс с кодом 1 — это и
    есть отказ, который клиент stdio показывает человеку. stdout при этом не тронут.
    """
    token = settings.mcp_token.get_secret_value().strip() if settings.mcp_token else ""
    if not token:
        raise SystemExit(
            "TRACKER_MCP_TOKEN is required for --stdio: a stdio message carries no "
            "Authorization header, so the process presents this token on every call"
        )
    return {"authorization": f"Bearer {token}"}


async def run_stdio() -> None:
    """Поднимает тот же сервер на stdin/stdout и работает, пока клиент не закроет вход."""
    settings = get_settings()
    configure_logging(debug=settings.debug)
    server = create_server(runtime=Runtime(headers=stdio_headers(settings)), settings=settings)
    logger.info("MCP server speaking over stdio")
    try:
        async with journal_listener():
            await server.run_stdio_async()
    finally:
        await dispose_engine()
        logger.info("MCP server stopped")


async def run() -> None:
    """Поднимает сервер на streamable HTTP и работает до сигнала остановки."""
    settings = get_settings()
    configure_logging(debug=settings.debug)
    server = create_server(settings=settings)
    logger.info(
        "MCP server listening on %s:%s%s",
        settings.mcp_host,
        settings.mcp_port,
        settings.mcp_path,
    )
    application = _watching_shutdown(
        server.streamable_http_app(
            streamable_http_path=settings.mcp_path,
            host=settings.mcp_host,
        )
    )
    try:
        async with journal_listener():
            await uvicorn.Server(
                uvicorn.Config(
                    application,
                    host=settings.mcp_host,
                    port=settings.mcp_port,
                    timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
                )
            ).serve()
    finally:
        await dispose_engine()
        logger.info("MCP server stopped")


def _watching_shutdown(application: Starlette) -> Starlette:
    """Дописывает подписку на сигнал остановки в жизненный цикл приложения SDK.

    Именно в жизненный цикл, а не рядом с `serve()`: свои обработчики uvicorn ставит
    внутри `serve()`, и подписка, поставленная раньше, была бы им затёрта. Жизненный
    цикл запускается уже после — там наш обработчик встаёт поверх и зовёт прежний следом
    (`app/core/shutdown.py`).

    Даёт то же, что и API: ожидание ленты (`wait_journal`) возвращается сразу по
    сигналу, а не досиживает свой таймаут.
    """
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(scope: Starlette) -> AsyncIterator[None]:
        with shutdown.listening(on_begin=journal_wakeup.wake_all):
            async with inner(scope):
                yield

    application.router.lifespan_context = lifespan
    return application


def main(argv: list[str] | None = None) -> None:
    """Разбирает ключ транспорта и запускает сервер: без ключа — HTTP, как прежде."""
    parser = argparse.ArgumentParser(prog="python -m app.mcp", description="Tracker MCP server")
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Speak MCP over stdin/stdout instead of HTTP; the token comes from TRACKER_MCP_TOKEN",
    )
    args = parser.parse_args(argv)
    asyncio.run(run_stdio() if args.stdio else run())


if __name__ == "__main__":
    main()
