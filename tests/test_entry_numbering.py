"""Гонка за номером записи: двадцать одновременных записей в одну задачу, номера без дыр.

Как и гонка за номером задачи, проверка идёт на своих сессиях поверх движка прогона с
настоящими коммитами: конфликт виден только **между** транзакциями. `asyncio.Barrier`
выравнивает старт — без него первая запись успевает закоммититься раньше, чем вторая
начнёт выдачу.

Уборка ручная и особенная: записи дела неизменяемы на уровне схемы, и удалить строки,
закоммиченные тестом, можно, только выключив триггер на время уборки. Это единственное
законное место в проекте, где триггер выключается, и оно не должно множиться.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.author import created_by_columns
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.authors import TRACKER
from app.domain.tasks import TaskField
from app.services import case as case_service
from app.services.auth import TRACKER_ACTOR

CONCURRENCY = 20


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def committed_task(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[uuid.UUID]:
    """Задача, видимая другим соединениям, и уборка за собой вместе с проектом."""
    async with committing_sessions() as session:
        project = Project(key="RACEENTRY", title="Гонка", **created_by_columns(TRACKER))
        session.add(project)
        await session.flush()
        task = Task(
            key="RACEENTRY-1",
            project=project,
            title="Гонка за номером записи",
            description="Есть",
            **created_by_columns(TRACKER),
        )
        session.add(task)
        await session.commit()
        task_id, project_id = task.id, project.id

    try:
        yield task_id
    finally:
        async with committing_sessions() as session:
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(
                text("DELETE FROM entries WHERE task_id = :task_id"), {"task_id": task_id}
            )
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            await session.execute(
                text("DELETE FROM tasks WHERE id = :task_id"), {"task_id": task_id}
            )
            await session.execute(
                text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id}
            )
            await session.commit()


async def test_parallel_appends_never_hand_out_the_same_number(
    committing_sessions: async_sessionmaker[AsyncSession],
    committed_task: uuid.UUID,
) -> None:
    """Номера разные, последовательные и без дыр: блокировка строки задачи сериализует их."""
    barrier = asyncio.Barrier(CONCURRENCY)

    async def append(position: int) -> int:
        async with committing_sessions() as session:
            task = await session.get(Task, committed_task)
            assert task is not None
            await barrier.wait()
            entry = await case_service.record_section_changed(
                session,
                task,
                actor=TRACKER_ACTOR,
                field=TaskField.GOAL,
                before="",
                after=str(position),
            )
            await session.commit()
            return entry.no

    numbers = await asyncio.gather(*(append(position) for position in range(CONCURRENCY)))

    assert sorted(numbers) == list(range(1, CONCURRENCY + 1))
