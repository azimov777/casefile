"""Поле задачи `direction` (TRK-556): заведение и правка, `get_task`, поиск, снятие переносом.

Правила — `CONCEPT.md`, 3.3 («Направление задачи»), 3.7, 4.2 и 4.4 (решение владельца
`TRK#16`, части 3 и 4): адрес направления того же проекта или `null`, одно на задачу;
правка подшивает `field_changed` в дело задачи; наследования нет; перенос снимает поле.

Обзорные проверки задачи: (а) `update_task` ставит направление, в деле `field_changed`;
(б) чужой проект — `direction_project_mismatch`, архивное — `direction_archived`;
(в) ребёнок не берёт направление родителя; (г) `move_task` снимает поле и подшивает
`field_changed`; (д) `direction:` отбирает, `empty()` находит задачи без направления,
несуществующий адрес — отказ.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.direction import Direction
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.case import EntryType
from app.domain.errors import (
    DirectionArchivedError,
    DirectionNotFoundError,
    DirectionProjectMismatchError,
    ProjectArchivedError,
    SearchValueInvalidError,
    TaskClosedError,
    TaskFieldsInvalidError,
)
from app.domain.links import LinkKind
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import directions as directions_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges
from conftest import Connect, call, refuse


async def _direction(
    session: AsyncSession, actor: Actor, address: str = "TRK/x", title: str = "Популяризация"
) -> Direction:
    return await directions_service.create_direction(
        session, actor=actor, address=address, title=title, description="Каталоги"
    )


async def _set(session: AsyncSession, actor: Actor, task: Task, address: str | None) -> Any:
    return await tasks_service.update_task(
        session, task, actor=actor, changes=TaskChanges(direction=address)
    )


async def _field_changes(session: AsyncSession, actor: Actor, task: Task) -> list[dict[str, Any]]:
    entries = await case_service.list_entries(
        session, task, actor=actor, types=[EntryType.FIELD_CHANGED]
    )
    return [entry.payload for entry in entries.items]


async def _keys(session: AsyncSession, actor: Actor, **kwargs: Any) -> list[str]:
    outcome = await search_service.search_tasks(session, actor=actor, **kwargs)
    return [found.task.key for found in outcome.page.items]


async def _new(
    session: AsyncSession, actor: Actor, project: Project, title: str, **kw: Any
) -> Task:
    return await tasks_service.create_task(
        session, actor=actor, project=project, title=title, description="Для проверки", **kw
    )


# --- (а) Постановка и правка ---------------------------------------------------------------


async def test_update_sets_the_direction_and_files_field_changed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    direction = await _direction(db_session, main_actor)
    assert task.direction is None

    mutation = await _set(db_session, main_actor, task, "trk/X")

    assert task.direction_id == direction.id
    assert [(change.field, change.before, change.after) for change in mutation.changes] == [
        ("direction", None, "TRK/x")
    ]
    assert await _field_changes(db_session, main_actor, task) == [
        {"field": "direction", "before": None, "after": "TRK/x"}
    ]
    # В дело направления ничего не пишется: в нём одна служебная запись `created`.
    own = (await EntryRepository(db_session).list_direction_page(direction.id)).items
    assert [entry.type for entry in own] == [EntryType.CREATED]


async def test_the_direction_changes_and_clears_with_a_record_each_time(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await _direction(db_session, main_actor, "TRK/x")
    await _direction(db_session, main_actor, "TRK/y", "Коммерция")

    await _set(db_session, main_actor, task, "TRK/x")
    await _set(db_session, main_actor, task, "TRK/y")
    same = await _set(db_session, main_actor, task, "TRK/y")
    await _set(db_session, main_actor, task, None)

    assert not same.changed, "то же значение — ни версии, ни записи"
    assert task.direction is None
    assert [
        (item["before"], item["after"])
        for item in await _field_changes(db_session, main_actor, task)
    ] == [
        (None, "TRK/x"),
        ("TRK/x", "TRK/y"),
        ("TRK/y", None),
    ]


async def test_the_direction_is_editable_in_open_and_in_progress_but_not_when_closed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await _direction(db_session, main_actor)
    await tasks_service.transition_task(db_session, task, actor=main_actor, to=TaskStatus.OPEN)
    await _set(db_session, main_actor, task, "TRK/x")
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
    )
    await _set(db_session, main_actor, task, None)
    cancelled = await _new(db_session, main_actor, project, "Отменённая")
    await tasks_service.transition_task(
        db_session, cancelled, actor=main_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )

    with pytest.raises(TaskClosedError):
        await _set(db_session, main_actor, cancelled, "TRK/x")


async def test_a_value_that_is_not_an_address_is_refused_with_the_shape(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    with pytest.raises(TaskFieldsInvalidError) as refused:
        await _set(db_session, main_actor, task, "TRK")
    [problem] = refused.value.details["fields"]
    assert (problem["field"], problem["reason"]) == ("direction", "invalid_address")


async def test_an_unknown_direction_is_refused(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    with pytest.raises(DirectionNotFoundError):
        await _set(db_session, main_actor, task, "TRK/nope")


# --- (б) Отказы -----------------------------------------------------------------------------


async def test_a_direction_of_another_project_is_a_mismatch_with_both_projects(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await projects_service.create_project(db_session, actor=main_actor, key="UI", title="Интерфейс")
    await _direction(db_session, main_actor, "UI/board")

    with pytest.raises(DirectionProjectMismatchError) as refused:
        await _set(db_session, main_actor, task, "UI/board")

    assert refused.value.details == {
        "direction": "UI/board",
        "task_project": "TRK",
        "direction_project": "UI",
    }
    assert task.direction is None
    # И при создании: задача проекта `TRK` в направление `UI` не встаёт.
    with pytest.raises(DirectionProjectMismatchError):
        await _new(db_session, main_actor, project, "Новая", direction="UI/board")


async def test_an_archived_direction_cannot_be_set_but_can_be_left(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    direction = await _direction(db_session, main_actor)
    other = await _new(db_session, main_actor, project, "Вторая")
    await _set(db_session, main_actor, task, "TRK/x")
    await directions_service.archive_direction(
        db_session, direction, actor=main_actor, reason="Пауза"
    )

    with pytest.raises(DirectionArchivedError):
        await _set(db_session, main_actor, other, "TRK/x")
    with pytest.raises(DirectionArchivedError):
        await _new(db_session, main_actor, project, "Третья", direction="TRK/x")
    # Уже стоящее остаётся, снять можно.
    await tasks_service.update_task(
        db_session, task, actor=main_actor, changes=TaskChanges(priority="high", direction="TRK/x")
    )
    await _set(db_session, main_actor, task, None)
    assert task.direction is None


async def test_the_direction_of_a_task_in_an_archived_project_is_frozen(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await _direction(db_session, main_actor)
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")
    with pytest.raises(ProjectArchivedError):
        await _set(db_session, main_actor, task, "TRK/x")


# --- Создание и (в) наследование --------------------------------------------------------------


async def test_create_task_takes_the_direction(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _direction(db_session, main_actor)
    created = await _new(db_session, main_actor, project, "Внутри направления", direction="trk/x")
    plain = await _new(db_session, main_actor, project, "Без направления")
    assert (created.direction.address, plain.direction) == ("TRK/x", None)


async def test_a_child_does_not_inherit_the_direction_of_its_parent(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _direction(db_session, main_actor)
    parent = await _new(db_session, main_actor, project, "Программа", direction="TRK/x")
    child = await _new(db_session, main_actor, project, "Часть")
    await links_service.add_link(db_session, child, parent, actor=main_actor, kind=LinkKind.CHILD)

    assert parent.direction is not None
    assert child.direction is None


async def test_mcp_creates_a_child_with_a_parent_and_no_direction(
    mcp_session: Connect,
    task_secret: str,
    project: Project,
    main_actor: Actor,
    db_session: AsyncSession,
) -> None:
    await _direction(db_session, main_actor)
    async with mcp_session(task_secret) as session:
        parent = await call(
            session,
            "create_task",
            project="TRK",
            title="Программа",
            description="d",
            direction="TRK/x",
        )
        child = await call(
            session,
            "create_task",
            project="TRK",
            title="Часть",
            description="d",
            parent=parent["key"],
        )
        card = await call(session, "get_task", key=child["key"])
        parent_card = await call(session, "get_task", key=parent["key"])

    assert card["task"]["direction"] is None
    assert parent_card["task"]["direction"] == {
        "address": "TRK/x",
        "title": "Популяризация",
        "description": "Каталоги",
        "archived_at": None,
    }


# --- (г) Перенос ----------------------------------------------------------------------------


async def test_move_drops_the_direction_and_files_field_changed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    await _direction(db_session, main_actor)
    await _set(db_session, main_actor, task, "TRK/x")

    await tasks_service.move_task(
        db_session, task, actor=main_actor, project=ui, reason="Интерфейс"
    )

    assert task.direction is None
    assert (await _field_changes(db_session, main_actor, task))[-1] == {
        "field": "direction",
        "before": "TRK/x",
        "after": None,
    }
    moves = await case_service.list_entries(
        db_session, task, actor=main_actor, types=[EntryType.MOVED]
    )
    assert len(moves.items) == 1


async def test_a_closed_task_in_an_archived_direction_still_moves_and_drops_it(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    direction = await _direction(db_session, main_actor)
    await _set(db_session, main_actor, task, "TRK/x")
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )
    await directions_service.archive_direction(
        db_session, direction, actor=main_actor, reason="Пауза"
    )

    await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason="Перенос")

    assert task.direction is None


async def test_a_move_of_a_task_without_a_direction_files_no_field_changed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    await tasks_service.move_task(
        db_session, task, actor=main_actor, project=ui, reason="Интерфейс"
    )
    assert await _field_changes(db_session, main_actor, task) == []


# --- (д) Поиск ------------------------------------------------------------------------------


async def test_search_selects_by_the_direction_of_the_task_itself(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _direction(db_session, main_actor, "TRK/x")
    await _direction(db_session, main_actor, "TRK/y", "Коммерция")
    inside = await _new(db_session, main_actor, project, "Внутри x", direction="TRK/x")
    other = await _new(db_session, main_actor, project, "Внутри y", direction="TRK/y")
    free = await _new(db_session, main_actor, project, "Без")
    child = await _new(db_session, main_actor, project, "Ребёнок задачи в x")
    await links_service.add_link(db_session, child, inside, actor=main_actor, kind=LinkKind.CHILD)

    assert await _keys(db_session, main_actor, query="direction: TRK/x") == [inside.key]
    assert await _keys(db_session, main_actor, query="direction: trk/Y") == [other.key]
    assert await _keys(db_session, main_actor, query="direction: empty()") == [free.key, child.key]
    assert await _keys(db_session, main_actor, query="direction: != TRK/x") == [
        other.key,
        free.key,
        child.key,
    ]
    assert await _keys(db_session, main_actor, query="direction: in TRK/x, TRK/y") == [
        inside.key,
        other.key,
    ]
    assert await _keys(db_session, main_actor, query="direction: not in TRK/x, TRK/y") == [
        free.key,
        child.key,
    ]
    assert await _keys(db_session, main_actor, query="direction: TRK/x, empty()") == [
        inside.key,
        free.key,
        child.key,
    ]
    # Структурный фильтр — тем же путём.
    structured = [search_service.StructuredTerm(name="direction", values=["TRK/y"])]
    assert await _keys(db_session, main_actor, structured=structured) == [other.key]


@pytest.mark.parametrize("address", ["TRK/nope", "NOPE/x", "TRK"])
async def test_an_unknown_direction_in_a_query_is_refused(
    db_session: AsyncSession, main_actor: Actor, project: Project, address: str
) -> None:
    with pytest.raises(SearchValueInvalidError) as refused:
        await _keys(db_session, main_actor, query=f"direction: {address}")
    assert refused.value.details["field"] == "direction"


async def test_the_row_carries_the_direction_only_when_asked(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _direction(db_session, main_actor)
    await _new(db_session, main_actor, project, "Внутри x", direction="TRK/x")
    await _new(db_session, main_actor, project, "Без")

    narrow = await search_service.search_tasks(db_session, actor=main_actor, fields=["key"])
    asked = await search_service.search_tasks(
        db_session, actor=main_actor, fields=["key", "direction"]
    )

    assert [found.direction for found in narrow.page.items] == [None, None]
    values = [found.direction.value for found in asked.page.items if found.direction]
    assert [value.address if value else None for value in values] == ["TRK/x", None]


# --- REST и MCP -----------------------------------------------------------------------------


async def test_rest_sets_reads_and_searches_the_direction(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    main_actor: Actor,
    project: Project,
    task: Task,
) -> None:
    await _direction(db_session, main_actor)
    key = task.key

    patched = await auth_client.patch(f"/api/v1/tasks/{key}", json={"direction": "TRK/x"})
    created = await auth_client.post(
        "/api/v1/tasks",
        json={"project": "TRK", "title": "Новая", "description": "d", "direction": "TRK/x"},
    )
    bad = await auth_client.patch(f"/api/v1/tasks/{key}", json={"direction": "TRK/zzz"})
    package = await auth_client.get(f"/api/v1/tasks/{key}")
    found = await auth_client.get(
        "/api/v1/tasks", params={"query": "direction: TRK/x", "fields": "key,direction"}
    )
    structured = await auth_client.get(
        "/api/v1/tasks", params={"direction": "TRK/x", "fields": "key"}
    )

    expected = {
        "address": "TRK/x",
        "title": "Популяризация",
        "description": "Каталоги",
        "archived_at": None,
    }
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["direction"] == expected
    assert created.json()["data"]["direction"] == expected
    assert (bad.status_code, bad.json()["error"]["code"]) == (404, "direction_not_found")
    assert package.json()["data"]["task"]["direction"] == expected
    rows = found.json()["data"]
    assert {row["key"] for row in rows} == {key, created.json()["data"]["key"]}
    assert all(row["direction"] == {"address": "TRK/x", "title": "Популяризация"} for row in rows)
    assert len(structured.json()["data"]) == 2


async def test_mcp_sets_the_direction_and_finds_the_task_by_it(
    mcp_session: Connect,
    task_secret: str,
    project: Project,
    task: Task,
    main_actor: Actor,
    db_session: AsyncSession,
) -> None:
    await _direction(db_session, main_actor)
    key = task.key
    async with mcp_session(task_secret) as session:
        updated = await call(session, "update_task", key=key, changes={"direction": "TRK/x"})
        found = await call(
            session, "search_tasks", query="direction: TRK/x", fields=["key", "direction"]
        )
        by_argument = await call(session, "search_tasks", direction=["empty()"], fields=["key"])
        refused = await refuse(session, "update_task", key=key, changes={"direction": "UI/x"})
        cleared = await call(session, "update_task", key=key, changes={"direction": None})
        card = await call(session, "get_task", key=key)

    assert updated["entries"]
    assert found["items"] == [
        {"key": key, "direction": {"address": "TRK/x", "title": "Популяризация"}}
    ]
    assert [row["key"] for row in by_argument["items"]] == []
    assert "project_not_found" in refused or "direction_not_found" in refused
    assert cleared["entries"]
    assert card["task"]["direction"] is None
