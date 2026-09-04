"""Ожидание ленты из MCP: пустой ответ по таймауту и пробуждение оповещением.

Две проверки, и вторая не следует из первой. Пустой ответ по таймауту приходит и тогда,
когда слушатель `LISTEN/NOTIFY` в процессе не поднят вовсе: ожидание молча переходит на
контрольный опрос и продолжает «работать», отвечая с задержкой до
`TRACKER_JOURNAL_WAIT_POLL_INTERVAL` секунд. Поймать это можно единственным способом —
подшить запись **другим соединением** и убедиться, что ответ пришёл **быстрее** опроса.

Поэтому второй тест идёт не на общей фикстуре с откатом: оповещение PostgreSQL рассылает
при фиксации, и в откатившейся транзакции его не будет вовсе. Здесь свои сессии поверх
движка прогона, с настоящими коммитами, и слушатель, поднятый тем же менеджером, каким
его поднимает процесс MCP (`app/mcp/__main__.py`, `journal_listener`).

Из настоящих коммитов следует и остальное устройство: участник, токен и задача заводятся
видимыми другим соединениям, а уборка ручная. У записей дела она особенная — они
неизменяемы на уровне схемы, и удалить закоммиченные строки можно, только выключив
триггер на время уборки.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from mcp.server.mcpserver import MCPServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models.author import created_by_columns
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.db.session import asyncpg_dsn, transaction
from app.db.wakeup import journal_wakeup
from app.domain.authors import TRACKER
from app.domain.participants import ParticipantKind
from app.domain.tasks import TaskField
from app.domain.tokens import TokenScope
from app.mcp.__main__ import journal_listener
from app.mcp.runtime import Runtime
from app.mcp.server import create_server
from app.services import case as case_service
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from conftest import Connect, call, connect_mcp, refuse

#: Сколько ждёт тест, которому ждать нечего. Меньше контрольного опроса — иначе он
#: проверял бы опрос, а не истёкший таймаут.
SHORT_TIMEOUT = 2.0

#: Номер, после которого записей заведомо нет: `seq` выдаётся с единицы и монотонно.
BEYOND_THE_TAIL = 10**9


# --- Ожидание на транзакции теста -----------------------------------------------------


async def test_an_empty_tail_answers_when_the_wait_runs_out(
    mcp_session: Connect, task_secret: str
) -> None:
    """Обзорная проверка 7: ждать нечего — пустой список примерно через две секунды.

    Пустой ответ по истечении ожидания не ошибка и не отдельный код: «ничего не
    случилось» и есть пустая коллекция.
    """
    loop = asyncio.get_running_loop()
    async with mcp_session(task_secret) as session:
        began = loop.time()
        page = await call(session, "wait_journal", after=BEYOND_THE_TAIL, timeout=SHORT_TIMEOUT)
        elapsed = loop.time() - began

    assert page == {"items": [], "next_cursor": None}
    assert SHORT_TIMEOUT * 0.8 <= elapsed < SHORT_TIMEOUT + 3, elapsed


async def test_asking_for_a_longer_wait_than_allowed_is_refused(
    mcp_session: Connect, task_secret: str
) -> None:
    """Потолок ожидания — отказ, а не молча срезанное значение.

    Попросивший десять минут и получивший минуту истолковал бы пустой ответ как «за
    десять минут ничего не произошло».
    """
    async with mcp_session(task_secret) as session:
        failure = await refuse(session, "wait_journal", timeout=600)

    assert "journal_wait_too_long" in failure


async def test_the_wait_reads_the_tail_it_already_has(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Хвост, который уже есть, отдаётся сразу: ожидание начинается с чтения."""
    async with mcp_session(task_secret) as session:
        page = await call(session, "wait_journal", after=0, task=task.key)

    assert [item["type"] for item in page["items"]] == ["created"]
    assert page["items"][0]["task_key"] == task.key


# --- Пробуждение оповещением ----------------------------------------------------------


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Сессии с настоящими коммитами: оповещение доходит только на фиксации."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def committed_world(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[str, Task]]:
    """Токен и задача, видимые другим соединениям, и уборка за собой.

    Токен и участник фиксируются вместе с задачей: ждущий пойдёт по настоящей сессии, а
    строки, заведённые в откатываемой транзакции теста, для неё не существуют.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    async with committing_sessions() as session:
        participant = await participants_service.register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.AGENT,
            name=f"waker{suffix}",
            description="Проверка пробуждения",
        )
        issued = await tokens_service.issue_token(
            session,
            actor=TRACKER_ACTOR,
            participant=participant,
            scope=TokenScope.TASK,
            name="wake test",
        )
        queue = Queue(key=f"WAKE{suffix}", title="Пробуждение", **created_by_columns(TRACKER))
        session.add(queue)
        await session.flush()
        task = Task(
            key=f"{queue.key}-1",
            queue=queue,
            title="Задача для пробуждения",
            description="Есть",
            **created_by_columns(TRACKER),
        )
        session.add(task)
        await session.commit()
        secret = issued.secret
        ids = {
            "task": task.id,
            "queue": queue.id,
            "token": issued.token.id,
            "participant": participant.id,
        }

    try:
        yield secret, task
    finally:
        async with committing_sessions() as session:
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(
                text("DELETE FROM entries WHERE task_id = :task"), {"task": ids["task"]}
            )
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            await session.execute(text("DELETE FROM tasks WHERE id = :task"), {"task": ids["task"]})
            await session.execute(
                text("DELETE FROM queues WHERE id = :queue"), {"queue": ids["queue"]}
            )
            await session.execute(
                text("DELETE FROM idempotency_keys WHERE token_id = :token"),
                {"token": ids["token"]},
            )
            await session.execute(
                text("DELETE FROM tokens WHERE id = :token"), {"token": ids["token"]}
            )
            await session.execute(
                text("DELETE FROM participants WHERE id = :participant"),
                {"participant": ids["participant"]},
            )
            await session.commit()


@pytest.fixture
def committing_server(committing_sessions: async_sessionmaker[AsyncSession]) -> MCPServer:
    """MCP-сервер на настоящих сессиях: транзакция теста здесь не годится.

    Ждущий обязан увидеть строку, подшитую другим соединением, а сессия внутри
    откатываемой транзакции теста чужих фиксаций не увидит никогда.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        # Граница берётся боевая: своя копия разошлась бы с ней молча — например, не
        # переводила бы нарушение целостности в доменный отказ.
        async with committing_sessions() as session, transaction(session):
            yield session

    return create_server(runtime=Runtime(sessions=scope))


async def test_the_wait_wakes_up_before_the_fallback_poll(
    committing_server: MCPServer,
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_world: tuple[str, Task],
    test_database_url: str,
) -> None:
    """Обзорная проверка 7a: ответ приходит быстрее контрольного опроса.

    Это и есть доказательство, что слушатель оповещений в процессе MCP поднят. Проверка 7
    его не поймала бы: без слушателя ожидание не ломается, а молча переходит на опрос.

    Слушатель поднимается **тем же** менеджером, каким его поднимает процесс
    (`app/mcp/__main__.py`), а не прямым вызовом `journal_wakeup.start`: иначе тест
    проверял бы механизм, а не то, что процесс им пользуется.
    """
    secret, task = committed_world
    poll = get_settings().journal_wait_poll_interval
    assert poll > 2.0, (
        "контрольный опрос настроен чаще проверки — тест перестал отличать оповещение "
        f"от опроса (journal_wait_poll_interval={poll})"
    )

    async with committing_sessions() as reading:
        start = await EntryRepository(reading).latest_seq()

    loop = asyncio.get_running_loop()

    async def append_later() -> int:
        await asyncio.sleep(0.5)
        async with committing_sessions() as writing:
            written = await writing.get(Task, task.id)
            assert written is not None
            entry = await case_service.record_section_changed(
                writing,
                written,
                actor=TRACKER_ACTOR,
                field=TaskField.GOAL,
                before="",
                after="разбудили",
            )
            await writing.commit()
            return entry.seq

    async with journal_listener(asyncpg_dsn(test_database_url)):
        assert journal_wakeup.is_listening, "слушатель не поднялся — тест проверял бы опрос"
        writer = asyncio.create_task(append_later())
        began = loop.time()
        async with connect_mcp(committing_server, secret) as session:
            page = await call(session, "wait_journal", after=start, timeout=30)
        elapsed = loop.time() - began
        expected = await writer

    assert [item["seq"] for item in page["items"]] == [expected]
    assert elapsed < poll, f"ожидание длилось {elapsed:.1f}: разбудил опрос, не оповещение"
