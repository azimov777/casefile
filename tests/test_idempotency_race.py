"""Одновременные повторы одного ключа: десять запросов, одна задача.

Проверку нельзя поставить на фикстуре `db_session`: она живёт внутри одной транзакции
теста, а уникальный индекс, на котором держится весь механизм, срабатывает только
**между** транзакциями. Тест на общей сессии был бы зелёным и на коде, который просто
ищет ключ и вставляет, если не нашёл, — то есть проверял бы последовательный вызов под
видом одновременного.

Поэтому здесь всё своё: движок прогона, фабрика сессий с настоящими коммитами,
приложение с настоящей зависимостью `get_session`, `asyncio.Barrier` вместо надежды на
планировщик и ручная уборка закоммиченных строк в `finally`.

Проверять, что тест **умеет падать**, надо так: заменить в `app/services/idempotency.py`
занятие ключа наивным «поискал, не нашёл — сделал и записал» (убрать точку сохранения и
разбор нарушения уникальности). Девять запросов ответят `409`, потому что дубликат
всплывёт на коммите, и проверка статусов покраснеет.

## Прогрев токена обязателен, иначе гонки не будет

Первый запрос новым токеном обновляет `tokens.last_used_at`, а сессия приложения
сбрасывает это изменение на первом же `SELECT`. Строка токена оказывается
заблокированной до конца транзакции, и остальные девять запросов тем же токеном ждут
**до** того, как дойдут до ключа: первый успевает зафиксироваться, они находят готовый
ответ и до уникального индекса не добираются. Отметка держится минуту
(`LAST_USED_THROTTLE`), поэтому один прогревочный `GET` перед барьером возвращает
настоящую одновременность. Без него тест зелёный и на наивной реализации.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import session as session_module
from app.domain.idempotency import IDEMPOTENCY_KEY_HEADER
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope
from app.main import create_app
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR

CONCURRENCY = 10
KEY = "race-key"
PROJECT_KEY = "RACEIDEM"


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий поверх движка прогона: каждая коммитит по-настоящему."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def committed_installation(
    committing_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[str]:
    """Участник, токен и проект, видимые другим соединениям; отдаёт секрет токена.

    Заодно переводит фабрику сессий приложения на движок прогона: приложение обязано
    ходить настоящей зависимостью `get_session`, иначе десять «одновременных» запросов
    поделили бы одну сессию и никакой гонки не случилось бы.
    """
    monkeypatch.setattr(
        session_module,
        "_sessionmaker",
        async_sessionmaker(bind=engine_of(committing_sessions), expire_on_commit=False),
    )

    async with committing_sessions() as session:
        owner = await participants_service.register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.HUMAN,
            name="race_owner",
            description="Владелец гоночной установки",
        )
        issued = await tokens_service.issue_token(
            session,
            actor=TRACKER_ACTOR,
            participant=owner,
            scope=TokenScope.MAIN,
            name="race",
        )
        await projects_service.create_project(
            session,
            actor=TRACKER_ACTOR,
            key=PROJECT_KEY,
            title="Гонка ключей",
        )
        await session.commit()
        secret, owner_id = issued.secret, owner.id

    try:
        yield secret
    finally:
        async with committing_sessions() as session:
            # Записи дела неизменяемы триггером, и уборка закоммиченных строк — то самое
            # единственное место, где его законно выключить (`docs/notes/db.md`).
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(
                text(
                    "DELETE FROM entries WHERE task_id IN (SELECT id FROM tasks WHERE project_id "
                    "IN (SELECT id FROM projects WHERE key = :key))"
                ),
                {"key": PROJECT_KEY},
            )
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            await session.execute(
                text(
                    "DELETE FROM tasks "
                    "WHERE project_id IN (SELECT id FROM projects WHERE key = :key)"
                ),
                {"key": PROJECT_KEY},
            )
            await session.execute(
                text("DELETE FROM projects WHERE key = :key"), {"key": PROJECT_KEY}
            )
            # Ключи идемпотентности уезжают каскадом за токеном, токены — за участником.
            await session.execute(text("DELETE FROM participants WHERE id = :id"), {"id": owner_id})
            await session.commit()


def engine_of(sessions: async_sessionmaker[AsyncSession]) -> AsyncEngine:
    """Движок, к которому привязана фабрика: тесту он нужен, чтобы отдать его приложению."""
    engine = sessions.kw["bind"]
    assert isinstance(engine, AsyncEngine)
    return engine


@pytest.fixture
async def live_client(committed_installation: str) -> AsyncIterator[AsyncClient]:
    """Клиент приложения без подмен: каждый запрос открывает свою транзакцию."""
    application: FastAPI = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as client:
        client.headers["Authorization"] = f"Bearer {committed_installation}"
        yield client


async def test_ten_parallel_repeats_create_one_task(live_client: AsyncClient) -> None:
    """Обзорная проверка 4: одна задача, десять одинаковых ответов."""
    body = {
        "project": PROJECT_KEY,
        "title": "Гонка одинаковых ключей",
        "description": "Десять повторов одного вызова",
    }
    # Прогрев: снимает блокировку строки токена с гоночных запросов, см. шапку файла.
    await live_client.get("/api/v1/projects")
    barrier = asyncio.Barrier(CONCURRENCY)

    async def create() -> tuple[int, dict]:
        await barrier.wait()
        response = await live_client.post(
            "/api/v1/tasks",
            json=body,
            headers={IDEMPOTENCY_KEY_HEADER: KEY},
        )
        return response.status_code, response.json()

    answers = await asyncio.gather(*(create() for _ in range(CONCURRENCY)))

    assert {status for status, _ in answers} == {201}, [status for status, _ in answers]
    keys = {payload["data"]["key"] for _, payload in answers}
    assert keys == {f"{PROJECT_KEY}-1"}, keys
    # Ответы совпадают целиком, а не только ключом задачи: проигравшие отдают
    # сохранённый ответ победителя, а не собирают похожий из базы.
    assert all(payload == answers[0][1] for _, payload in answers)

    listing = await live_client.get("/api/v1/tasks", params={"project": PROJECT_KEY})
    assert len(listing.json()["data"]) == 1


async def test_a_failed_call_frees_the_key(live_client: AsyncClient) -> None:
    """Откатившаяся транзакция ключ не занимает: строка ключа откатывается вместе с ней.

    Это свойство, ради которого строка ключа и созданный объект обязаны жить в одной
    транзакции. Занятый ключ после неудачи означал бы, что повтор навсегда получает
    ответ, которого нет.
    """
    key = "race-key-after-failure"
    rejected = await live_client.post(
        "/api/v1/tasks",
        json={"project": PROJECT_KEY, "title": "", "description": "Пустое название"},
        headers={IDEMPOTENCY_KEY_HEADER: key},
    )
    assert rejected.status_code == 422, rejected.text

    accepted = await live_client.post(
        "/api/v1/tasks",
        json={"project": PROJECT_KEY, "title": "Теперь название есть", "description": "Есть"},
        headers={IDEMPOTENCY_KEY_HEADER: key},
    )

    assert accepted.status_code == 201, accepted.text


async def test_an_uncommitted_key_is_invisible_to_another_connection(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_installation: str,
    live_client: AsyncClient,
) -> None:
    """Ключ существует для чужой транзакции только вместе со своим ответом."""
    del committed_installation
    await live_client.post(
        "/api/v1/tasks",
        json={"project": PROJECT_KEY, "title": "Ключ вместе ответом", "description": "Есть"},
        headers={IDEMPOTENCY_KEY_HEADER: "visible-key"},
    )

    async with committing_sessions() as session:
        empty = await session.scalar(
            text("SELECT count(*) FROM idempotency_keys WHERE response IS NULL")
        )

    assert empty == 0
