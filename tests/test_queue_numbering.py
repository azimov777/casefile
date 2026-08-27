"""Нумерация задач в очереди при параллельной работе.

Единственный тест проекта, который идёт мимо общей фикстуры с откатом: проверять
гонку внутри одной транзакции бессмысленно — конкуренции там нет по определению.
Поэтому здесь свои сессии, честные коммиты и явная уборка за собой.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models.catalog import IssueType, Status
from app.db.models.queue import Queue
from app.db.repositories import QueueRepository
from app.domain.actors import SYSTEM_ACTOR_ID

#: Ключ очереди, которую тест создаёт и удаляет сам. Отдельный, чтобы не пересечься
#: с данными других тестов: они откатываются, а эта очередь живёт по-настоящему.
QUEUE_KEY = "CONC"
PARALLEL_REQUESTS = 16


@pytest.fixture
async def committed_queue(engine: AsyncEngine) -> uuid.UUID:
    """Очередь, зафиксированная в базе: её должны увидеть все параллельные соединения."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(delete(Queue).where(Queue.key == QUEUE_KEY))
        status = (
            await session.scalars(select(Status).where(Status.queue_id.is_(None)).limit(1))
        ).one()
        issue_type = (
            await session.scalars(select(IssueType).where(IssueType.queue_id.is_(None)).limit(1))
        ).one()
        queue = Queue(
            key=QUEUE_KEY,
            name="Concurrency",
            owner_id=SYSTEM_ACTOR_ID,
            default_status=status,
            default_issue_type=issue_type,
        )
        session.add(queue)
        await session.commit()
        queue_id = queue.id

    yield queue_id

    async with AsyncSession(engine) as session:
        await session.execute(delete(Queue).where(Queue.id == queue_id))
        await session.commit()


async def test_parallel_allocation_never_repeats_a_number(
    engine: AsyncEngine, committed_queue: uuid.UUID
) -> None:
    """Шестнадцать одновременных транзакций получают шестнадцать разных номеров подряд.

    Проверяется именно то, ради чего счётчик сделан отдельным `UPDATE ... RETURNING`:
    инкремент считает база поверх текущего значения строки, а не приложение поверх
    прочитанного. Наивное «прочитать и записать +1» здесь выдало бы одинаковые номера
    и разъехавшиеся ключи задач.
    """

    async def allocate() -> int:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            queue = await session.get(Queue, committed_queue)
            assert queue is not None
            number = await QueueRepository(session).allocate_issue_number(queue)
            await session.commit()
            return number

    numbers = await asyncio.gather(*(allocate() for _ in range(PARALLEL_REQUESTS)))

    assert sorted(numbers) == list(range(1, PARALLEL_REQUESTS + 1))


async def test_counter_survives_the_transactions_that_took_the_numbers(
    engine: AsyncEngine, committed_queue: uuid.UUID
) -> None:
    """После всех выдач счётчик равен последнему выданному номеру — без дыр и нахлёстов."""

    async def allocate() -> int:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            queue = await session.get(Queue, committed_queue)
            assert queue is not None
            number = await QueueRepository(session).allocate_issue_number(queue)
            await session.commit()
            return number

    await asyncio.gather(*(allocate() for _ in range(PARALLEL_REQUESTS)))

    async with AsyncSession(engine) as session:
        queue = await session.get(Queue, committed_queue)
        assert queue is not None
        assert queue.last_issue_number == PARALLEL_REQUESTS


async def test_rolled_back_transaction_loses_its_number(
    engine: AsyncEngine, committed_queue: uuid.UUID
) -> None:
    """Откат оставляет дыру в нумерации — и это осознанная цена, а не дефект.

    Убрать этот случай, не отказавшись от транзакционности, нельзя: номер выдан внутри
    транзакции, и её откат отменяет выдачу вместе со всем остальным. Тест существует,
    чтобы следующий читатель не «чинил» поведение, приняв его за ошибку.
    """
    async with AsyncSession(engine, expire_on_commit=False) as session:
        queue = await session.get(Queue, committed_queue)
        assert queue is not None
        assert await QueueRepository(session).allocate_issue_number(queue) == 1
        await session.rollback()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        queue = await session.get(Queue, committed_queue)
        assert queue is not None
        assert await QueueRepository(session).allocate_issue_number(queue) == 1
        await session.commit()
