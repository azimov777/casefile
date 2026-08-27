"""Сценарии по справочникам: создание, области действия, защита от разрушительных правок.

Главное здесь — не создание записей, а отказы: статус с задачами нельзя удалить и
нельзя переопределить его категорию, запись очереди по умолчанию нельзя отключить.
Задачи в этих тестах настоящие: счётчики из `app/services/issue_usage.py` перестали
быть заглушками в задаче 05, и подменять их больше нечем и незачем — подмена скрыла бы
расхождение между запросом и тем, что он должен считать.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.queue import Queue
from app.domain.catalogs import (
    INITIAL_ISSUE_TYPES,
    INITIAL_RESOLUTIONS,
    INITIAL_STATUSES,
    CatalogKind,
    StatusCategory,
)
from app.domain.errors import (
    CatalogEntryUnavailableError,
    StatusCategoryLockedError,
    StatusInUseError,
    StatusKeyTakenError,
    StatusNotFoundError,
)
from app.services import catalogs as service
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[object]]


@pytest.fixture
def issues_in_status(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
) -> Callable[..., Awaitable[None]]:
    """Заводит несколько задач в указанном статусе.

    Настоящие задачи, а не подменённый счётчик: проверка «статус занят» обязана
    опираться на тот же запрос, которым пользуется рабочий код.
    """

    async def _create(count: int, status_ref: str = "open") -> None:
        status = await queues_service.resolve_catalog_ref(
            db_session, CatalogKind.STATUS, status_ref, initiator=owner
        )
        for _ in range(count):
            await make_issue(status=status)

    return _create


# --- Начальный набор -------------------------------------------------------------


async def test_migration_seeds_exactly_what_the_domain_declares(db_session: AsyncSession) -> None:
    """Списки в миграции и в домене обязаны совпадать.

    Миграция не имеет права импортировать код приложения, поэтому набор записан в ней
    литералами. Разъехаться двум спискам не даёт этот тест — другого сторожа нет.
    """
    statuses = (await db_session.scalars(select(Status).where(Status.queue_id.is_(None)))).all()
    types = (await db_session.scalars(select(IssueType).where(IssueType.queue_id.is_(None)))).all()
    resolutions = (
        await db_session.scalars(select(Resolution).where(Resolution.queue_id.is_(None)))
    ).all()

    assert {(s.key, s.name, s.category) for s in statuses} == {
        (entry.key, entry.name, entry.category) for entry in INITIAL_STATUSES
    }
    assert {(t.key, t.name, t.icon) for t in types} == {
        (entry.key, entry.name, entry.icon) for entry in INITIAL_ISSUE_TYPES
    }
    assert {(r.key, r.name) for r in resolutions} == {
        (entry.key, entry.name) for entry in INITIAL_RESOLUTIONS
    }


# --- Области действия ------------------------------------------------------------


async def test_same_key_lives_in_the_global_and_in_the_local_scope(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Глобальный `blocked` и локальный `TRK.blocked` — две разные записи."""
    global_entry = await service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="blocked",
        name="Заблокирован",
        category=StatusCategory.IN_PROGRESS,
    )
    local_entry = await service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="blocked",
        name="Ждёт смежников",
        queue=queue,
        category=StatusCategory.IN_PROGRESS,
    )

    assert global_entry.id != local_entry.id
    assert service.format_entry_ref(global_entry) == "blocked"
    assert service.format_entry_ref(local_entry) == "TRK.blocked"


async def test_duplicate_key_in_the_same_scope_is_rejected(
    db_session: AsyncSession, owner: Actor
) -> None:
    with pytest.raises(StatusKeyTakenError):
        await service.create_entry(
            db_session,
            CatalogKind.STATUS,
            initiator=owner,
            key="open",
            name="Ещё один открыт",
            category=StatusCategory.NEW,
        )


async def test_database_itself_forbids_two_global_entries_with_one_key(
    db_session: AsyncSession,
) -> None:
    """Проверка сценария — не единственная защита: ограничение стоит и в схеме.

    Ради этого случая у ограничения выставлен `NULLS NOT DISTINCT`. По умолчанию
    PostgreSQL считает NULL-ы различными, и пара `(queue_id, key)` пропустила бы
    сколько угодно глобальных статусов `open`.
    """
    db_session.add(Status(key="open", name="Дубль", category=StatusCategory.NEW))

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


async def test_local_entry_is_invisible_outside_its_queue(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Локальная запись адресуется только через свою очередь."""
    await service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="in_review",
        name="Ревью",
        queue=queue,
        category=StatusCategory.IN_PROGRESS,
    )

    with pytest.raises(StatusNotFoundError):
        await service.get_entry(db_session, CatalogKind.STATUS, key="in_review", queue=None)


async def test_status_requires_a_category(db_session: AsyncSession, owner: Actor) -> None:
    """Категория обязательна: без неё статус невидим для досок, прогресса и автоматики."""
    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.create_entry(
            db_session,
            CatalogKind.STATUS,
            initiator=owner,
            key="waiting",
            name="Ожидание",
        )

    assert error.value.details["field"] == "category"


# --- Изменение -------------------------------------------------------------------


async def test_rename_keeps_the_key(db_session: AsyncSession, owner: Actor) -> None:
    """Переименование не трогает ключ: на него ссылаются фильтры и воркфлоу."""
    entry = await service.get_entry(db_session, CatalogKind.STATUS, key="closed", queue=None)

    updated = await service.update_entry(
        db_session, entry, CatalogKind.STATUS, initiator=owner, name="Готово"
    )

    assert (updated.key, updated.name) == ("closed", "Готово")


async def test_category_changes_while_the_status_is_empty(
    db_session: AsyncSession, owner: Actor
) -> None:
    entry = await service.get_entry(db_session, CatalogKind.STATUS, key="in_progress", queue=None)

    updated = await service.update_entry(
        db_session,
        entry,
        CatalogKind.STATUS,
        initiator=owner,
        category=StatusCategory.DONE,
    )

    assert updated.category is StatusCategory.DONE


async def test_category_is_locked_while_issues_sit_in_the_status(
    db_session: AsyncSession, owner: Actor, issues_in_status: Callable[..., Awaitable[None]]
) -> None:
    """Смена категории задним числом переопределяет, какие задачи считаются закрытыми."""
    await issues_in_status(2, "in_progress")
    entry = await service.get_entry(db_session, CatalogKind.STATUS, key="in_progress", queue=None)

    with pytest.raises(StatusCategoryLockedError) as error:
        await service.update_entry(
            db_session,
            entry,
            CatalogKind.STATUS,
            initiator=owner,
            category=StatusCategory.DONE,
        )

    assert error.value.details["issues"] == 2
    assert entry.category is StatusCategory.IN_PROGRESS


async def test_field_of_another_kind_is_not_swallowed(
    db_session: AsyncSession, owner: Actor
) -> None:
    """Иконка у статуса — дефект вызывающего кода, а не поле, которое можно тихо забыть.

    Через HTTP такое не пройдёт: у каждого справочника своя схема. Но сценарий зовут
    ещё из MCP и из фоновых процессов, где схем нет, и молчаливый успех означал бы,
    что вызывающий уверен в применённом изменении, которого не было.
    """
    entry = await service.get_entry(db_session, CatalogKind.STATUS, key="open", queue=None)

    with pytest.raises(ValueError, match="icon belongs to issue types"):
        await service.update_entry(
            db_session, entry, CatalogKind.STATUS, initiator=owner, icon="fire"
        )


async def test_queue_default_status_cannot_be_deactivated(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Иначе очередь осталась бы с настройкой, которой нельзя воспользоваться."""
    with pytest.raises(StatusInUseError) as error:
        await service.update_entry(
            db_session,
            queue.default_status,
            CatalogKind.STATUS,
            initiator=owner,
            is_active=False,
        )

    assert error.value.details["queues"] == ["TRK"]


# --- Удаление --------------------------------------------------------------------


async def test_unused_status_is_deleted(db_session: AsyncSession, owner: Actor) -> None:
    entry = await service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="temporary",
        name="Временный",
        category=StatusCategory.NEW,
    )

    await service.delete_entry(db_session, entry, CatalogKind.STATUS, initiator=owner)

    with pytest.raises(StatusNotFoundError):
        await service.get_entry(db_session, CatalogKind.STATUS, key="temporary", queue=None)


async def test_status_with_issues_is_not_deleted(
    db_session: AsyncSession,
    owner: Actor,
    issues_in_status: Callable[..., Awaitable[None]],
) -> None:
    """Тихое удаление оставило бы задачи со ссылкой в никуда и сломало доски."""
    await issues_in_status(3)
    entry = await service.get_entry(db_session, CatalogKind.STATUS, key="open", queue=None)

    with pytest.raises(StatusInUseError) as error:
        await service.delete_entry(db_session, entry, CatalogKind.STATUS, initiator=owner)

    assert error.value.details == {
        "kind": "status",
        "ref": "open",
        "reason": "issues_exist",
        "issues": 3,
    }


async def test_queue_default_status_is_not_deleted(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    with pytest.raises(StatusInUseError) as error:
        await service.delete_entry(
            db_session, queue.default_status, CatalogKind.STATUS, initiator=owner
        )

    assert error.value.details["reason"] == "cannot_delete_queue_default"


async def test_deleting_an_issue_type_releases_it_from_queues(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Разрешение «тип можно заводить в очереди» без самого типа ничего не значит."""
    entry = await service.create_entry(
        db_session,
        CatalogKind.ISSUE_TYPE,
        initiator=owner,
        key="incident",
        name="Инцидент",
    )
    await queues_service.set_issue_types(
        db_session, queue, initiator=owner, refs=["task", "incident"]
    )

    await service.delete_entry(db_session, entry, CatalogKind.ISSUE_TYPE, initiator=owner)

    remaining = await queues_service.get_queue_config(db_session, queue, initiator=owner)
    assert [issue_type.key for issue_type in remaining.issue_types] == ["task"]


# --- Перенос задач ---------------------------------------------------------------


async def test_issues_are_moved_between_statuses(
    db_session: AsyncSession,
    owner: Actor,
    issues_in_status: Callable[..., Awaitable[None]],
) -> None:
    """Перенос — отдельный явный шаг, после которого удаление статуса проходит."""
    await issues_in_status(2, "in_progress")
    source = await service.get_entry(db_session, CatalogKind.STATUS, key="in_progress", queue=None)
    target = await service.get_entry(db_session, CatalogKind.STATUS, key="closed", queue=None)

    result = await service.move_issues(db_session, initiator=owner, source=source, target=target)

    assert result.moved == 2
    await service.delete_entry(db_session, source, CatalogKind.STATUS, initiator=owner)
    with pytest.raises(StatusNotFoundError):
        await service.get_entry(db_session, CatalogKind.STATUS, key="in_progress", queue=None)


async def test_moving_into_the_same_status_is_rejected(
    db_session: AsyncSession, owner: Actor
) -> None:
    entry = await service.get_entry(db_session, CatalogKind.STATUS, key="open", queue=None)

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.move_issues(db_session, initiator=owner, source=entry, target=entry)

    assert error.value.details["reason"] == "same_status"


async def test_global_source_cannot_move_into_a_local_target(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """В глобальном статусе стоят задачи разных очередей — локальный принял бы чужие."""
    source = await service.get_entry(db_session, CatalogKind.STATUS, key="open", queue=None)
    target = await service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="backlog",
        name="Бэклог",
        queue=queue,
        category=StatusCategory.NEW,
    )

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await service.move_issues(db_session, initiator=owner, source=source, target=target)

    assert error.value.details["reason"] == "target_must_be_global"


async def test_move_narrowed_to_one_queue_accepts_a_local_target(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    issues_in_status: Callable[..., Awaitable[None]],
) -> None:
    """С указанной очередью перенос затрагивает только её задачи — локальная цель законна."""
    await issues_in_status(2)
    source = await service.get_entry(db_session, CatalogKind.STATUS, key="open", queue=None)
    target = await service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="backlog",
        name="Бэклог",
        queue=queue,
        category=StatusCategory.NEW,
    )

    result = await service.move_issues(
        db_session, initiator=owner, source=source, target=target, queue=queue
    )

    assert result.moved == 2
    assert await service.count_usage(db_session, CatalogKind.STATUS, target.id) == 2
