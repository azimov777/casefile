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
from app.db.session import dispose_engine, schema_is_missing, session_scope
from app.db.wakeup import hub as wakeup_hub
from app.services import automation as automation_service

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл процесса: движок БД создаётся лениво, закрывается явно."""
    settings: Settings = app.state.settings
    logger.info("Starting tracker %s in %s environment", __version__, settings.environment)
    await _sync_automation_rules()
    # Слушатель оповещений поднимается процессом, а не первым ожиданием: ленивый подъём
    # оставил бы за собой соединение, которое некому закрыть в разовом скрипте или в
    # тесте. Не подключился — ожидание переходит на контрольный опрос и говорит об этом
    # в лог, а API стартует как ни в чём не бывало.
    await wakeup_hub.start()
    yield
    await wakeup_hub.close()
    await dispose_engine()
    logger.info("Stopping tracker")


async def _sync_automation_rules() -> None:
    """Заводит строки состояния под правила автоматики, объявленные в коде.

    Сбой не останавливает старт, и это не небрежность: контур поднимается до применения
    миграций (они — отдельный шаг), и первые секунды таблицы `automation_rules` может не
    быть вовсе. Ронять API из-за этого нельзя, а молчать — тем более: список правил
    окажется пустым, и объяснить это будет нечем. Синхронизацию повторяют планировщик и
    воркер при своём старте, поэтому пропущенный здесь заход не теряется.

    Непромигрированная база при этом отделена от настоящего сбоя: она ожидаема, ей
    хватает строки предупреждения, и трассировка на каждом старте с нуля мешала бы
    заметить ту, что означает поломку.
    """
    try:
        async with session_scope() as session:
            created = await automation_service.sync_rules(session)
    except Exception as exc:
        if schema_is_missing(exc):
            logger.warning("Database schema is not migrated yet; rules are not synchronised")
        else:
            logger.exception(
                "Automation rules are not synchronised; the registry may be incomplete"
            )
        return
    if created:
        logger.info("Automation rules registered: %s", ", ".join(created))


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
