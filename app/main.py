"""Точка входа приложения: сборка FastAPI из слоёв.

Запуск для разработки: `uvicorn app.main:app --reload`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.client_address import ClientAddresses
from app.api.errors import register_exception_handlers
from app.api.router import api_router, generate_operation_id, session_router
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.shutdown import shutdown
from app.db.session import dispose_engine
from app.db.wakeup import journal_wakeup
from app.services.login import PasswordLogin

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл процесса: слушатель журнала поднимается, движок БД закрывается.

    Запросов к схеме при старте нет вовсе: миграции — отдельный шаг Compose, и контур
    поднимается раньше, чем схема появляется. Запрос к непромигрированной базе здесь
    означал бы падение старта на ровном месте.

    Слушатель оповещений журнала (`LISTEN/NOTIFY`) схемы не требует и потому поднимается
    здесь, а не при первом ожидании: ленивый подъём оставлял бы за собой соединение,
    которое некому закрыть в разовом скрипте. Не подключился — в логе строка, ожидание
    переходит на контрольный опрос; ронять из-за этого API нельзя.

    Подписка на сигнал остановки ставится **здесь**, а не в самом сигнале, и это
    единственное место, где она может стоять: uvicorn ставит свои обработчики до запуска
    жизненного цикла, и наш встаёт поверх, вызывая прежний следом (`app/core/shutdown.py`).
    Без неё поток ленты не кончается никогда, и сервер не останавливается вовсе.
    """
    settings: Settings = app.state.settings
    logger.info("Starting tracker %s in %s environment", __version__, settings.environment)
    await journal_wakeup.start()
    with shutdown.listening(on_begin=journal_wakeup.wake_all):
        yield
    await journal_wakeup.close()
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
    # Сеансы входа по паролю и окно попыток живут столько же, сколько приложение
    # (`app/services/login.py`). Испорченный `TRACKER_PASSWORD_HASH` роняет здесь сборку,
    # то есть старт процесса, а не первую попытку входа.
    app.state.password_login = PasswordLogin.from_settings(settings)
    # Кому верить адрес клиента для окна попыток (`TRACKER_REAL_IP_FROM`); имена хостов в
    # нём разрешаются при попытке входа, а не здесь — `ui` поднимается позже API.
    app.state.client_addresses = ClientAddresses.from_settings(settings)

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
    app.include_router(session_router)

    return app


app = create_app()
