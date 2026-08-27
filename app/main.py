"""Точка входа приложения: сборка FastAPI из слоёв.

Запуск для разработки: `uvicorn app.main:app --reload`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.router import api_router, generate_operation_id
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл процесса: движок БД создаётся лениво, закрывается явно."""
    settings: Settings = app.state.settings
    logger.info("Starting tracker %s in %s environment", __version__, settings.environment)
    yield
    await dispose_engine()
    logger.info("Stopping tracker")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собирает приложение. Фабрика, а не глобальный объект: тесты поднимают свой экземпляр."""
    settings = settings or get_settings()
    configure_logging(debug=settings.debug)

    app = FastAPI(
        title="Tracker API",
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
        # Генератор задан на приложении, а не на роутерах: он должен действовать на все
        # маршруты, включая те, что подключаются мимо `api_router`.
        generate_unique_id_function=generate_operation_id,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)

    return app


app = create_app()
