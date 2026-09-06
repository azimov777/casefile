"""Сценарии задач: создание, правки по статусам, переходы, версия, служебные записи."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import (
    InvalidTaskKeyError,
    TaskClosedError,
    TaskFieldLockedError,
    TaskFieldsInvalidError,
    TaskNotFoundError,
    TaskSectionsIncompleteError,
    TaskVersionConflictError,
    TransitionNotAllowedError,
    TransitionReasonRequiredError,
)
from app.domain.tasks import TaskPriority, TaskStatus
from app.services import case as case_service
from app.services import queues as queues_service
from app.services import tasks as service
from app.services.auth import Actor
from app.services.tasks import TaskChanges


async def entries(session: AsyncSession, task: Task) -> list[Entry]:
    """Все записи задачи по порядку: страница заведомо больше любого теста."""
    page = await case_service.list_entries(session, task, actor=_reader(task), limit=200)
    return page.items


def _reader(task: Task) -> Actor:
    from app.domain.tokens import TokenScope

    return Actor(author=task.created_by, scope=TokenScope.TASK)


async def summary(session: AsyncSession, task: Task, actor: Actor) -> None:
    """Сводка ради перехода: без неё из `in_progress` не выйти (задача 23)."""
    await case_service.add_summary(
        session,
        task,
        actor=actor,
        done="Разобрался",
        remaining="Дописать",
        blockers="нет",
        next_step="Дописать проверку",
    )


async def move(
    session: AsyncSession,
    task: Task,
    actor: Actor,
    *statuses: TaskStatus,
    reason: str | None = None,
) -> Task:
    """Проводит задачу по цепочке, подшивая то, без чего переход не пройдёт.

    Сводка перед выходом из `in_progress` и вердикты перед `done` — правила перехода,
    а не предмет здешних тестов: без них до `done` не добраться вовсе. Сами правила
    проверяются в `tests/test_case_service.py`.
    """
    for status in statuses:
        if task.status is TaskStatus.IN_PROGRESS:
            await summary(session, task, actor)
            if status is TaskStatus.DONE:
                for check_no in range(1, len(task.checks) + 1):
                    await case_service.add_verdict(
                        session, task, actor=actor, check_no=check_no, outcome="passed"
                    )
        await service.transition_task(session, task, actor=actor, to=status, reason=reason)
    return task


# --- Создание -------------------------------------------------------------------------


async def test_a_new_task_is_born_in_backlog_with_a_created_entry(
    db_session: AsyncSession,
    task: Task,
) -> None:
    """Обзорная проверка 1: `backlog`, одна запись `created` с `no = 1` и автором из токена."""
    assert task.key == "TRK-1"
    assert task.status is TaskStatus.BACKLOG
    assert task.version == 1
    assert task.priority is TaskPriority.NORMAL
    assert task.created_by.signature == "owner"
    assert task.queue.key == "TRK"

    case = await entries(db_session, task)
    assert [(entry.no, entry.type) for entry in case] == [(1, EntryType.CREATED)]
    assert case[0].author.signature == "owner"
    assert case[0].author.kind.value == "human"
    assert case[0].payload == {}
    assert case[0].body == ""


async def test_a_rejected_creation_does_not_burn_a_number(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Номер выдаётся последним: откат по валидации не оставляет дыры в нумерации."""
    with pytest.raises(TaskFieldsInvalidError) as error:
        await service.create_task(
            db_session, actor=task_actor, queue=queue, title="  ", description="есть"
        )
    assert [item["field"] for item in error.value.details["fields"]] == ["title"]
    assert queue.last_task_number == 0

    created = await service.create_task(
        db_session, actor=task_actor, queue=queue, title="Первая", description="есть"
    )
    assert created.key == "TRK-1"


async def test_the_description_is_required(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    with pytest.raises(TaskFieldsInvalidError):
        await service.create_task(
            db_session, actor=task_actor, queue=queue, title="x", description=" "
        )


# --- Чтение ---------------------------------------------------------------------------


async def test_addressing_is_soft_by_case_and_strict_by_shape(
    db_session: AsyncSession, task: Task
) -> None:
    assert (await service.get_task(db_session, "trk-1")).id == task.id

    with pytest.raises(TaskNotFoundError) as missing:
        await service.get_task(db_session, "TRK-2")
    assert missing.value.details["key"] == "TRK-2"

    with pytest.raises(InvalidTaskKeyError):
        await service.get_task(db_session, "TRK-01")


async def test_the_package_carries_transitions_and_the_case_index(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    package = await service.read_task_package(db_session, task.key, actor=task_actor)

    assert package.task.id == task.id
    assert package.transitions == (TaskStatus.OPEN, TaskStatus.CANCELLED)
    assert [heading.no for heading in package.index] == [1]
    assert package.index[0].type is EntryType.CREATED
    assert package.index[0].author.signature == "owner"


# --- Переходы -------------------------------------------------------------------------


async def test_opening_requires_filled_sections(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 2: все незаполненные разделы перечислены сразу."""
    blank = await service.create_task(
        db_session, actor=task_actor, queue=queue, title="Пустая", description="Без разделов"
    )

    with pytest.raises(TaskSectionsIncompleteError) as error:
        await service.transition_task(db_session, blank, actor=task_actor, to=TaskStatus.OPEN)

    assert error.value.details["fields"] == ["goal", "context", "constraints", "output", "checks"]
    assert blank.status is TaskStatus.BACKLOG
    assert blank.version == 1


async def test_a_move_outside_the_table_names_the_allowed_targets(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 3."""
    await move(db_session, task, task_actor, TaskStatus.OPEN)

    with pytest.raises(TransitionNotAllowedError) as error:
        await service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.DONE)

    assert error.value.details["allowed"] == ["in_progress", "backlog", "cancelled"]


async def test_a_step_back_needs_a_reason_and_records_it(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 4: без причины `422`, с причиной проходит и причина в деле."""
    await move(db_session, task, task_actor, TaskStatus.OPEN, TaskStatus.IN_PROGRESS)
    # Сводка — отдельным шагом: без неё выход из `in_progress` упёрся бы в неё, а
    # проверяется здесь именно причина, и порядок проверок не должен это скрывать.
    await summary(db_session, task, task_actor)

    with pytest.raises(TransitionReasonRequiredError) as error:
        await service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.OPEN)
    assert error.value.code == "transition_reason_required"

    mutation = await service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason="Жду ответа"
    )

    assert mutation.changed
    assert task.status is TaskStatus.OPEN
    last = (await entries(db_session, task))[-1]
    assert last.type is EntryType.STATUS_CHANGED
    assert last.payload == {"from": "in_progress", "to": "open", "reason": "Жду ответа"}
    assert last.author.signature == "owner"


async def test_a_transition_is_accepted_as_a_string_too(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """MCP присылает статус строкой; неизвестная строка — замечание к полю, а не пятисотка."""
    await service.transition_task(db_session, task, actor=task_actor, to="open")
    assert task.status is TaskStatus.OPEN

    with pytest.raises(TaskFieldsInvalidError) as error:
        await service.transition_task(db_session, task, actor=task_actor, to="finished")
    assert error.value.details["fields"][0]["field"] == "status"


async def test_a_forward_move_records_no_reason_and_bumps_the_version(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    await move(db_session, task, task_actor, TaskStatus.OPEN)

    assert task.version == 2
    last = (await entries(db_session, task))[-1]
    assert last.payload == {"from": "backlog", "to": "open", "reason": None}
    assert last.title == "Status changed: backlog -> open"


async def test_a_closed_task_has_no_transitions(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    await move(db_session, task, task_actor, TaskStatus.CANCELLED, reason="Задача больше не нужна")

    with pytest.raises(TransitionNotAllowedError) as error:
        await service.transition_task(
            db_session, task, actor=task_actor, to=TaskStatus.BACKLOG, reason="Передумали"
        )
    assert error.value.details["allowed"] == []


# --- Правки полей ---------------------------------------------------------------------


async def test_sections_change_only_in_backlog_and_leave_a_trace(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 5: в `open` — `409`, в `backlog` — `section_changed` с «было / стало»."""
    mutation = await service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(goal="Новая цель")
    )
    assert [(change.field, change.before, change.after) for change in mutation.changes] == [
        ("goal", "Ключи не сгорают на отклонённых запросах", "Новая цель")
    ]
    assert task.version == 2
    last = (await entries(db_session, task))[-1]
    assert last.type is EntryType.SECTION_CHANGED
    assert last.payload == {
        "field": "goal",
        "before": "Ключи не сгорают на отклонённых запросах",
        "after": "Новая цель",
    }

    await move(db_session, task, task_actor, TaskStatus.OPEN)
    with pytest.raises(TaskFieldLockedError) as error:
        await service.update_task(
            db_session, task, actor=task_actor, changes=TaskChanges(goal="Ещё одна")
        )
    assert error.value.details["fields"] == ["goal"]
    assert error.value.details["editable_in"] == ["backlog"]


async def test_checks_are_a_section_and_change_as_a_whole(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    await service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(checks=["одна", "две"])
    )

    assert task.checks == ["одна", "две"]
    last = (await entries(db_session, task))[-1]
    assert last.payload["field"] == "checks"
    assert last.payload["after"] == ["одна", "две"]


async def test_the_assignee_changes_in_any_open_status_but_not_in_a_closed_one(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 6."""
    await move(db_session, task, task_actor, TaskStatus.OPEN, TaskStatus.IN_PROGRESS)

    await service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(assignee="release_bot")
    )
    assert task.assignee == "release_bot"
    last = (await entries(db_session, task))[-1]
    assert last.type is EntryType.ASSIGNEE_CHANGED
    assert last.payload == {"before": None, "after": "release_bot"}
    assert last.title == "Assignee changed: nobody -> release_bot"

    await move(db_session, task, task_actor, TaskStatus.DONE)
    with pytest.raises(TaskClosedError) as error:
        await service.update_task(
            db_session, task, actor=task_actor, changes=TaskChanges(assignee=None)
        )
    assert error.value.code == "task_closed"


async def test_tags_and_priority_leave_a_field_changed_entry_each(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Правка обвязки оставляет по записи на поле — иначе она не дошла бы до ленты.

    Раньше здесь стояло обратное: теги и приоритет версию поднимали, а записи не
    оставляли. Довод был верный — дело не про перекладывание меток, — но у него
    оказалась цена: лента журнала это лента записей дела, и изменение без записи
    не доходит до открытого экрана вовсе (`CONCEPT.md`, 4.1). Правило снято, а
    «дело не про метки» держится тем, что записи служебные: они сжимаются в ленте,
    отбираются по типу и не входят в `last_entry_at`.
    """
    await move(db_session, task, task_actor, TaskStatus.OPEN)
    before = len(await entries(db_session, task))

    mutation = await service.update_task(
        db_session,
        task,
        actor=task_actor,
        changes=TaskChanges(tags=["backend"], priority="high"),
    )

    assert {change.field for change in mutation.changes} == {"tags", "priority"}
    assert task.version == 3
    assert task.priority is TaskPriority.HIGH

    filed = await entries(db_session, task)
    assert len(filed) == before + 2, "по записи на каждое изменённое поле"
    added = filed[before:]
    assert {entry.type for entry in added} == {EntryType.FIELD_CHANGED}
    assert {entry.payload["field"] for entry in added} == {"tags", "priority"}


async def test_sending_the_current_values_changes_nothing(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Фактических изменений нет — версия не растёт и страница не подшивается."""
    before = len(await entries(db_session, task))

    mutation = await service.update_task(
        db_session,
        task,
        actor=task_actor,
        changes=TaskChanges(title=task.title, checks=list(task.checks), assignee=None),
    )

    assert not mutation.changed
    assert task.version == 1
    assert len(await entries(db_session, task)) == before


async def test_a_stale_version_is_a_conflict(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 7."""
    await service.update_task(db_session, task, actor=task_actor, changes=TaskChanges(goal="x"))
    assert task.version == 2

    with pytest.raises(TaskVersionConflictError) as error:
        await service.update_task(
            db_session,
            task,
            actor=task_actor,
            changes=TaskChanges(goal="y"),
            expected_version=1,
        )

    assert error.value.code == "version_conflict"
    assert error.value.details == {"key": "TRK-1", "expected": 1, "actual": 2}


async def test_a_task_scope_token_runs_the_whole_cycle(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Рабочий цикл не требует `main`: создание, правка и переходы открыты набору `task`."""
    await service.update_task(db_session, task, actor=task_actor, changes=TaskChanges(tags=["a"]))
    await move(db_session, task, task_actor, TaskStatus.OPEN, TaskStatus.IN_PROGRESS)

    assert task.status is TaskStatus.IN_PROGRESS


# --- Дело -----------------------------------------------------------------------------


async def test_seq_grows_across_the_tracker_and_no_inside_each_task(
    db_session: AsyncSession,
    main_actor: Actor,
    task_actor: Actor,
    task: Task,
) -> None:
    """Обзорная проверка 8: две очереди, записи чередуются."""
    other_queue = await queues_service.create_queue(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация"
    )
    other = await service.create_task(
        db_session, actor=task_actor, queue=other_queue, title="Дежурство", description="Есть"
    )
    await service.update_task(db_session, task, actor=task_actor, changes=TaskChanges(goal="a"))
    await service.update_task(db_session, other, actor=task_actor, changes=TaskChanges(goal="b"))
    await service.update_task(db_session, task, actor=task_actor, changes=TaskChanges(goal="c"))

    first = await entries(db_session, task)
    second = await entries(db_session, other)
    assert [entry.no for entry in first] == [1, 2, 3]
    assert [entry.no for entry in second] == [1, 2]
    seqs = sorted(entry.seq for entry in first + second)
    assert len(set(seqs)) == 5
    ordered = sorted(first + second, key=lambda entry: entry.seq)
    assert [(entry.no, entry.task_id == task.id) for entry in ordered] == [
        (1, True),
        (1, False),
        (2, True),
        (2, False),
        (3, True),
    ]


async def test_entries_are_read_in_pages_by_number(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    for goal in ("a", "b", "c", "d"):
        await service.update_task(
            db_session, task, actor=task_actor, changes=TaskChanges(goal=goal)
        )

    first = await case_service.list_entries(db_session, task, actor=task_actor, limit=2)
    second = await case_service.list_entries(
        db_session, task, actor=task_actor, limit=2, cursor=first.next_cursor
    )
    third = await case_service.list_entries(
        db_session, task, actor=task_actor, limit=2, cursor=second.next_cursor
    )

    assert [entry.no for entry in first.items] == [1, 2]
    assert [entry.no for entry in second.items] == [3, 4]
    assert [entry.no for entry in third.items] == [5]
    assert third.next_cursor is None


async def test_the_index_has_headings_only(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    await service.update_task(db_session, task, actor=task_actor, changes=TaskChanges(goal="x"))

    index = await case_service.case_index(db_session, task, actor=task_actor)

    assert [(heading.no, heading.type.value) for heading in index] == [
        (1, "created"),
        (2, "section_changed"),
    ]
    assert index[1].title == "Section changed: goal"
    assert not hasattr(index[1], "payload")


async def test_entries_cannot_be_changed_even_with_raw_sql(
    db_session: AsyncSession, task: Task
) -> None:
    """Неизменяемость закреплена в схеме: триггер отклоняет `UPDATE` и `DELETE`."""
    with pytest.raises(DBAPIError, match="entries are immutable"):
        await db_session.execute(
            text("UPDATE entries SET title = 'rewritten' WHERE task_id = :task_id"),
            {"task_id": task.id},
        )
