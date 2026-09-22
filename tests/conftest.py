"""Общие фикстуры тестов.

Схема работы: один раз за прогон создаётся тестовая база и накатываются миграции,
дальше каждый тест получает сессию внутри транзакции, которая после теста
откатывается. Состояние между тестами не переносится, порядок тестов не важен.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg

# `httpx2` — зависимость самого SDK MCP, а не проекта: клиент `streamable_http_client`
# принимает именно его `AsyncClient`. Проектной зависимостью объявлять его нельзя —
# приложение им не пользуется, — а подсунуть вместо него `httpx` 0.28 не выйдет: типы
# транспорта у них разные (`docs/notes/mcp.md`).
import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.session import get_session, transaction
from app.domain.authors import ACTOR_LABEL_HEADER
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
from app.services.setup import ensure_admin_account
from mcp import ClientSession

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


def alembic_config(url: str) -> Config:
    """Конфиг Alembic, направленный на эту базу.

    Публичная и одна на весь набор: тест миграций гоняет `upgrade` и `downgrade` по
    своей базе, и вторая сборка конфига разъехалась бы с этой на первой же правке путей.
    """
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _upgrade_to_head(url: str) -> None:
    """Накатывает миграции. Синхронная: внутри Alembic поднимает свой цикл событий."""
    command.upgrade(alembic_config(url), "head")


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

    Ради этого же — коммит **на входе**. Сессия теста живёт в режиме
    `create_savepoint`, и всё, что фикстуры записали без коммита, лежит внутри текущей
    точки сохранения: откат отклонённого вызова унёс бы вместе со своей работой и
    очередь, и токен, а следующий вызов ответил бы `unauthorized` — далеко от места
    ошибки. Коммит закрывает точку сохранения фикстур и открывает вызову свою.

    Следствие для тестов: после **отклонённого** вызова объекты ORM, прочитанные до
    него, устарели (откат снимает с них значения), и обращение к их полям уходит за
    данными в базу вне async-контекста — `MissingGreenlet` на ровном месте. Ключи задач
    поэтому запоминают строкой **до** вызова, а не читают из объекта после.

    Сама граница берётся боевая (`app/db/session.py`, `transaction`), а не пишется здесь
    заново: она переводит нарушение целостности в доменный конфликт, и фикстура с
    собственной копией отдавала бы инструменту сырой `IntegrityError` — то есть была бы
    зелёной ровно там, где боевой код сломан.
    """

    @asynccontextmanager
    async def _scope() -> AsyncIterator[AsyncSession]:
        await db_session.commit()
        async with transaction(db_session):
            yield db_session

    return _scope


@pytest.fixture
def mcp_server(mcp_sessions: SessionFactory) -> MCPServer:
    """MCP-сервер, у которого сессия подменена на транзакцию теста."""
    return create_server(runtime=Runtime(sessions=mcp_sessions))


#: Базовый адрес клиента MCP в тестах. Порт обязателен: у эндпоинта стоит защита от DNS
#: rebinding, и её список разрешённых значений `Host` — это `localhost:*` и `127.0.0.1:*`.
#: Голый `localhost` под шаблон не подходит и отвергается `421` ещё до обработчика
#: (`docs/notes/mcp.md`).
MCP_BASE_URL = "http://localhost:8100"

#: Как тест подключается к серверу: контекстный менеджер, отдающий готовую сессию клиента.
type Connect = Callable[..., AbstractAsyncContextManager[ClientSession]]


@asynccontextmanager
async def connect_mcp(
    server: MCPServer,
    secret: str,
    *,
    label: str | None = None,
) -> AsyncIterator[ClientSession]:
    """Сессия настоящего клиента SDK поверх ASGI: без сети и без занятого порта.

    Инструменты проверяются именно через клиент, а не вызовом функции: половина того, что
    может сломаться, живёт не в теле инструмента — это разбор аргументов по схеме, разбор
    заголовка с токеном, промежуточные слои и свёртка результата.

    Жизненный цикл приложения открывается руками: `ASGITransport` его не запускает, а
    менеджер сессий streamable HTTP заводит свою группу задач именно там и без неё
    отвечает `Task group is not initialized`.
    """
    application = server.streamable_http_app()
    headers = {"Authorization": f"Bearer {secret}"}
    if label is not None:
        headers[ACTOR_LABEL_HEADER] = label
    async with application.router.lifespan_context(application):
        http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(application),
            base_url=MCP_BASE_URL,
            headers=headers,
            timeout=60,
        )
        async with (
            http_client,
            streamable_http_client(f"{MCP_BASE_URL}/mcp", http_client=http_client) as streams,
        ):
            read, write = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@pytest.fixture
def mcp_session(mcp_server: MCPServer) -> Connect:
    """Подключение к серверу теста: `async with mcp_session(secret) as session`."""

    def connect(
        secret: str, *, label: str | None = None
    ) -> AbstractAsyncContextManager[ClientSession]:
        return connect_mcp(mcp_server, secret, label=label)

    return connect


def tool_text(result: CallToolResult) -> str:
    """Текст результата инструмента: по нему агент читает и данные, и причину отказа."""
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def call(session: ClientSession, tool: str, /, **arguments: Any) -> dict[str, Any]:
    """Успешный вызов инструмента. Возвращает структурированный результат.

    Параметры до `/` — только позиционные: у инструментов есть аргументы `name` и
    `session`, и с обычными параметрами такой вызов падал бы `TypeError`.
    """
    result = await session.call_tool(tool, arguments)
    assert not result.is_error, tool_text(result)
    assert result.structured_content is not None
    return result.structured_content


async def refuse(session: ClientSession, tool: str, /, **arguments: Any) -> str:
    """Вызов, который обязан отказать. Возвращает текст отказа с кодом и подробностями."""
    result = await session.call_tool(tool, arguments)
    assert result.is_error, f"вызов {tool} прошёл, хотя должен был отказать: {tool_text(result)}"
    return tool_text(result)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Асинхронный HTTP-клиент поверх ASGI: без сети и без реального сервера."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as http_client:
        yield http_client


@pytest.fixture
async def owner(db_session: AsyncSession) -> Participant:
    """Владелец-человек с учётной записью администратора: от его имени идут запросы API.

    Заводится от имени трекера — ровно как это делает первичная инициализация: другого
    автора на пустой установке не существует. Учётная запись — `owner@localhost`, без
    пароля, как у установки, заведшей себя сама.
    """
    participant = await participants_service.register_participant(
        db_session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.HUMAN,
        name="owner",
        description="Владелец установки",
    )
    # И учётная запись администратора, как у владельца настоящей установки
    # (`app/services/setup.py`): без неё управление людьми отвечало бы `admin_required`.
    await ensure_admin_account(db_session, participant)
    return participant


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
