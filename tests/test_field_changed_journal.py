"""Правка обвязки доходит до ленты: запись `field_changed` и её путь до потребителя.

Проверяется не «запись подшилась», а то, ради чего она подшивается: изменение,
не оставившее записи, не существует для внешнего мира (`CONCEPT.md`, 4.1), и открытый
экран молча показывал бы устаревшее значение.

Часть проверок требует настоящих коммитов — гонка, обрыв и перезапуск на откатываемой
фикстуре проверяли бы не то. Для них здесь свои сессии поверх движка прогона и ручная
уборка: записи дела неизменяемы на уровне триггера.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models.author import created_by_columns
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.authors import TRACKER
from app.domain.case import EntryType
from app.domain.tasks import TaskPriority, TaskStatus
from app.services import tasks as tasks_service
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.tasks import TaskChanges

JOURNAL = "/api/v1/journal"


async def tail(client: AsyncClient, after: int) -> list[dict]:
    """Хвост ленты после названного номера — так её читает интерфейс."""
    response = await client.get(JOURNAL, params={"after": after, "limit": 200})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def latest(session: AsyncSession) -> int:
    return await EntryRepository(session).latest_seq()


async def opened(session: AsyncSession, task: Task, actor: Actor) -> Task:
    """Задача в `open`: обвязка правится в любом незакрытом статусе."""
    await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.OPEN)
    return task


# --- Каждая правка оставляет ровно одно событие ---------------------------------------


async def test_a_change_of_the_trim_reaches_the_journal_once(
    db_session: AsyncSession,
    auth_client: AsyncClient,
    task_actor: Actor,
    task: Task,
) -> None:
    """Смена приоритета даёт одно событие с ключом и полем.

    Параметризации здесь больше нет: обвязка после снятия меток состоит из одного поля.
    Второй параметр вернётся вместе со вторым полем обвязки — и тогда же проверит, что
    новое поле не осталось немым в ленте.
    """
    await opened(db_session, task, task_actor)
    start = await latest(db_session)

    await tasks_service.update_task(
        db_session,
        task,
        actor=task_actor,
        changes=TaskChanges(priority=TaskPriority.CRITICAL),
    )

    events = await tail(auth_client, start)
    assert len(events) == 1, "одно изменение — одно событие"
    event = events[0]
    assert event["type"] == EntryType.FIELD_CHANGED.value
    assert event["task_key"] == task.key, "потребителю нужен ключ задачи, не только номер"
    assert event["payload"]["field"] == "priority"
    assert event["payload"]["after"] == "critical"


async def test_a_mixed_change_gives_both_facts_in_order_and_once(
    db_session: AsyncSession,
    auth_client: AsyncClient,
    task_actor: Actor,
    task: Task,
) -> None:
    """Один вызов меняет и подшиваемое поле, и прежде немое — приходят оба, по разу.

    Исполнитель подшивался в дело и раньше, приоритет не подшивался вовсе. Именно на
    таком вызове старое поведение теряло половину факта: экран узнавал о смене
    исполнителя и не узнавал о смене приоритета.
    """
    await opened(db_session, task, task_actor)
    start = await latest(db_session)

    await tasks_service.update_task(
        db_session,
        task,
        actor=task_actor,
        changes=TaskChanges(assignee="release_bot", priority=TaskPriority.HIGH),
    )

    events = await tail(auth_client, start)
    assert [event["type"] for event in events] == [
        EntryType.ASSIGNEE_CHANGED.value,
        EntryType.FIELD_CHANGED.value,
    ], "порядок событий — порядок полей в изменении"
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)
    assert len({event["no"] for event in events}) == 2, "двух записей про один факт не бывает"


async def test_a_change_that_changes_nothing_leaves_no_event(
    db_session: AsyncSession,
    auth_client: AsyncClient,
    task_actor: Actor,
    task: Task,
) -> None:
    """Правка теми же значениями события не порождает: менять нечего — говорить не о чем."""
    await opened(db_session, task, task_actor)
    await tasks_service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(priority=TaskPriority.HIGH)
    )
    start = await latest(db_session)

    await tasks_service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(priority=TaskPriority.HIGH)
    )

    assert await tail(auth_client, start) == []


# --- Откат уносит событие -------------------------------------------------------------


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Сессии с настоящими коммитами: откат, гонку и перезапуск иначе не проверить."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def committed_tasks(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[list[uuid.UUID]]:
    """Очередь и три задачи, видимые другим соединениям, и уборка за собой."""
    async with committing_sessions() as session:
        queue = Queue(key="TRIMRACE", title="Гонка обвязки", **created_by_columns(TRACKER))
        session.add(queue)
        await session.flush()
        tasks = [
            Task(
                key=f"TRIMRACE-{number}",
                queue=queue,
                title=f"Задача {number}",
                description="Есть",
                status=TaskStatus.OPEN,
                **created_by_columns(TRACKER),
            )
            for number in range(1, 4)
        ]
        session.add_all(tasks)
        await session.commit()
        task_ids = [item.id for item in tasks]
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


async def _change_priority(
    sessions: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    priority: TaskPriority,
    *,
    commit: bool = True,
) -> int | None:
    """Меняет приоритет в своей транзакции. Без коммита — откатывает."""
    async with sessions() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        await tasks_service.update_task(
            session, task, actor=TRACKER_ACTOR, changes=TaskChanges(priority=priority)
        )
        if not commit:
            await session.rollback()
            return None
        await session.commit()
    async with sessions() as session:
        return await latest(session)


async def _types_after(sessions: async_sessionmaker[AsyncSession], after: int) -> list[str]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT type FROM entries WHERE seq > :after ORDER BY seq"), {"after": after}
        )
        return [row[0] for row in rows]


async def test_a_rolled_back_change_reaches_nobody(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
) -> None:
    """Транзакция откачена — события нет ни при каком порядке чтения.

    Событие и изменение живут в одной транзакции: событие о несостоявшемся изменении
    хуже, чем отсутствие события.
    """
    async with committing_sessions() as session:
        start = await latest(session)

    await _change_priority(committing_sessions, committed_tasks[0], TaskPriority.HIGH, commit=False)

    assert await _types_after(committing_sessions, start) == []

    async with committing_sessions() as session:
        task = await session.get(Task, committed_tasks[0])
        assert task is not None
        assert task.priority is TaskPriority.NORMAL, "откат унёс и само изменение"


async def test_parallel_changes_of_different_tasks_leave_no_gaps(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
) -> None:
    """Три одновременных правки разных задач дают три события без дыр и повторов.

    Именно разных: правки одной задачи сериализует очередь изменений, и такая гонка
    прошла бы и на сломанном коде.
    """
    async with committing_sessions() as session:
        start = await latest(session)

    await asyncio.gather(
        *(
            _change_priority(committing_sessions, task_id, TaskPriority.CRITICAL)
            for task_id in committed_tasks
        )
    )

    async with committing_sessions() as session:
        rows = await session.execute(
            text("SELECT seq, type FROM entries WHERE seq > :after ORDER BY seq"), {"after": start}
        )
        found = rows.all()

    assert [row[1] for row in found] == [EntryType.FIELD_CHANGED.value] * len(committed_tasks)
    seqs = [row[0] for row in found]
    assert seqs == sorted(seqs), "порядок чтения — порядок номеров"
    assert len(set(seqs)) == len(seqs), "повторов в курсоре нет"


async def test_a_consumer_that_dropped_off_gets_everything_missed_once(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
) -> None:
    """Потребитель вернулся с курсором — получил пропущенное ровно один раз и по порядку."""
    async with committing_sessions() as session:
        start = await latest(session)

    # Потребитель прочитал первое событие и отвалился.
    await _change_priority(committing_sessions, committed_tasks[0], TaskPriority.HIGH)
    seen = await _types_after(committing_sessions, start)
    assert seen == [EntryType.FIELD_CHANGED.value]
    async with committing_sessions() as session:
        cursor = await latest(session)

    # Пока его не было, случились ещё две правки.
    await _change_priority(committing_sessions, committed_tasks[1], TaskPriority.LOW)
    await _change_priority(committing_sessions, committed_tasks[2], TaskPriority.CRITICAL)

    missed = await _types_after(committing_sessions, cursor)
    assert missed == [EntryType.FIELD_CHANGED.value] * 2, "ровно пропущенное, по разу"


async def test_the_event_survives_a_restart(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_tasks: list[uuid.UUID],
    test_database_url: str,
) -> None:
    """Событие пережило перезапуск: оно строка в базе, а не рассылка в памяти.

    Перезапуск изображается новым движком — своим пулом соединений, то есть взглядом
    другого процесса. Это и есть та разница, ради которой выбран путь без второго
    хранилища: уведомление, ушедшее в память, здесь не нашлось бы.
    """
    async with committing_sessions() as session:
        start = await latest(session)

    await _change_priority(committing_sessions, committed_tasks[0], TaskPriority.CRITICAL)

    fresh = create_async_engine(test_database_url)
    try:
        async with fresh.connect() as connection:
            rows = await connection.execute(
                text("SELECT type, payload FROM entries WHERE seq > :after ORDER BY seq"),
                {"after": start},
            )
            found = rows.all()
    finally:
        await fresh.dispose()

    assert [row[0] for row in found] == [EntryType.FIELD_CHANGED.value]
    assert found[0][1]["after"] == "critical"
