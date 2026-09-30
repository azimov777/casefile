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
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx2
import pytest
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models.author import created_by_columns
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.db.session import asyncpg_dsn, transaction
from app.db.wakeup import journal_wakeup
from app.domain.authors import TRACKER
from app.domain.journal import MAX_TASK_KEYS
from app.domain.participants import ParticipantKind
from app.domain.tasks import TaskField
from app.domain.tokens import TokenScope
from app.mcp.__main__ import journal_listener
from app.mcp.runtime import Runtime
from app.mcp.server import create_server
from app.services import case as case_service
from app.services import participants as participants_service
from app.services import tasks as tasks_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor
from conftest import MCP_BASE_URL, Connect, call, connect_mcp, refuse
from mcp import Client

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
    """Хвост, который уже есть, отдаётся сразу: ожидание начинается с чтения.

    Здесь же проверено, что прежняя форма вызова — `task` одной строкой — работает без
    изменений после того, как аргумент научился списку.
    """
    async with mcp_session(task_secret) as session:
        page = await call(session, "wait_journal", after=0, task=task.key)

    assert [item["type"] for item in page["items"]] == ["created"]
    assert page["items"][0]["task_key"] == task.key


async def test_the_wait_takes_several_task_keys_at_once(
    mcp_session: Connect,
    task_secret: str,
    task: Task,
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Сессия, ведущая несколько дел, называет их списком и ждёт по всем разом."""
    second = await tasks_service.create_task(
        db_session,
        actor=task_actor,
        project=project,
        title="Второе дело сессии",
        description="Нужно, чтобы список ключей было чем провалить",
    )
    third = await tasks_service.create_task(
        db_session,
        actor=task_actor,
        project=project,
        title="Задача, про которую не спрашивали",
        description="Записи этой задачи в выдачу попасть не должны",
    )
    keys = [task.key, second.key]
    outsider = third.key

    async with mcp_session(task_secret) as session:
        page = await call(session, "wait_journal", after=0, task=keys)

    assert {item["task_key"] for item in page["items"]} == set(keys)
    assert outsider not in {item["task_key"] for item in page["items"]}


async def test_more_task_keys_than_the_ceiling_are_refused(
    mcp_session: Connect, task_secret: str
) -> None:
    """Потолок ключей — отказ с числом, а не молча усечённый список."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "wait_journal",
            task=[f"TRK-{number}" for number in range(MAX_TASK_KEYS + 1)],
        )

    assert "journal_too_many_tasks" in failure
    assert str(MAX_TASK_KEYS) in failure


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
        project = Project(key=f"WAKE{suffix}", title="Пробуждение", **created_by_columns(TRACKER))
        session.add(project)
        await session.flush()
        task = Task(
            key=f"{project.key}-1",
            project=project,
            title="Задача для пробуждения",
            description="Есть",
            **created_by_columns(TRACKER),
        )
        session.add(task)
        await session.commit()
        secret = issued.secret
        ids = {
            "task": task.id,
            "project": project.id,
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
                text("DELETE FROM projects WHERE id = :project"), {"project": ids["project"]}
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


# --- Эпохи протокола: 2025-11-25 с рукопожатием и 2026-07-28 без сессий ----------------

#: Обе эпохи, которыми ходят клиенты. На второй нет `initialize`, `Mcp-Session-Id` и
#: возобновления потока: один запрос — один ответ, а оборванный запрос клиент повторяет
#: заново (TRK-440, TRK-435#6).
EPOCHS = ["legacy", "2026-07-28"]


@asynccontextmanager
async def connect_epoch(server: MCPServer, secret: str, mode: str) -> AsyncIterator[Any]:
    """Клиент SDK, закреплённый на эпохе: `legacy` — рукопожатие, иначе — версия без него.

    Возвращает объект с `call_tool`, одинаковый на обеих эпохах: у старой это
    `ClientSession`, у новой — `Client`. Результат обоих читается одной функцией
    `epoch_call`.
    """
    if mode == "legacy":
        async with connect_mcp(server, secret) as session:
            yield session
        return
    application = server.streamable_http_app()
    async with application.router.lifespan_context(application):
        http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(application),
            base_url=MCP_BASE_URL,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=60,
        )
        async with (
            http_client,
            Client(
                streamable_http_client(f"{MCP_BASE_URL}/mcp", http_client=http_client),
                mode=mode,
            ) as client,
        ):
            # Закрепление не молчит: клиент обязан говорить на выбранной эпохе.
            assert client.protocol_version == mode
            yield client


async def epoch_call(client: Any, tool: str, /, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def _append(
    sessions: async_sessionmaker[AsyncSession], task: Task, after: str, *, pause: float = 0.0
) -> int:
    """Подшивает запись другим соединением, с настоящим коммитом. Возвращает её `seq`."""
    await asyncio.sleep(pause)
    async with sessions() as writing:
        written = await writing.get(Task, task.id)
        assert written is not None
        entry = await case_service.record_section_changed(
            writing,
            written,
            actor=TRACKER_ACTOR,
            field=TaskField.GOAL,
            before="",
            after=after,
        )
        await writing.commit()
        return entry.seq


@pytest.mark.parametrize("mode", EPOCHS)
async def test_the_wait_returns_an_entry_filed_by_another_client_on_either_epoch(
    mode: str,
    committing_server: MCPServer,
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_world: tuple[str, Task],
    test_database_url: str,
) -> None:
    """Проверка 1 TRK-440: ждущий получает запись другого клиента и на эпохе без сессий.

    Запись подшивается другим соединением посреди ожидания, а слушатель поднят тем же
    менеджером, что у процесса: ответ обязан прийти раньше контрольного опроса, то есть
    разбудить его должно оповещение, а не опрос.
    """
    secret, task = committed_world
    poll = get_settings().journal_wait_poll_interval
    async with committing_sessions() as reading:
        start = await EntryRepository(reading).latest_seq()

    loop = asyncio.get_running_loop()
    async with journal_listener(asyncpg_dsn(test_database_url)):
        writer = asyncio.create_task(_append(committing_sessions, task, "разбудили", pause=0.5))
        began = loop.time()
        async with connect_epoch(committing_server, secret, mode) as client:
            page = await epoch_call(client, "wait_journal", after=start, timeout=30)
        elapsed = loop.time() - began
        expected = await writer

    assert [item["seq"] for item in page["items"]] == [expected]
    assert elapsed < poll, f"{mode}: ожидание длилось {elapsed:.1f}: разбудил опрос, не оповещение"


@pytest.mark.parametrize("mode", EPOCHS)
async def test_an_interrupted_wait_repeated_with_the_same_after_loses_and_doubles_nothing(
    mode: str,
    committing_server: MCPServer,
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_world: tuple[str, Task],
    test_database_url: str,
) -> None:
    """Проверка 1 TRK-440: оборванный и повторённый с тем же `after` вызов честен.

    На эпохе 2026-07-28 возобновления потока нет: оборвавшийся запрос клиент шлёт
    заново. Вызов ничего не хранит между запросами — позицию задаёт `after`, — поэтому
    повтор обязан отдать каждую запись ровно один раз, а оборванный ждущий — уйти и
    освободить свою регистрацию, не оставив живого ожидания на сервере.
    """
    secret, task = committed_world
    async with committing_sessions() as reading:
        start = await EntryRepository(reading).latest_seq()

    async with journal_listener(asyncpg_dsn(test_database_url)):
        # Первый вызов обрывается: клиент уходит, пока записей ещё нет.
        async with connect_epoch(committing_server, secret, mode) as client:
            waiting = asyncio.create_task(
                epoch_call(client, "wait_journal", after=start, timeout=30)
            )
            await asyncio.sleep(0.5)
            assert len(journal_wakeup._waiters) == 1, "ждущий не зарегистрировался"
            waiting.cancel()
            with suppress(asyncio.CancelledError):
                await waiting

        # Ушедший ждущий снимается со слушателя: иначе обрывы копили бы ожидания.
        for _ in range(50):
            if not journal_wakeup._waiters:
                break
            await asyncio.sleep(0.1)
        assert not journal_wakeup._waiters, f"{mode}: оборванное ожидание осталось на сервере"

        # Записи приходят, пока клиент повторяет вызов с прежним `after`.
        first = await _append(committing_sessions, task, "первая")
        second = await _append(committing_sessions, task, "вторая")
        async with connect_epoch(committing_server, secret, mode) as client:
            again = await epoch_call(client, "wait_journal", after=start, timeout=5)
            rest = await epoch_call(
                client, "wait_journal", after=again["items"][-1]["seq"], timeout=0
            )
            nothing = await epoch_call(client, "wait_journal", after=second, timeout=0)

    assert [item["seq"] for item in again["items"]] == [first, second]
    assert rest["items"] == []
    assert nothing["items"] == []
