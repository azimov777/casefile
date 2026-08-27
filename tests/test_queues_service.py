"""Сценарии по очередям: конфигурация, значения по умолчанию, архивация, нумерация.

Очередь — центральная единица настройки, поэтому проверяется не только то, что она
создаётся, но и то, что её нельзя привести в нерабочее состояние: остаться без типов
задач, получить чужой локальный статус по умолчанию или потерять счётчик номеров.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.queue import Queue
from app.domain.actors import ActorType
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.errors import (
    CatalogEntryUnavailableError,
    InvalidQueueKeyError,
    QueueArchivedError,
    QueueKeyTakenError,
    QueueNotEmptyError,
    QueueNotFoundError,
)
from app.services import actors as actors_service
from app.services import catalogs as catalogs_service
from app.services import queues as service

MakeIssue = Callable[..., Awaitable[object]]


# --- Создание --------------------------------------------------------------------


async def test_new_queue_is_ready_to_accept_issues(queue: Queue) -> None:
    """Без указаний очередь комплектуется глобальными справочниками и работает сразу."""
    assert queue.key == "TRK"
    assert queue.default_issue_type.key == "task"
    assert queue.default_status.key == "open"
    assert queue.last_issue_number == 0
    assert not queue.is_archived


async def test_new_queue_allows_every_active_global_issue_type(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    config = await service.get_queue_config(db_session, queue, initiator=owner)

    assert [issue_type.key for issue_type in config.issue_types] == ["task", "bug", "epic"]


async def test_queue_key_is_normalised(db_session: AsyncSession, owner: Actor) -> None:
    created = await service.create_queue(
        db_session, initiator=owner, key="ops", name="Эксплуатация"
    )

    assert created.key == "OPS"


async def test_queue_key_is_unique(db_session: AsyncSession, owner: Actor, queue: Queue) -> None:
    with pytest.raises(QueueKeyTakenError):
        await service.create_queue(db_session, initiator=owner, key="TRK", name="Второй трекер")


async def test_invalid_queue_key_is_rejected(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(InvalidQueueKeyError):
        await service.create_queue(db_session, initiator=owner, key="TRK-2", name="Плохой ключ")


async def test_queue_can_be_created_with_a_narrowed_set_of_types(
    db_session: AsyncSession, owner: Actor
) -> None:
    created = await service.create_queue(
        db_session,
        initiator=owner,
        key="OPS",
        name="Эксплуатация",
        issue_type_refs=["bug"],
        default_issue_type_ref="bug",
        default_status_ref="in_progress",
    )
    config = await service.get_queue_config(db_session, created, initiator=owner)

    assert [issue_type.key for issue_type in config.issue_types] == ["bug"]
    assert created.default_issue_type.key == "bug"
    assert created.default_status.key == "in_progress"


async def test_default_type_outside_the_chosen_set_is_rejected(
    db_session: AsyncSession, owner: Actor
) -> None:
    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.create_queue(
            db_session,
            initiator=owner,
            key="OPS",
            name="Эксплуатация",
            issue_type_refs=["bug"],
            default_issue_type_ref="epic",
        )

    assert error.value.details["reason"] == "not_available_for_new_queue"


async def test_new_queue_cannot_borrow_a_local_entry(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Ссылка с чужим префиксом отвергается, а не толкуется как глобальный ключ."""
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.ISSUE_TYPE,
        initiator=owner,
        key="incident",
        name="Инцидент",
        queue=queue,
    )

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.create_queue(
            db_session,
            initiator=owner,
            key="OPS",
            name="Эксплуатация",
            issue_type_refs=["TRK.incident"],
        )

    assert error.value.details["reason"] == "must_be_global"


async def test_owner_defaults_to_the_initiator(queue: Queue, owner: Actor) -> None:
    assert queue.owner_id == owner.id


async def test_inactive_actor_cannot_own_a_queue(
    db_session: AsyncSession, owner: Actor, system_actor: Actor
) -> None:
    bot = await actors_service.create_actor(
        db_session,
        initiator=owner,
        actor_type=ActorType.AGENT,
        key="retired_bot",
        display_name="Retired",
    )
    await actors_service.update_actor(db_session, bot, initiator=owner, is_active=False)

    with pytest.raises(Exception, match="inactive"):
        await service.create_queue(
            db_session, initiator=owner, key="OPS", name="Эксплуатация", owner=bot
        )


# --- Изменение -------------------------------------------------------------------


async def test_update_changes_only_what_is_passed(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    updated = await service.update_queue(db_session, queue, initiator=owner, name="Разработка")

    assert updated.name == "Разработка"
    assert updated.description == "Задачи по разработке трекера"


async def test_local_status_can_become_the_queue_default(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Ссылка на локальную запись собирается из самой записи — очередь её признаёт своей."""
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="backlog",
        name="Бэклог",
        queue=queue,
        category=StatusCategory.NEW,
    )

    updated = await service.update_queue(
        db_session, queue, initiator=owner, default_status_ref="TRK.backlog"
    )

    assert catalogs_service.format_entry_ref(updated.default_status) == "TRK.backlog"


async def test_queue_cannot_take_a_status_of_another_queue(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    other = await service.create_queue(db_session, initiator=owner, key="OPS", name="Эксплуатация")
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="on_duty",
        name="Дежурство",
        queue=other,
        category=StatusCategory.IN_PROGRESS,
    )

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.update_queue(
            db_session, queue, initiator=owner, default_status_ref="OPS.on_duty"
        )

    assert error.value.details["reason"] == "belongs_to_another_queue"


async def test_default_issue_type_must_be_allowed_in_the_queue(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await service.set_issue_types(db_session, queue, initiator=owner, refs=["task"])

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.update_queue(db_session, queue, initiator=owner, default_issue_type_ref="bug")

    assert error.value.details["reason"] == "not_allowed_in_queue"


async def test_issue_types_are_replaced_as_a_whole(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    result = await service.set_issue_types(db_session, queue, initiator=owner, refs=["task", "bug"])

    assert [issue_type.key for issue_type in result] == ["task", "bug"]


async def test_default_issue_type_cannot_be_dropped_from_the_set(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.set_issue_types(db_session, queue, initiator=owner, refs=["bug"])

    assert error.value.details["reason"] == "default_issue_type_must_stay"


async def test_queue_cannot_be_left_without_issue_types(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    with pytest.raises(CatalogEntryUnavailableError):
        await service.set_issue_types(db_session, queue, initiator=owner, refs=[])


# --- Конфигурация ----------------------------------------------------------------


async def test_config_gathers_the_whole_process_in_one_call(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="in_review",
        name="Ревью",
        queue=queue,
        category=StatusCategory.IN_PROGRESS,
    )

    config = await service.get_queue_config(db_session, queue, initiator=owner)

    assert config.queue is queue
    assert [status.key for status in config.statuses] == [
        "open",
        "in_progress",
        "closed",
        "in_review",
    ]
    assert [resolution.key for resolution in config.resolutions] == [
        "done",
        "rejected",
        "duplicate",
    ]


async def test_config_hides_disabled_entries(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Конфигурация отвечает на вопрос «чем можно пользоваться сейчас»."""
    entry = await catalogs_service.get_entry(
        db_session, CatalogKind.RESOLUTION, key="duplicate", queue=None
    )
    await catalogs_service.update_entry(
        db_session, entry, CatalogKind.RESOLUTION, initiator=owner, is_active=False
    )

    config = await service.get_queue_config(db_session, queue, initiator=owner)

    assert "duplicate" not in [resolution.key for resolution in config.resolutions]


async def test_config_of_one_queue_hides_another_queues_local_entries(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    other = await service.create_queue(db_session, initiator=owner, key="OPS", name="Эксплуатация")
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="on_duty",
        name="Дежурство",
        queue=other,
        category=StatusCategory.IN_PROGRESS,
    )

    config = await service.get_queue_config(db_session, queue, initiator=owner)

    assert "on_duty" not in [status.key for status in config.statuses]


# --- Архивация и удаление --------------------------------------------------------


async def test_archiving_is_idempotent(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    archived = await service.archive_queue(db_session, queue, initiator=owner)
    archived_at = archived.archived_at
    again = await service.archive_queue(db_session, queue, initiator=owner)

    assert again.is_archived
    assert again.archived_at == archived_at


async def test_unarchiving_returns_the_queue_to_work(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await service.archive_queue(db_session, queue, initiator=owner)

    restored = await service.unarchive_queue(db_session, queue, initiator=owner)

    assert not restored.is_archived
    assert restored.archived_at is None


async def test_archived_queue_hands_out_no_issue_numbers(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Единственная точка выдачи номеров — она же единственный нужный запрет."""
    await service.archive_queue(db_session, queue, initiator=owner)

    with pytest.raises(QueueArchivedError):
        await service.allocate_issue_number(db_session, queue)


async def test_archived_queue_still_accepts_configuration_changes(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Иначе привести очередь в порядок перед возвратом из архива было бы нечем."""
    await service.archive_queue(db_session, queue, initiator=owner)

    updated = await service.update_queue(db_session, queue, initiator=owner, name="Архивная")

    assert updated.name == "Архивная"


async def test_empty_queue_is_deleted_with_its_local_catalogs(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="backlog",
        name="Бэклог",
        queue=queue,
        category=StatusCategory.NEW,
    )

    await service.delete_queue(db_session, queue, initiator=owner)

    with pytest.raises(QueueNotFoundError):
        await service.get_queue_by_key(db_session, "TRK")


async def test_queue_with_issues_is_not_deleted(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
) -> None:
    """Вместо удаления — архивация: ключи задач переживают саму очередь."""
    await make_issue()
    await make_issue()

    with pytest.raises(QueueNotEmptyError) as error:
        await service.delete_queue(db_session, queue, initiator=owner)

    assert error.value.details["issues"] == 2
    assert error.value.details["hint"] == "archive the queue instead"


# --- Нумерация -------------------------------------------------------------------


async def test_numbers_are_handed_out_in_order(db_session: AsyncSession, queue: Queue) -> None:
    numbers = [await service.allocate_issue_number(db_session, queue) for _ in range(3)]

    assert numbers == [1, 2, 3]
    assert queue.last_issue_number == 3


async def test_issue_key_uses_the_queue_key(db_session: AsyncSession, queue: Queue) -> None:
    assert await service.allocate_issue_key(db_session, queue) == "TRK-1"
