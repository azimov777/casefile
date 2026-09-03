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
"""

import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.mcp.server import create_server

logger = get_logger("mcp")


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
    await server.run_streamable_http_async(
        host=settings.mcp_host,
        port=settings.mcp_port,
        streamable_http_path=settings.mcp_path,
    )


if __name__ == "__main__":
    asyncio.run(run())
