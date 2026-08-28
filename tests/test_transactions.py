"""Граница транзакции: успешное завершение коммитит, исключение откатывает.

Проверяются оба входа — HTTP-запрос через `get_session` и прямой `session_scope`, которым
пользуются воркеры. Тесты идут мимо фикстуры `app`: она подменяет `get_session` сессией
теста, а проверить надо именно настоящую зависимость.

Отдельная история — падение самого коммита. Оно возможно у отложенных ограничений
(`DEFERRABLE INITIALLY DEFERRED`): вставка проходит, а `COMMIT` отказывает. Такой отказ
случается уже после того, как обработчик вернул результат, и без специальных мер уходит
мимо обработчиков ошибок — клиент получает оборванный ответ вместо оболочки ошибки.
Меры две, и обе проверяются здесь: `SessionDep` объявлен с областью `function`
(`app/api/deps.py`), а нарушение целостности переводится в `conflict`
(`app/db/session.py`).

Там же, в `app/db/session.py`, живёт разбор ошибок драйвера на «ожидаемое состояние
старта» и «поломку» — `schema_is_missing`. Его проверки в конце файла: ошибаться он может
только в одну из двух сторон, и обе дорого стоят, поэтому проверяются обе.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import SessionDep
from app.core.errors import ConflictError
from app.db import session as session_module
from app.main import create_app

PROBE_TABLE = "transaction_probe"
DEFERRED_PROBE_TABLE = "deferred_probe"


@pytest.fixture
async def probe_table(engine: AsyncEngine) -> AsyncIterator[None]:
    """Таблица-проба вне транзакции теста: иначе не увидеть, что коммит действительно был."""
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE TABLE {PROBE_TABLE} (value integer primary key)"))
    yield
    async with engine.begin() as connection:
        await connection.execute(text(f"DROP TABLE {PROBE_TABLE}"))


@pytest.fixture
async def deferred_probe_table(engine: AsyncEngine) -> AsyncIterator[None]:
    """Таблица с отложенным ограничением: единственный способ уронить именно коммит.

    Ограничение проверяется в конце транзакции, а не на вставке, поэтому две одинаковые
    строки вставляются успешно и отказывает `COMMIT`. Дубликат ключа задачи ведёт себя
    так же, если ограничение объявлено отложенным, — а вести себя иначе клиент не должен.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                f"CREATE TABLE {DEFERRED_PROBE_TABLE} ("
                "value integer, "
                f"CONSTRAINT uq_{DEFERRED_PROBE_TABLE}_value UNIQUE (value) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
        )
    yield
    async with engine.begin() as connection:
        await connection.execute(text(f"DROP TABLE {DEFERRED_PROBE_TABLE}"))


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

    @application.post("/probe-deferred/{value}")
    async def _probe_deferred(value: int, session: SessionDep) -> dict[str, int]:
        """Две одинаковые строки: обе вставляются, отказывает коммит."""
        for _ in range(2):
            await session.execute(
                text(f"INSERT INTO {DEFERRED_PROBE_TABLE} (value) VALUES (:value)"),
                {"value": value},
            )
        return {"value": value}

    @application.post("/probe-duplicate-issue-key")
    async def _probe_duplicate_issue_key(session: SessionDep) -> dict[str, str]:
        """Дубликат ключа задачи, обнаруженный сразу на вставке, а не на коммите."""
        await session.execute(
            text(
                "INSERT INTO issues (key, queue_id, issue_type_id, status_id, "
                "summary, author_id) "
                "SELECT :key, q.id, q.default_issue_type_id, q.default_status_id, "
                ":summary, q.owner_id FROM queues q WHERE q.key = :queue"
            ),
            {"key": "DUP-1", "summary": "Проба", "queue": "DUP"},
        )
        await session.flush()
        return {"key": "DUP-1"}

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


async def test_failing_commit_reaches_the_client_as_a_conflict(
    probe_client: AsyncClient,
    deferred_probe_table: None,
    engine: AsyncEngine,
) -> None:
    """Упавший коммит обязан прийти клиенту единой оболочкой ошибки, а не пятисоткой.

    Без области `function` у `SessionDep` этот тест падает не проверкой, а
    `RuntimeError: Caught handled exception, but response already started`: FastAPI
    закрывает зависимости после отправки ответа, и обработчику ошибок уже некуда писать.
    """
    response = await probe_client.post("/probe-deferred/1")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["details"]["reason"] == "integrity_violation"

    async with engine.connect() as connection:
        stored = await connection.execute(text(f"SELECT value FROM {DEFERRED_PROBE_TABLE}"))
    assert list(stored.scalars()) == []


async def test_duplicate_issue_key_is_a_conflict_not_a_five_hundred(
    probe_client: AsyncClient,
    engine: AsyncEngine,
) -> None:
    """Тот же ответ, когда база отказывает не на коммите, а сразу на вставке.

    Клиент не должен различать эти два случая: и там, и там это конфликт состояния.
    Очередь заводится и убирается прямо здесь — тест идёт мимо фикстур с откатом,
    потому что проверяет настоящую границу транзакции.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO queues (key, name, owner_id, default_issue_type_id, "
                "default_status_id) "
                "SELECT 'DUP', 'Проба', a.id, t.id, s.id FROM actors a, issue_types t, statuses s "
                "WHERE a.key = 'system' AND t.key = 'task' AND t.queue_id IS NULL "
                "AND s.key = 'open' AND s.queue_id IS NULL"
            )
        )
    try:
        first = await probe_client.post("/probe-duplicate-issue-key")
        assert first.status_code == 200

        second = await probe_client.post("/probe-duplicate-issue-key")

        assert second.status_code == 409
        error = second.json()["error"]
        assert error["code"] == "conflict"
        assert error["details"]["constraint"] == "uq_issues_key"
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM issues WHERE key = 'DUP-1'"))
            await connection.execute(text("DELETE FROM queues WHERE key = 'DUP'"))


# --- Непромигрированная база отличается от поломки -----------------------------------


async def test_missing_table_reads_as_an_unmigrated_schema(engine: AsyncEngine) -> None:
    """Первые секунды контура таблиц нет, и это состояние обязано отличаться от сбоя.

    Иначе воркер и планировщик пишут полноэкранную трассировку каждые пять секунд, пока
    человек не применит миграции, — и настоящую ошибку старта в этой простыне не найти.
    """
    with pytest.raises(ProgrammingError) as failure:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM there_is_no_such_table"))

    assert session_module.schema_is_missing(failure.value) is True


async def test_missing_column_does_not_read_as_an_unmigrated_schema(
    probe_table: None,
    engine: AsyncEngine,
) -> None:
    """Таблица есть, а колонки нет — это миграции, применённые не до конца, то есть поломка.

    Граница проверки проходит здесь намеренно: расширить её до «любой ошибки схемы»
    значило бы превратить настоящий дефект выкладки в строку предупреждения.
    """
    with pytest.raises(ProgrammingError) as failure:
        async with engine.connect() as connection:
            await connection.execute(text(f"SELECT no_such_column FROM {PROBE_TABLE}"))

    assert session_module.schema_is_missing(failure.value) is False


async def test_integrity_violation_does_not_read_as_an_unmigrated_schema(
    probe_table: None,
    engine: AsyncEngine,
) -> None:
    """Нарушение целостности — сбой, и трассировку у него отбирать нельзя."""
    with pytest.raises(IntegrityError) as failure:
        async with engine.begin() as connection:
            await connection.execute(text(f"INSERT INTO {PROBE_TABLE} VALUES (1), (1)"))

    assert session_module.schema_is_missing(failure.value) is False
