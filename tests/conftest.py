"""Общие фикстуры тестов.

Схема работы: один раз за прогон создаётся тестовая база и накатываются миграции,
дальше каждый тест получает сессию внутри транзакции, которая после теста
откатывается. Состояние между тестами не переносится, порядок тестов не важен.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.session import get_session
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope
from app.main import create_app
from app.mcp.runtime import Runtime, SessionFactory
from app.mcp.server import create_server
from app.services import participants as participants_service
from app.services import queues as queues_service
from app.services import tasks as tasks_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor

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
def mcp_sessions(db_session: AsyncSession) -> SessionFactory:
    """Фабрика сессий MCP-сервера: та же граница транзакции, но на сессии теста.

    Повторяет `session_scope` (коммит на выходе, откат на исключении), а не отдаёт
    сессию как есть: инструмент, который откатывает свою транзакцию, не должен уносить
    с собой данные, заведённые фикстурами до него.
    """

    @asynccontextmanager
    async def _scope() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise
        else:
            await db_session.commit()

    return _scope


@pytest.fixture
def mcp_server(mcp_sessions: SessionFactory) -> MCPServer:
    """MCP-сервер, у которого сессия подменена на транзакцию теста."""
    return create_server(runtime=Runtime(sessions=mcp_sessions))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Асинхронный HTTP-клиент поверх ASGI: без сети и без реального сервера."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as http_client:
        yield http_client


@pytest.fixture
async def owner(db_session: AsyncSession) -> Participant:
    """Владелец-человек: от его имени идут запросы в тестах API.

    Заводится от имени трекера — ровно как это делает первичная инициализация: другого
    автора на пустой установке не существует.
    """
    return await participants_service.register_participant(
        db_session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.HUMAN,
        name="owner",
        description="Владелец установки",
    )


@pytest.fixture
async def main_secret(db_session: AsyncSession, owner: Participant) -> str:
    """Секрет токена владельца с набором `main`: им можно всё."""
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name="tests",
    )
    return issued.secret


@pytest.fixture
async def task_secret(db_session: AsyncSession, owner: Participant) -> str:
    """Секрет именного токена с набором `task`: рабочий цикл без управления установкой."""
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.TASK,
        name="tests task scope",
    )
    return issued.secret


@pytest.fixture
async def shared_secret(db_session: AsyncSession) -> str:
    """Секрет общего агентского токена: без участника, подпись приезжает заголовком."""
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        scope=TokenScope.TASK,
        name="tests shared",
    )
    return issued.secret


@pytest.fixture
def main_actor(owner: Participant) -> Actor:
    """Структура автора для прямых вызовов сценариев: владелец с набором `main`."""
    return Actor(
        author=owner.author,
        scope=TokenScope.MAIN,
        participant=owner,
    )


@pytest.fixture
def task_actor(owner: Participant) -> Actor:
    """То же, но с набором `task`: им проверяются отказы единой точки прав."""
    return Actor(
        author=owner.author,
        scope=TokenScope.TASK,
        participant=owner,
    )


@pytest.fixture
async def auth_client(client: AsyncClient, main_secret: str) -> AsyncClient:
    """Клиент с заголовком авторизации: всё под `/api/v1` требует токена.

    Возвращает **тот же** объект, что и `client`: заголовок проставляется существующему
    клиенту. Тест, взявший обе фикстуры ради «двух разных токенов», на самом деле ходит
    одним — менять токен надо по ходу теста, а не двумя клиентами.
    """
    client.headers["Authorization"] = f"Bearer {main_secret}"
    return client


@pytest.fixture
async def queue(db_session: AsyncSession, main_actor: Actor) -> Queue:
    """Очередь `TRK`: на ней проверяется всё, что требует существующей очереди."""
    return await queues_service.create_queue(
        db_session,
        actor=main_actor,
        key="TRK",
        title="Трекер",
        description="Бэкенд трекера",
    )


@pytest.fixture
async def task(db_session: AsyncSession, task_actor: Actor, queue: Queue) -> Task:
    """Задача `TRK-1` в `backlog` с заполненными разделами: готова к переходу в `open`.

    Заводится набором `task`, как это делает агент: автор её записей — владелец, но
    право на создание задачи не требует `main`.
    """
    return await tasks_service.create_task(
        db_session,
        actor=task_actor,
        queue=queue,
        title="Починить выдачу ключей задач",
        description="Ключ выдаётся до валидации и сгорает на неудачном запросе",
        goal="Ключи не сгорают на отклонённых запросах",
        context="Номер выдаёт `queues.next_task_number` последним",
        constraints="Счётчик очереди не переписывать",
        output="Тест на несгоревший номер",
        checks=["Создание задачи без названия не тратит номер"],
    )
