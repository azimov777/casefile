"""Общие фикстуры тестов.

Схема работы: один раз за прогон создаётся тестовая база и накатываются миграции,
дальше каждый тест получает сессию внутри транзакции, которая после теста
откатывается. Состояние между тестами не переносится, порядок тестов не важен.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.project import Portfolio, Project
from app.db.models.queue import Queue
from app.db.session import get_session
from app.domain.actors import ActorType
from app.main import create_app
from app.services import actors as actors_service
from app.services import issues as issues_service
from app.services import projects as projects_service
from app.services import queues as queues_service

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


@pytest.fixture
async def system_actor(db_session: AsyncSession) -> Actor:
    """Системный актор. Создаётся миграцией, поэтому здесь только читается."""
    return await actors_service.get_system_actor(db_session)


@pytest.fixture
async def owner(db_session: AsyncSession) -> Actor:
    """Владелец-человек: инициатор запросов в тестах API."""
    actor, _ = await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.HUMAN,
        key="owner",
        display_name="Owner",
    )
    return actor


@pytest.fixture
async def owner_secret(db_session: AsyncSession, system_actor: Actor, owner: Actor) -> str:
    """Секрет рабочего токена владельца."""
    issued = await actors_service.issue_token(
        db_session, owner, initiator=system_actor, name="tests"
    )
    return issued.secret


@pytest.fixture
async def auth_client(client: AsyncClient, owner_secret: str) -> AsyncClient:
    """Клиент с заголовком авторизации: всё под `/api/v1` требует токена."""
    client.headers["Authorization"] = f"Bearer {owner_secret}"
    return client


@pytest.fixture
async def queue(db_session: AsyncSession, owner: Actor) -> Queue:
    """Очередь `TRK` с набором по умолчанию из глобальных справочников.

    Нужна почти каждому тесту очередей, справочников и (начиная с задачи 05) задач:
    очередь — единственный способ получить рабочую конфигурацию процесса.
    """
    return await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="TRK",
        name="Трекер",
        description="Задачи по разработке трекера",
    )


@pytest.fixture
def make_project(db_session: AsyncSession, owner: Actor) -> Callable[..., Awaitable[Project]]:
    """Фабрика проектов: ключ и название по умолчанию, остальное — как попросят.

    Проект не привязан к очереди намеренно: он собирает задачи из разных очередей, и
    фикстура, требующая очередь, подталкивала бы писать тесты «проект одной очереди» —
    то есть проверять не то, ради чего проект существует.
    """

    async def _make(**kwargs: Any) -> Project:
        return await projects_service.create_project(
            db_session,
            initiator=kwargs.pop("initiator", owner),
            key=kwargs.pop("key", "alpha"),
            name=kwargs.pop("name", "Платформа доставки"),
            **kwargs,
        )

    return _make


@pytest.fixture
def make_portfolio(db_session: AsyncSession, owner: Actor) -> Callable[..., Awaitable[Portfolio]]:
    """Фабрика портфелей."""

    async def _make(**kwargs: Any) -> Portfolio:
        return await projects_service.create_portfolio(
            db_session,
            initiator=kwargs.pop("initiator", owner),
            key=kwargs.pop("key", "platform"),
            name=kwargs.pop("name", "Платформа"),
            **kwargs,
        )

    return _make


@pytest.fixture
def make_issue(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> Callable[..., Awaitable[Issue]]:
    """Фабрика задач: очередь и название по умолчанию, остальное — как попросят.

    Нужна половине тестов проекта, а не только тестам задач: защита справочников и
    реестра полей проверяется настоящими задачами, а не подменой счётчиков.
    """

    async def _make(**kwargs: Any) -> Issue:
        return await issues_service.create_issue(
            db_session,
            initiator=kwargs.pop("initiator", owner),
            queue=kwargs.pop("queue", queue),
            summary=kwargs.pop("summary", "Починить выдачу ключей"),
            **kwargs,
        )

    return _make
