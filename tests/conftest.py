"""Общие фикстуры тестов.

Схема работы: один раз за прогон создаётся тестовая база и накатываются миграции,
дальше каждый тест получает сессию внутри транзакции, которая после теста
откатывается. Состояние между тестами не переносится, порядок тестов не важен.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _to_asyncpg_dsn(url: str) -> str:
    """SQLAlchemy-адрес → DSN для asyncpg: у драйвера свой префикс схемы."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _create_database_if_missing(url: str) -> None:
    """Создаёт тестовую базу, если её ещё нет.

    Подключение идёт к служебной базе `postgres`: CREATE DATABASE нельзя выполнить,
    находясь внутри создаваемой базы.
    """
    dsn = _to_asyncpg_dsn(url)
    server_dsn, _, database = dsn.rpartition("/")
    connection = await asyncpg.connect(f"{server_dsn}/postgres")
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


def _upgrade_to_head(url: str) -> None:
    """Накатывает миграции. Синхронная: внутри Alembic поднимает свой цикл событий."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def test_database_url(settings: Settings) -> str:
    return settings.effective_test_database_url


@pytest.fixture(scope="session")
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Движок тестовой базы. Базу создаём и мигрируем один раз на весь прогон."""
    await _create_database_if_missing(test_database_url)
    # Миграции — в отдельном потоке: Alembic вызывает asyncio.run, а в текущем
    # потоке уже крутится цикл событий pytest-asyncio.
    await asyncio.to_thread(_upgrade_to_head, test_database_url)

    engine = create_async_engine(test_database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Соединение с открытой внешней транзакцией — граница отката для одного теста."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Сессия внутри транзакции теста.

    `join_transaction_mode="create_savepoint"` — ключевая деталь: коммит внутри
    сценария закрывает вложенный savepoint, а не внешнюю транзакцию. Поэтому тест
    может проверять код, который честно коммитит, и всё равно откатиться в конце.
    """
    session = AsyncSession(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        autoflush=False,
    )
    yield session
    await session.close()


@pytest.fixture
def app(db_session: AsyncSession) -> Iterator[FastAPI]:
    """Приложение, у которого сессия подменена на транзакцию теста."""
    application = create_app()
    application.dependency_overrides[get_session] = lambda: db_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Асинхронный HTTP-клиент поверх ASGI: без сети и без реального сервера."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as http_client:
        yield http_client
