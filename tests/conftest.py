"""Общие фикстуры тестов.

Схема работы: один раз за прогон создаётся тестовая база и накатываются миграции,
дальше каждый тест получает сессию внутри транзакции, которая после теста
откатывается. Состояние между тестами не переносится, порядок тестов не важен.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer
from mcp_types import InputRequiredResult
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule
from app.db.models.board import Board
from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.models.project import Portfolio, Project
from app.db.models.queue import Queue
from app.db.models.saved_filter import SavedFilter
from app.db.repositories import AutomationRuleRepository
from app.db.session import get_session
from app.domain.actors import ActorType
from app.domain.catalogs import CatalogKind
from app.main import create_app
from app.mcp.runtime import Runtime, SessionFactory, use_headers
from app.mcp.server import create_server
from app.services import actors as actors_service
from app.services import automation as automation_service
from app.services import boards as boards_service
from app.services import issues as issues_service
from app.services import projects as projects_service
from app.services import queues as queues_service
from app.services import saved_filters as saved_filters_service

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
    сессию как есть. Разница видна ровно там, где она важна: `dry_run` у инструментов
    настройки процесса откатывает транзакцию, и без честного коммита предыдущих вызовов
    он унёс бы вместе с проверкой данные, заведённые фикстурами.
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
def mcp_call(
    mcp_server: MCPServer,
    owner_secret: str,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Вызов инструмента от имени владельца: заголовок авторизации ставится сам.

    Идёт через `MCPServer.call_tool`, а не в обход, — так проверяется и схема
    аргументов, и то, что результат вообще сворачивается в структурированный ответ.
    """

    # Имя инструмента — позиционный параметр (`/`): у инструментов есть аргументы
    # `name` и `queue`, и обычный именованный параметр столкнулся бы с ними.
    async def _call(tool: str, /, **arguments: Any) -> dict[str, Any]:
        async with use_headers({"authorization": f"Bearer {owner_secret}"}):
            result = await mcp_server.call_tool(tool, arguments)
        assert not isinstance(result, InputRequiredResult)
        assert result.structured_content is not None
        return result.structured_content

    return _call


@pytest.fixture
def mcp_read(
    mcp_server: MCPServer,
    owner_secret: str,
) -> Callable[[str], Awaitable[Any]]:
    """Чтение ресурса от имени владельца."""

    async def _read(uri: str) -> Any:
        async with use_headers({"authorization": f"Bearer {owner_secret}"}):
            contents = await mcp_server.read_resource(uri)
        assert not isinstance(contents, InputRequiredResult)
        return json.loads(next(iter(contents)).content)

    return _read


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
def make_saved_filter(
    db_session: AsyncSession,
    owner: Actor,
) -> Callable[..., Awaitable[SavedFilter]]:
    """Фабрика сохранённых фильтров: источник задач для доски.

    Отдельная фикстура, а не создание внутри фабрики доски: доска обязана строиться
    поверх готового фильтра, и тест, которому нужен свой отбор, должен уметь его
    задать — иначе проверять «доска показывает то, что отбирает её фильтр» было бы
    нечем.
    """

    async def _make(**kwargs: Any) -> SavedFilter:
        return await saved_filters_service.create_saved_filter(
            db_session,
            initiator=kwargs.pop("initiator", owner),
            name=kwargs.pop("name", "Задачи доски"),
            query=kwargs.pop("query", "queue: TRK"),
            **kwargs,
        )

    return _make


@pytest.fixture
def resolve_status(db_session: AsyncSession, owner: Actor) -> Callable[[str], Awaitable[Status]]:
    """Ссылка справочника (`open`, `TRK.open`) в запись статуса.

    Нужна тестам досок: колонка описывается набором статусов, и сценарий принимает
    объекты, а не строки, — разрешение ссылки в проекте делает интерфейс.
    """

    async def _resolve(ref: str) -> Status:
        entry = await queues_service.resolve_catalog_ref(
            db_session,
            CatalogKind.STATUS,
            ref,
            initiator=owner,
        )
        assert isinstance(entry, Status)
        return entry

    return _resolve


@pytest.fixture
def make_board(
    db_session: AsyncSession,
    owner: Actor,
    make_saved_filter: Callable[..., Awaitable[SavedFilter]],
) -> Callable[..., Awaitable[Board]]:
    """Фабрика досок. Фильтр создаётся сам, если тест не передал свой.

    Колонки тест задаёт сам: набор статусов — это и есть то, чем одна доска отличается
    от другой, и умолчание здесь прятало бы половину проверяемого.
    """

    async def _make(**kwargs: Any) -> Board:
        saved_filter = kwargs.pop("saved_filter", None)
        if saved_filter is None:
            saved_filter = await make_saved_filter()
        return await boards_service.create_board(
            db_session,
            initiator=kwargs.pop("initiator", owner),
            name=kwargs.pop("name", "Доска команды"),
            saved_filter=saved_filter,
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


@pytest.fixture
async def automation_rules(db_session: AsyncSession) -> dict[str, AutomationRule]:
    """Строки состояния под все объявленные правила, все — выключенными.

    Синхронизация в фикстуре, а не в тесте: движок ищет правило по строке в базе, и
    тест без неё проверял бы «правил нет», думая, что проверяет «правило не сработало».

    Реестр правил глобальный на процесс, поэтому сюда попадают и правила, объявленные
    в самих тестовых модулях. Это безопасно: сработать может только правило, у которого
    строка включена, а включает её тест — внутри своей транзакции.
    """
    await automation_service.sync_rules(db_session)
    return {rule.rule_key: rule for rule in await AutomationRuleRepository(db_session).list_all()}


@pytest.fixture
def enable_rule(
    db_session: AsyncSession,
    owner: Actor,
    automation_rules: dict[str, AutomationRule],
) -> Callable[..., Awaitable[AutomationRule]]:
    """Включает правило и настраивает его — тем же сценарием, что и `PATCH` из API.

    Через сценарий, а не присваиванием в модель: проверка параметров и пересчёт
    расписания живут там, и тест, который их обходит, проверял бы состояние, которого
    настоящая настройка получить не может.
    """

    async def _enable(rule_key: str, **kwargs: Any) -> AutomationRule:
        view = await automation_service.update_rule(
            db_session,
            automation_rules[rule_key],
            initiator=kwargs.pop("initiator", owner),
            is_enabled=kwargs.pop("is_enabled", True),
            **kwargs,
        )
        return view.rule

    return _enable
