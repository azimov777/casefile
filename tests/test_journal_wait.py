"""Долгое ожидание ленты: пробуждение оповещением и гонка сигнала со строкой.

Эти проверки нельзя поставить на общей фикстуре с откатом. Ожидание просыпается от
`NOTIFY`, а PostgreSQL рассылает оповещения **при фиксации** — в откатившейся
транзакции их не будет вовсе, и тест на ней проверял бы контрольный опрос вместо
оповещения. Поэтому здесь свои сессии поверх движка прогона, с настоящими коммитами, и
свой слушатель, поднятый на тестовой базе.

Уборка ручная и особенная — та же, что у гонки за номером записи: записи дела
неизменяемы на уровне схемы, и удалить закоммиченные тестом строки можно, только выключив
триггер на время уборки.

## Что именно проверяется в гонке

Две разные вещи, и ни одна не заменяет другую.

**Сигнал не раньше строки.** Оповещение уходит из транзакции подшивки; пока она открыта,
слушатель не получает ничего. Проверяется прямым слушателем канала: во время открытой
транзакции — тишина, после коммита — ровно одно оповещение с номером записи, и строка к
этому моменту видна.

**Хвост не теряет записей.** Сто записей из параллельных транзакций в разные задачи.
Именно «в разные»: записи в одну задачу сериализует блокировка её строки, и такая гонка
прошла бы и на сломанном коде. `seq` выдаётся при `INSERT`, а видимой строка становится
при `COMMIT`, и без очереди на подшивку (`app/db/locks.py`, `lock_changes`) два порядка
расходятся — читатель, дошедший до большего номера, меньший не увидит уже никогда.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models.author import created_by_columns
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.db.session import asyncpg_dsn
from app.db.wakeup import JOURNAL_CHANNEL, journal_wakeup
from app.domain.authors import TRACKER
from app.domain.journal import JournalFilter
from app.domain.tasks import TaskField
from app.services import case as case_service
from app.services import journal as journal_service
from app.services.auth import TRACKER_ACTOR

#: Столько записей подшивается одновременно в гонке.
CONCURRENCY = 100

#: По стольким задачам они разложены. Одной задачи мало: запись в одну задачу
#: сериализует блокировка её строки, и гонка не состоялась бы.
TASKS = 10

#: Сколько транзакций держится открытыми одновременно. Потолок нужен не логике, а
#: PostgreSQL: у сессий прогона пул отключён (`NullPool`), поэтому каждая открытая
#: транзакция — это отдельное соединение, а их у сервера сотня на всех.
IN_FLIGHT = 20

#: Сколько ждёт тест, которому ждать нечего. Меньше контрольного опроса — иначе он
#: проверял бы опрос, а не таймаут.
SHORT_WAIT = 1.0


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Сессии с настоящими коммитами: оповещение доходит только на фиксации."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def listening(test_database_url: str) -> AsyncIterator[None]:
    """Слушатель канала журнала, поднятый на **тестовой** базе.

    Слушатель установки подключился бы к основной базе и не услышал бы в тестах ничего:
    прогон идёт на отдельной. Адрес поэтому передаётся явно.
    """
    await journal_wakeup.start(asyncpg_dsn(test_database_url))
    assert journal_wakeup.is_listening, "без слушателя тест проверял бы контрольный опрос"
    yield
    await journal_wakeup.close()


@pytest.fixture
async def committed_tasks(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[list[uuid.UUID]]:
    """Очередь и десять задач, видимых другим соединениям, и уборка за собой."""
    async with committing_sessions() as session:
        queue = Queue(key="JOURNALRACE", title="Гонка ленты", **created_by_columns(TRACKER))
        session.add(queue)
        await session.flush()
        tasks = [
            Task(
                key=f"JOURNALRACE-{number}",
                queue=queue,
                title=f"Задача {number}",
                description="Есть",
                **created_by_columns(TRACKER),
            )
            for number in range(1, TASKS + 1)
        ]
        session.add_all(tasks)
        await session.commit()
        task_ids = [task.id for task in tasks]
        queue_id = queue.id

    try:
        yield task_ids
    finally:
        async with committing_sessions() as session:
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(
                text("DELETE FROM entries WHERE task_id = ANY(:ids)"), {"ids": task_ids}
            )
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            await session.execute(text("DELETE FROM tasks WHERE id = ANY(:ids)"), {"ids": task_ids})
            await session.execute(
                text("DELETE FROM queues WHERE id = :queue_id"), {"queue_id": queue_id}
            )
            await session.commit()


async def _latest_seq(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return await EntryRepository(session).latest_seq()


async def _append(
    sessions: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    marker: str,
) -> int:
    """Подшивает одну служебную запись в своей транзакции и возвращает её `seq`."""
    async with sessions() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        entry = await case_service.record_section_changed(
            session,
            task,
            actor=TRACKER_ACTOR,
            field=TaskField.GOAL,
            before="",
            after=marker,
        )
        await session.commit()
        return entry.seq


# --- Ожидание -------------------------------------------------------------------------


async def test_an_empty_tail_answers_when_the_wait_runs_out(
    committing_sessions: async_sessionmaker[AsyncSession],
    listening: None,
) -> None:
    """Обзорная проверка 2: ждать нечего — пустой список примерно через заданное время.

    Пустой ответ по таймауту не ошибка и не отдельный код: «ничего не случилось» и есть
    пустая коллекция.
    """
    start = await _latest_seq(committing_sessions)
    loop = asyncio.get_running_loop()
    began = loop.time()

    async with committing_sessions() as session:
        page = await journal_service.wait_journal(
            session,
            actor=TRACKER_ACTOR,
            journal_filter=JournalFilter(),
            after=start,
            wait=SHORT_WAIT,
        )
    elapsed = loop.time() - began

    assert page.items == []
    assert SHORT_WAIT * 0.8 <= elapsed < SHORT_WAIT + 2, elapsed


async def test_the_wait_returns_as_soon_as_the_entry_is_committed(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
    listening: None,
) -> None:
    """Обзорная проверка 2: запись подшита через секунду — ответ приходит через секунду.

    Порог сравнивается с контрольным опросом намеренно. Ответ, пришедший быстрее опроса,
    мог прийти только по оповещению: значит, проверено именно `LISTEN/NOTIFY`, а не
    сон до следующей проверки базы.
    """
    poll = get_settings().journal_wait_poll_interval
    assert poll > 2.0, (
        "контрольный опрос настроен чаще проверки — тест перестал отличать оповещение "
        f"от опроса (journal_wait_poll_interval={poll})"
    )
    start = await _latest_seq(committing_sessions)
    loop = asyncio.get_running_loop()

    async def write_later() -> int:
        await asyncio.sleep(0.5)
        return await _append(committing_sessions, committed_tasks[0], "разбудили")

    writer = asyncio.create_task(write_later())
    began = loop.time()
    async with committing_sessions() as session:
        page = await journal_service.wait_journal(
            session,
            actor=TRACKER_ACTOR,
            journal_filter=JournalFilter(),
            after=start,
            wait=30.0,
        )
    elapsed = loop.time() - began
    written = await writer

    assert [item.entry.seq for item in page.items] == [written]
    assert elapsed < 2.0, f"ожидание длилось {elapsed:.1f}: разбудил опрос, не оповещение"


# --- Гонка сигнала со строкой ---------------------------------------------------------


async def test_the_signal_never_arrives_before_the_row(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
    test_database_url: str,
) -> None:
    """Обзорная проверка 6: оповещения нет, пока транзакция подшивки открыта.

    Слушатель здесь свой, а не хаб приложения: проверяется именно провод — то, что
    PostgreSQL придерживает `pg_notify` до фиксации. Хаб на этом же проводе и сидит.
    """
    received: list[str] = []
    connection = await asyncpg.connect(asyncpg_dsn(test_database_url))
    await connection.add_listener(
        JOURNAL_CHANNEL,
        lambda _connection, _pid, _channel, payload: received.append(payload),
    )
    try:
        async with committing_sessions() as session:
            task = await session.get(Task, committed_tasks[0])
            assert task is not None
            entry = await case_service.record_section_changed(
                session,
                task,
                actor=TRACKER_ACTOR,
                field=TaskField.GOAL,
                before="",
                after="сигнал не раньше строки",
            )
            seq = entry.seq
            # Запись уже вставлена и номер выдан, но транзакция открыта: снаружи строки
            # ещё нет, и оповещения быть не должно.
            await asyncio.sleep(0.5)
            assert received == [], "сигнал ушёл раньше, чем строка стала видимой"
            assert not await _row_is_visible(committing_sessions, seq)
            await session.commit()

        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.05)

        assert received == [str(seq)]
        assert await _row_is_visible(committing_sessions, seq)
    finally:
        await connection.close()


async def _row_is_visible(sessions: async_sessionmaker[AsyncSession], seq: int) -> bool:
    """Видна ли строка другому соединению. Своей транзакции у проверки нет намеренно."""
    async with sessions() as session:
        result = await session.execute(text("SELECT 1 FROM entries WHERE seq = :seq"), {"seq": seq})
        return result.scalar() is not None


async def test_a_hundred_parallel_entries_reach_the_reader_without_losses(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
    listening: None,
) -> None:
    """Обзорная проверка 6: сто записей из параллельных транзакций доходят все и по разу.

    Читатель идёт ровно так, как пойдёт назначатель: ждёт хвост, двигает курсор на
    последний полученный номер, ждёт снова. Потерянная запись означала бы назначателя,
    который не узнал о закрытии задачи, — и разобрать это по логам было бы нечем.

    Порядок, в котором транзакции перемежаются, тест не задаёт: с очередью на подшивку
    результат от него не зависит вовсе, а сломанную реализацию сотня записей при двадцати
    одновременных транзакциях ловит с запасом.
    """
    start = await _latest_seq(committing_sessions)
    in_flight = asyncio.Semaphore(IN_FLIGHT)

    async def append(position: int) -> int:
        async with in_flight:
            return await _append(
                committing_sessions, committed_tasks[position % TASKS], str(position)
            )

    async def read_until(expected: int) -> list[int]:
        seen: list[int] = []
        after = start
        async with committing_sessions() as session:
            while len(seen) < expected:
                page = await journal_service.wait_journal(
                    session,
                    actor=TRACKER_ACTOR,
                    journal_filter=JournalFilter(),
                    after=after,
                    wait=10.0,
                    limit=200,
                )
                if not page.items:
                    # Ожидание истекло на пустом хвосте: дальше ждать нечего, и молча
                    # крутиться дальше значило бы превратить провал в зависание.
                    break
                for item in page.items:
                    seen.append(item.entry.seq)
                    after = item.entry.seq
        return seen

    reader = asyncio.create_task(read_until(CONCURRENCY))
    written = await asyncio.gather(*(append(position) for position in range(CONCURRENCY)))
    seen = await asyncio.wait_for(reader, timeout=60)

    assert len(written) == CONCURRENCY
    assert seen == sorted(written), (
        f"хвост ленты потерял, задвоил или переставил записи: получено {len(seen)} из {CONCURRENCY}"
    )
    assert seen == sorted(seen), "курсор ленты обязан двигаться только вперёд"
