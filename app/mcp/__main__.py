"""MCP-сервер трекера: отдельный процесс, отдельный порт.

Запуск: `python -m app.mcp`. В Compose это сервис `mcp` в обоих контурах.

Отдельный сервис, а не маршрут внутри API. Причин две. Клиент MCP держит соединение
открытым и ждёт на нём: долгое ожидание ленты висит десятками секунд, и такие соединения
нельзя ставить в очередь к обычным запросам фронтенда. Плюс сервер обязан подниматься и
масштабироваться отдельно: агентов может быть десять при одном фронтенде и наоборот.

Транспорт — streamable HTTP: он же несёт нотификации, поэтому stdio здесь не годится.
Адрес по умолчанию `0.0.0.0:8100/mcp`, настраивается `TRACKER_MCP_HOST`,
`TRACKER_MCP_PORT` и `TRACKER_MCP_PATH`.

Процесс поднимается **до** миграций: схемы в первые секунды контура может не быть. В базу
при старте он не ходит вовсе, поэтому непромигрированную базу переживает без единой
ошибки.

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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine
from app.db.wakeup import journal_wakeup
from app.mcp.server import create_server

logger = get_logger("mcp")


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
    try:
        async with journal_listener():
            await server.run_streamable_http_async(
                host=settings.mcp_host,
                port=settings.mcp_port,
                streamable_http_path=settings.mcp_path,
            )
    finally:
        await dispose_engine()
        logger.info("MCP server stopped")


if __name__ == "__main__":
    asyncio.run(run())
