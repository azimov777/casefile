"""Граница транзакции: успешное завершение коммитит, исключение откатывает.

Проверяются оба входа — HTTP-запрос через `get_session` и прямой `session_scope`, которым
пользуются воркеры. Тесты идут мимо фикстуры `app`: она подменяет `get_session` сессией
теста, а проверить надо именно настоящую зависимость.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import SessionDep
from app.core.errors import ConflictError
from app.db import session as session_module
from app.main import create_app

PROBE_TABLE = "transaction_probe"


@pytest.fixture
async def probe_table(engine: AsyncEngine) -> AsyncIterator[None]:
    """Таблица-проба вне транзакции теста: иначе не увидеть, что коммит действительно был."""
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE TABLE {PROBE_TABLE} (value integer primary key)"))
    yield
    async with engine.begin() as connection:
        await connection.execute(text(f"DROP TABLE {PROBE_TABLE}"))


@pytest.fixture
def app_sessionmaker(
    engine: AsyncEngine,
    probe_table: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Фабрика сессий приложения переводится на тестовый движок, поведение — настоящее."""
    monkeypatch.setattr(
        session_module,
        "_sessionmaker",
        async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False),
    )


@pytest.fixture
async def probe_client(app_sessionmaker: None) -> AsyncIterator[AsyncClient]:
    """Приложение с настоящей зависимостью `get_session`, без подмен из фикстуры `app`."""
    application: FastAPI = create_app()

    @application.post("/probe/{value}")
    async def _probe(value: int, session: SessionDep) -> dict[str, int]:
        await _insert(session, value)
        if value < 0:
            raise ConflictError("Probe failed on purpose")
        return {"value": value}

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as client:
        yield client


async def _insert(session: AsyncSession, value: int) -> None:
    await session.execute(
        text(f"INSERT INTO {PROBE_TABLE} (value) VALUES (:value)"),
        {"value": value},
    )


async def _stored_values(engine: AsyncEngine) -> list[int]:
    """Читает пробу отдельным соединением: незакоммиченное сюда не попадёт."""
    async with engine.connect() as connection:
        result = await connection.execute(text(f"SELECT value FROM {PROBE_TABLE} ORDER BY value"))
        return list(result.scalars())


async def test_successful_request_commits(probe_client: AsyncClient, engine: AsyncEngine) -> None:
    response = await probe_client.post("/probe/1")

    assert response.status_code == 200
    assert await _stored_values(engine) == [1]


async def test_failed_request_rolls_back(probe_client: AsyncClient, engine: AsyncEngine) -> None:
    """Доменное исключение обязано откатывать запись, а не оставлять половину изменений."""
    response = await probe_client.post("/probe/-1")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert await _stored_values(engine) == []


async def test_session_scope_commits_on_success(
    app_sessionmaker: None,
    engine: AsyncEngine,
) -> None:
    """Воркер получает ту же границу транзакции, что и HTTP-запрос."""
    async with session_module.session_scope() as session:
        await _insert(session, 10)

    assert await _stored_values(engine) == [10]


async def test_session_scope_rolls_back_on_error(
    app_sessionmaker: None,
    engine: AsyncEngine,
) -> None:
    with pytest.raises(ConflictError):
        async with session_module.session_scope() as session:
            await _insert(session, 11)
            raise ConflictError("Worker failed on purpose")

    assert await _stored_values(engine) == []
