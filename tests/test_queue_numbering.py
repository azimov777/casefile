"""Гонка за номером задачи: пятьдесят одновременных запросов, пятьдесят разных номеров.

Проверку нельзя поставить на общей фикстуре `db_session`: она живёт внутри одной
транзакции теста, а конфликт за строку виден только **между** транзакциями. Тест,
написанный на общей сессии, был бы зелёным и на сломанном коде — он проверял бы
последовательный вызов под видом одновременного.

Поэтому здесь всё своё: движок прогона, собственная фабрика сессий с настоящими
коммитами, ручная уборка в `finally` (откат теста до закоммиченных строк не достаёт) и
`asyncio.Barrier` вместо надежды на планировщик задач — без него первый вызов успевает
закоммитить раньше, чем второй начнёт свой `UPDATE`.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.author import created_by_columns
from app.db.models.queue import Queue
from app.domain.authors import TRACKER
from app.services import queues as service
from app.services.auth import TRACKER_ACTOR

CONCURRENCY = 50


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий поверх движка прогона: каждая коммитит по-настоящему."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def committed_queue(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[uuid.UUID]:
    """Очередь, видимая другим соединениям, и уборка за собой.

    Уборка ручная: транзакция теста здесь ни при чём, а закоммиченная строка переживёт
    прогон и займёт ключ `RACE` у следующего.
    """
    async with committing_sessions() as session:
        queue = Queue(key="RACE", title="Гонка", **created_by_columns(TRACKER))
        session.add(queue)
        await session.commit()
        queue_id = queue.id

    try:
        yield queue_id
    finally:
        async with committing_sessions() as session:
            await session.execute(delete(Queue).where(Queue.id == queue_id))
            await session.commit()


async def test_parallel_allocations_never_hand_out_the_same_number(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_queue: uuid.UUID,
) -> None:
    """Обзорная проверка 5: номера разные, последовательные и без дыр."""
    barrier = asyncio.Barrier(CONCURRENCY)

    async def allocate() -> int:
        async with committing_sessions() as session:
            queue = await session.get(Queue, committed_queue)
            assert queue is not None
            await barrier.wait()
            number = await service.next_task_number(session, queue, actor=TRACKER_ACTOR)
            await session.commit()
            return number

    numbers = await asyncio.gather(*(allocate() for _ in range(CONCURRENCY)))

    assert sorted(numbers) == list(range(1, CONCURRENCY + 1))
