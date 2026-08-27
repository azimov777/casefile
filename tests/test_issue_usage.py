"""Счётчики использования: на них держится защита справочников и реестра полей.

Раньше это были заглушки, а тесты справочников подменяли их функциями. Теперь запросы
настоящие, и проверять надо именно их — особенно те, что идут по `values JSONB`:
одиночное поле хранит скаляр, множественное — массив, и одного выражения на оба случая
не хватает.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind
from app.domain.fields import FieldOption, FieldValueType
from app.services import catalogs as catalogs_service
from app.services import fields as fields_service
from app.services import issue_usage
from app.services import issues as issues_service
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _status(session: AsyncSession, owner: Actor, ref: str) -> object:
    return await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, ref, initiator=owner
    )


# --- Справочники ------------------------------------------------------------------


async def test_issues_are_counted_by_status_type_and_queue(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    open_status = await _status(db_session, owner, "open")
    task_type = await queues_service.resolve_catalog_ref(
        db_session, CatalogKind.ISSUE_TYPE, "task", initiator=owner
    )
    await make_issue()
    await make_issue()

    assert await issue_usage.count_issues_with_status(db_session, open_status.id) == 2
    assert await issue_usage.count_issues_with_issue_type(db_session, task_type.id) == 2
    assert await issue_usage.count_issues_in_queue(db_session, queue.id) == 2


async def test_resolution_is_counted_only_where_it_is_set(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    done = await queues_service.resolve_catalog_ref(
        db_session, CatalogKind.RESOLUTION, "done", initiator=owner
    )
    await make_issue()
    await make_issue(resolution=done)

    assert await issue_usage.count_issues_with_resolution(db_session, done.id) == 1


async def test_issues_of_another_queue_are_not_counted(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    other = await queues_service.create_queue(
        db_session, initiator=owner, key="OPS", name="Эксплуатация"
    )
    await make_issue()
    await issues_service.create_issue(
        db_session, initiator=owner, queue=other, summary="Чужая задача"
    )

    assert await issue_usage.count_issues_in_queue(db_session, queue.id) == 1


# --- Перенос между статусами -------------------------------------------------------
#
# Сценарий принимает объекты статусов и очереди, а не идентификаторы: с задачи 06 он
# пишет запись в историю каждой перенесённой задачи и одно событие на весь перенос, и
# для того и другого нужны ссылки (`open`, `TRK.open`) и инициатор. Что именно перенос
# оставляет после себя, проверяет `tests/test_events_service.py`.


async def test_move_between_statuses_touches_only_the_source(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    source = await _status(db_session, owner, "open")
    target = await _status(db_session, owner, "closed")
    in_progress = await _status(db_session, owner, "in_progress")
    await make_issue()
    await make_issue()
    await make_issue(status=in_progress)

    moved = await issue_usage.move_issues_to_status(
        db_session, initiator=owner, source=source, target=target
    )

    assert moved == 2
    assert await issue_usage.count_issues_with_status(db_session, source.id) == 0
    assert await issue_usage.count_issues_with_status(db_session, target.id) == 2
    assert await issue_usage.count_issues_with_status(db_session, in_progress.id) == 1


async def test_move_narrowed_to_a_queue_leaves_other_queues_alone(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    source = await _status(db_session, owner, "open")
    target = await _status(db_session, owner, "closed")
    other = await queues_service.create_queue(
        db_session, initiator=owner, key="OPS", name="Эксплуатация"
    )
    await make_issue()
    await issues_service.create_issue(
        db_session, initiator=owner, queue=other, summary="Чужая задача"
    )

    moved = await issue_usage.move_issues_to_status(
        db_session, initiator=owner, source=source, target=target, queue=queue
    )

    assert moved == 1
    assert await issue_usage.count_issues_with_status(db_session, source.id) == 1


async def test_move_raises_the_version_of_the_moved_issues(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Иначе клиент со старой версией записал бы поверх нового статуса, ничего не заметив."""
    source = await _status(db_session, owner, "open")
    target = await _status(db_session, owner, "closed")
    issue = await make_issue()

    await issue_usage.move_issues_to_status(
        db_session, initiator=owner, source=source, target=target
    )

    await db_session.refresh(issue)
    assert issue.version == 2


# --- Значения кастомных полей -----------------------------------------------------


async def test_field_usage_is_counted_by_reference(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    """Ключ в `values` — ссылка на поле, поэтому глобальное и локальное не сливаются."""
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="severity",
        name="Серьёзность",
        value_type=FieldValueType.STRING,
    )
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="severity",
        name="Серьёзность очереди",
        value_type=FieldValueType.STRING,
        queue=queue,
    )
    await make_issue(values={"severity": "высокая"})
    await make_issue(values={"TRK.severity": "низкая"})

    assert await issue_usage.count_issues_with_field(db_session, "severity") == 1
    assert await issue_usage.count_issues_with_field(db_session, "TRK.severity") == 1
    assert await issue_usage.count_issues_with_field(db_session, "unknown") == 0


async def test_option_usage_is_found_in_a_scalar_and_in_an_array(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Одиночное поле хранит скаляр, множественное — массив: запрос обязан покрыть оба."""
    options = [
        FieldOption(key="minor", name="Мелкая"),
        FieldOption(key="critical", name="Критическая"),
    ]
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="severity",
        name="Серьёзность",
        value_type=FieldValueType.ENUM,
        options=options,
    )
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="areas",
        name="Области",
        value_type=FieldValueType.ENUM,
        is_multiple=True,
        options=[FieldOption(key="api", name="API"), FieldOption(key="db", name="БД")],
    )
    await make_issue(values={"severity": "critical", "areas": ["api", "db"]})

    assert await issue_usage.count_issues_with_field_value(db_session, "severity", "critical") == 1
    assert await issue_usage.count_issues_with_field_value(db_session, "severity", "minor") == 0
    assert await issue_usage.count_issues_with_field_value(db_session, "areas", "db") == 1
    assert await issue_usage.count_issues_with_field_value(db_session, "areas", "ui") == 0


# --- Ссылки на задачи -------------------------------------------------------------


async def test_missing_issue_keys_reports_only_the_absent_ones(
    db_session: AsyncSession, make_issue: MakeIssue
) -> None:
    """Единственная бывшая заглушка, чей ответ разрешал действие, а не запрещал."""
    await make_issue()

    missing = await issue_usage.missing_issue_keys(db_session, {"TRK-1", "TRK-2"})

    assert missing == {"TRK-2"}


async def test_missing_issue_keys_on_an_empty_set_asks_the_database_nothing(
    db_session: AsyncSession,
) -> None:
    assert await issue_usage.missing_issue_keys(db_session, set()) == set()


# --- Связка с защитой справочников -------------------------------------------------


async def test_catalog_protection_now_works_without_any_stubs(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Смысл всей замены: запрет опирается на настоящие задачи, а не на подменённый счётчик."""
    await make_issue()
    open_status = await _status(db_session, owner, "open")

    counted = await catalogs_service.count_usage(db_session, CatalogKind.STATUS, open_status.id)

    assert counted == 1
