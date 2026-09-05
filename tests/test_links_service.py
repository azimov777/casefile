"""Сценарии связей: постановка и снятие, записи в обоих делах, циклы, блокировка работы."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import (
    LinkCycleError,
    LinkExistsError,
    LinkNotFoundError,
    LinkSelfError,
    TaskBlockedError,
    TaskClosedError,
    TaskHasUnclosedChildrenError,
)
from app.domain.links import LinkKind
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import links as service
from app.services import tasks as tasks_service
from app.services.auth import Actor


async def make(session: AsyncSession, actor: Actor, queue: Queue, title: str) -> Task:
    """Задача в `backlog` с заполненными разделами: готова идти по цепочке статусов."""
    return await tasks_service.create_task(
        session,
        actor=actor,
        queue=queue,
        title=title,
        description="описание",
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
    )


async def move(
    session: AsyncSession,
    task: Task,
    actor: Actor,
    *statuses: TaskStatus,
    reason: str | None = "причина",
) -> Task:
    """Проводит задачу по цепочке, подшивая то, без чего переход не пройдёт."""
    for status in statuses:
        if task.status is TaskStatus.IN_PROGRESS:
            await summary(session, task, actor)
        if task.status is TaskStatus.IN_PROGRESS and status is TaskStatus.DONE:
            for check_no in range(1, len(task.checks) + 1):
                await case_service.add_verdict(
                    session, task, actor=actor, check_no=check_no, outcome="passed"
                )
        await tasks_service.transition_task(session, task, actor=actor, to=status, reason=reason)
    return task


async def summary(session: AsyncSession, task: Task, actor: Actor) -> None:
    """Сводка ради перехода: без неё из `in_progress` не выйти (задача 23)."""
    await case_service.add_summary(
        session,
        task,
        actor=actor,
        done="сделано",
        remaining="осталось",
        blockers="нет",
        next_step="дальше",
    )


async def entries(session: AsyncSession, task: Task, actor: Actor) -> list[Entry]:
    page = await case_service.list_entries(session, task, actor=actor, limit=200)
    return page.items


async def link_entries(session: AsyncSession, task: Task, actor: Actor) -> list[tuple[str, dict]]:
    """Записи о связях этой задачи: тип и нагрузка, в порядке подшивки."""
    return [
        (entry.type.value, entry.payload)
        for entry in await entries(session, task, actor)
        if entry.type in {EntryType.LINK_ADDED, EntryType.LINK_REMOVED}
    ]


# --- Одна строка, две стороны -----------------------------------------------------------


async def test_a_link_is_seen_from_both_sides_under_its_own_kind(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 5: `blocks` у одной, `blocked_by` у другой, `relates` — одинаково."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    third = await make(db_session, task_actor, queue, "третья")

    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)
    await service.add_link(db_session, first, third, actor=task_actor, kind=LinkKind.RELATES)

    seen_from_first = await service.list_links(db_session, first, actor=task_actor)
    seen_from_second = await service.list_links(db_session, second, actor=task_actor)
    seen_from_third = await service.list_links(db_session, third, actor=task_actor)

    # Множеством, а не списком: обе связи заведены одной транзакцией, `created_at` у них
    # общий (`now()` — время её начала), и порядок между ними задаёт идентификатор
    # (`docs/notes/db.md`). В жизни связи приходят разными запросами и идут по времени.
    assert {(link.kind, link.other.key) for link in seen_from_first} == {
        (LinkKind.BLOCKS, "TRK-2"),
        (LinkKind.RELATES, "TRK-3"),
    }
    assert [(link.kind, link.other.key) for link in seen_from_second] == [
        (LinkKind.BLOCKED_BY, "TRK-1")
    ]
    assert [(link.kind, link.other.key) for link in seen_from_third] == [
        (LinkKind.RELATES, "TRK-1")
    ]


async def test_the_other_side_carries_its_status(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 7, первая половина: статус задачи на другой стороне в связи есть."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await move(db_session, second, task_actor, TaskStatus.OPEN)

    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKED_BY)

    (link,) = await service.list_links(db_session, first, actor=task_actor)
    assert link.other.status is TaskStatus.OPEN
    assert link.author.signature == "owner"


async def test_the_same_link_from_the_other_side_is_a_duplicate(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Связь хранится один раз: «B blocked_by A» после «A blocks B» — повтор, а не вторая."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)

    with pytest.raises(LinkExistsError) as error:
        await service.add_link(
            db_session, second, first, actor=task_actor, kind=LinkKind.BLOCKED_BY
        )

    assert error.value.code == "link_exists"
    assert error.value.status_code == 409


async def test_a_symmetric_link_is_a_duplicate_from_either_side(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """У `relates` дубликат ловится только благодаря упорядочиванию пары по ключу."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await service.add_link(db_session, second, first, actor=task_actor, kind=LinkKind.RELATES)

    with pytest.raises(LinkExistsError):
        await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.RELATES)


async def test_a_link_can_be_removed_from_the_other_side(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)

    await service.remove_link(db_session, second, first, actor=task_actor, kind=LinkKind.BLOCKED_BY)

    assert await service.list_links(db_session, first, actor=task_actor) == []
    assert await service.list_links(db_session, second, actor=task_actor) == []


async def test_removing_a_link_that_is_not_there_is_a_miss(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")

    with pytest.raises(LinkNotFoundError) as error:
        await service.remove_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)

    assert error.value.status_code == 404


# --- Записи в делах обеих задач ---------------------------------------------------------


async def test_both_cases_get_the_link_entry_under_their_own_kind(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 4: `link_added` в обоих делах, вид — со стороны своей задачи."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")

    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)

    assert await link_entries(db_session, first, task_actor) == [
        ("link_added", {"kind": "blocks", "other": "TRK-2"})
    ]
    assert await link_entries(db_session, second, task_actor) == [
        ("link_added", {"kind": "blocked_by", "other": "TRK-1"})
    ]

    await service.remove_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)

    assert await link_entries(db_session, first, task_actor) == [
        ("link_added", {"kind": "blocks", "other": "TRK-2"}),
        ("link_removed", {"kind": "blocks", "other": "TRK-2"}),
    ]
    assert await link_entries(db_session, second, task_actor) == [
        ("link_added", {"kind": "blocked_by", "other": "TRK-1"}),
        ("link_removed", {"kind": "blocked_by", "other": "TRK-1"}),
    ]


async def test_the_link_entry_is_signed_by_the_author_of_the_action(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Служебную запись подписывает автор действия, а не трекер (`docs/notes/tasks.md`)."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")

    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.PARENT)

    entry = (await entries(db_session, first, task_actor))[-1]
    assert entry.type is EntryType.LINK_ADDED
    assert entry.author.signature == "owner"
    assert entry.title == "Link added: parent TRK-2"
    assert entry.body == ""


# --- Запреты ----------------------------------------------------------------------------


async def test_a_task_cannot_be_linked_to_itself(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    first = await make(db_session, task_actor, queue, "первая")

    with pytest.raises(LinkSelfError):
        await service.add_link(db_session, first, first, actor=task_actor, kind=LinkKind.RELATES)


async def test_a_closed_task_keeps_its_links(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 6: закрытая задача не принимает связь ни со своей стороны, ни с чужой."""
    closed = await make(db_session, task_actor, queue, "закрытая")
    other = await make(db_session, task_actor, queue, "живая")
    await move(db_session, closed, task_actor, TaskStatus.CANCELLED, reason="не нужна")

    with pytest.raises(TaskClosedError) as from_closed:
        await service.add_link(db_session, closed, other, actor=task_actor, kind=LinkKind.RELATES)
    assert from_closed.value.details["key"] == "TRK-1"

    with pytest.raises(TaskClosedError) as from_open:
        await service.add_link(db_session, other, closed, actor=task_actor, kind=LinkKind.RELATES)
    assert from_open.value.details["key"] == "TRK-1"
    assert from_open.value.details["status"] == "cancelled"


async def test_a_link_of_a_closed_task_cannot_be_removed_either(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.RELATES)
    await move(db_session, second, task_actor, TaskStatus.CANCELLED, reason="не нужна")

    with pytest.raises(TaskClosedError):
        await service.remove_link(
            db_session, first, second, actor=task_actor, kind=LinkKind.RELATES
        )


# --- Циклы ------------------------------------------------------------------------------


async def test_a_two_task_hierarchy_cycle_is_refused(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 3, первая половина."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.PARENT)

    with pytest.raises(LinkCycleError) as error:
        await service.add_link(db_session, second, first, actor=task_actor, kind=LinkKind.PARENT)

    assert error.value.code == "link_cycle_detected"


async def test_a_three_task_blocking_cycle_is_refused(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 3, вторая половина: кольцо длиной три ловится обходом графа."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    third = await make(db_session, task_actor, queue, "третья")
    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.BLOCKS)
    await service.add_link(db_session, second, third, actor=task_actor, kind=LinkKind.BLOCKS)

    with pytest.raises(LinkCycleError) as error:
        await service.add_link(db_session, third, first, actor=task_actor, kind=LinkKind.BLOCKS)

    assert error.value.code == "link_cycle_detected"
    assert error.value.details["key"] == "TRK-3"


async def test_a_parent_may_be_blocked_by_its_own_child(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Иерархия и блокировки — два независимых графа: так выражается «жду декомпозицию»."""
    parent = await make(db_session, task_actor, queue, "родитель")
    child = await make(db_session, task_actor, queue, "ребёнок")
    await service.add_link(db_session, parent, child, actor=task_actor, kind=LinkKind.PARENT)

    await service.add_link(db_session, parent, child, actor=task_actor, kind=LinkKind.BLOCKED_BY)

    kinds = {link.kind for link in await service.list_links(db_session, parent, actor=task_actor)}
    assert kinds == {LinkKind.PARENT, LinkKind.BLOCKED_BY}


async def test_relates_never_makes_a_cycle(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """`relates` — только контекст, и кольца из него законны."""
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    third = await make(db_session, task_actor, queue, "третья")

    await service.add_link(db_session, first, second, actor=task_actor, kind=LinkKind.RELATES)
    await service.add_link(db_session, second, third, actor=task_actor, kind=LinkKind.RELATES)
    await service.add_link(db_session, third, first, actor=task_actor, kind=LinkKind.RELATES)

    assert len(await service.list_links(db_session, first, actor=task_actor)) == 2


# --- Признак `blocked` и валидации перехода ---------------------------------------------


async def test_blocked_is_true_exactly_while_a_blocker_is_open(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 7, вторая половина: закрытый блокер признак не поднимает."""
    blocker = await make(db_session, task_actor, queue, "блокер")
    blocked = await make(db_session, task_actor, queue, "заблокированная")
    await service.add_link(db_session, blocker, blocked, actor=task_actor, kind=LinkKind.BLOCKS)

    package = await tasks_service.read_task_package(db_session, blocked.key, actor=task_actor)
    assert package.features.blocked is True
    assert [link.kind for link in package.links] == [LinkKind.BLOCKED_BY]

    await move(
        db_session,
        blocker,
        task_actor,
        TaskStatus.OPEN,
        TaskStatus.IN_PROGRESS,
        TaskStatus.DONE,
    )

    package = await tasks_service.read_task_package(db_session, blocked.key, actor=task_actor)
    assert package.features.blocked is False
    # Связь при этом на месте: трекер её не снимает — это сделал бы кто-то за агента.
    assert [link.kind for link in package.links] == [LinkKind.BLOCKED_BY]


async def test_a_blocked_task_is_not_taken_into_work_until_the_blocker_closes(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 1: отказ со списком блокеров, а после закрытия блокера — проход."""
    blocker = await make(db_session, task_actor, queue, "блокер")
    blocked = await make(db_session, task_actor, queue, "заблокированная")
    await service.add_link(db_session, blocker, blocked, actor=task_actor, kind=LinkKind.BLOCKS)
    await move(db_session, blocked, task_actor, TaskStatus.OPEN)

    with pytest.raises(TaskBlockedError) as error:
        await tasks_service.transition_task(
            db_session, blocked, actor=task_actor, to=TaskStatus.IN_PROGRESS
        )
    assert error.value.details["blockers"] == ["TRK-1"]
    assert blocked.status is TaskStatus.OPEN

    await move(
        db_session,
        blocker,
        task_actor,
        TaskStatus.OPEN,
        TaskStatus.IN_PROGRESS,
        TaskStatus.DONE,
    )
    await tasks_service.transition_task(
        db_session, blocked, actor=task_actor, to=TaskStatus.IN_PROGRESS
    )

    assert blocked.status is TaskStatus.IN_PROGRESS


async def test_a_parent_does_not_close_while_a_child_is_open(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
) -> None:
    """Обзорная проверка 2: отказ со списком детей, после отмены ребёнка — проход."""
    parent = await make(db_session, task_actor, queue, "родитель")
    child = await make(db_session, task_actor, queue, "ребёнок")
    await service.add_link(db_session, parent, child, actor=task_actor, kind=LinkKind.PARENT)
    await move(db_session, child, task_actor, TaskStatus.OPEN)
    await move(
        db_session,
        parent,
        task_actor,
        TaskStatus.OPEN,
        TaskStatus.IN_PROGRESS,
    )
    await summary(db_session, parent, task_actor)
    for check_no in range(1, len(parent.checks) + 1):
        await case_service.add_verdict(
            db_session, parent, actor=task_actor, check_no=check_no, outcome="passed"
        )

    with pytest.raises(TaskHasUnclosedChildrenError) as error:
        await tasks_service.transition_task(
            db_session, parent, actor=task_actor, to=TaskStatus.DONE
        )
    assert error.value.details["children"] == ["TRK-2"]

    await tasks_service.transition_task(
        db_session, child, actor=task_actor, to=TaskStatus.CANCELLED, reason="не понадобился"
    )
    await tasks_service.transition_task(db_session, parent, actor=task_actor, to=TaskStatus.DONE)

    assert parent.status is TaskStatus.DONE
