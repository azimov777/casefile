"""Сценарии по очередям: создание, правка, чтение и выдача номеров."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.queue import Queue
from app.domain.errors import InvalidQueueKeyError, QueueKeyTakenError, QueueNotFoundError
from app.services import queues as service
from app.services.auth import Actor


async def test_creation_canonicalises_the_key_and_records_the_author(
    db_session: AsyncSession,
    main_actor: Actor,
) -> None:
    queue = await service.create_queue(
        db_session, actor=main_actor, key="ops", title="  Эксплуатация  ", description="Контекст"
    )

    assert queue.key == "OPS"
    assert queue.title == "Эксплуатация"
    assert queue.last_task_number == 0
    assert queue.created_by.signature == "owner"


async def test_a_key_differing_only_in_case_is_taken(
    db_session: AsyncSession,
    main_actor: Actor,
    queue: Queue,
) -> None:
    with pytest.raises(QueueKeyTakenError) as error:
        await service.create_queue(db_session, actor=main_actor, key="trk", title="Дубль")

    assert error.value.details["key"] == "TRK"


async def test_a_malformed_key_is_rejected(db_session: AsyncSession, main_actor: Actor) -> None:
    with pytest.raises(InvalidQueueKeyError):
        await service.create_queue(db_session, actor=main_actor, key="TRK-1", title="Дефис")


async def test_creation_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
) -> None:
    """Обзорная проверка 2 на уровне сценария."""
    with pytest.raises(PermissionDeniedError) as error:
        await service.create_queue(db_session, actor=task_actor, key="OPS", title="Эксплуатация")

    assert error.value.details["action"] == "queue.create"
    assert error.value.status_code == 403


async def test_reading_is_open_to_the_task_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Агент читает описание очереди — это общий контекст всех её задач."""
    read = await service.read_queue(db_session, "trk", actor=task_actor)
    page = await service.list_queues(db_session, actor=task_actor)

    assert read.id == queue.id
    assert [item.key for item in page.items] == ["TRK"]


async def test_an_unknown_key_is_not_found(db_session: AsyncSession, task_actor: Actor) -> None:
    with pytest.raises(QueueNotFoundError) as error:
        await service.read_queue(db_session, "GHOST", actor=task_actor)

    assert error.value.code == "queue_not_found"


async def test_update_changes_title_and_description_but_never_the_key(
    db_session: AsyncSession,
    main_actor: Actor,
    queue: Queue,
) -> None:
    updated = await service.update_queue(
        db_session, queue, actor=main_actor, description="Новый контекст"
    )

    assert updated.description == "Новый контекст"
    assert updated.title == "Трекер"
    assert updated.key == "TRK"


async def test_update_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    with pytest.raises(PermissionDeniedError):
        await service.update_queue(db_session, queue, actor=task_actor, title="Нельзя")


# --- Номера задач ------------------------------------------------------------------


async def test_numbers_are_handed_out_in_order(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Набор `task`: номер берут при создании задачи, то есть в рабочем цикле агента."""
    numbers = [
        await service.next_task_number(db_session, queue, actor=task_actor) for _ in range(3)
    ]

    assert numbers == [1, 2, 3]


async def test_the_loaded_queue_sees_its_own_increment(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Иначе ответ, собранный из объекта в том же запросе, показал бы счётчик до выдачи.

    Массовый `UPDATE` не синхронизирует загруженный объект сам — за этим следит
    `QueueRepository.allocate_task_number`.
    """
    await service.next_task_number(db_session, queue, actor=task_actor)

    assert queue.last_task_number == 1


async def test_numbers_are_independent_between_queues(
    db_session: AsyncSession,
    main_actor: Actor,
    task_actor: Actor,
    queue: Queue,
) -> None:
    other = await service.create_queue(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация"
    )

    first = await service.next_task_number(db_session, queue, actor=task_actor)
    second = await service.next_task_number(db_session, other, actor=task_actor)

    assert (first, second) == (1, 1)
