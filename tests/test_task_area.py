"""Поле задачи `area` (TRK-556): заведение и правка, `get_task`, поиск, снятие переносом.

Правила — TRK#57, TRK#153 и TRK#167 (решение владельца
`TRK#16`, части 3 и 4; обязательность — TRK-677): адрес области того же проекта, одна на
задачу; правка подшивает `field_changed` в дело задачи; наследования нет; перенос
ставит область целевого проекта. В этом файле `task` и `_new` без `area` — задачи,
заведённые до правила: строка с пустой областью, в обход сервиса.

Обзорные проверки задачи: (а) `update_task` ставит область, в деле `field_changed`;
(б) чужой проект — `area_project_mismatch`, архивная — `area_archived`;
(в) ребёнок не берёт область родителя; (г) `move_task` снимает поле и подшивает
`field_changed`; (д) `area:` отбирает, `empty()` находит задачи без области,
несуществующий адрес — отказ.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.case import EntryType
from app.domain.errors import (
    AreaArchivedError,
    AreaNotFoundError,
    AreaProjectMismatchError,
    AreaRequiredError,
    ProjectArchivedError,
    SearchValueInvalidError,
    TaskClosedError,
    TaskFieldsInvalidError,
)
from app.domain.links import LinkKind
from app.domain.tasks import TaskStatus
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges
from conftest import Connect, call, make_task, move_task, refuse


async def _area(
    session: AsyncSession, actor: Actor, address: str = "TRK/x", title: str = "Популяризация"
) -> Area:
    return await areas_service.create_area(
        session, actor=actor, address=address, title=title, description="Каталоги"
    )


async def _set(session: AsyncSession, actor: Actor, task: Task, address: str | None) -> Any:
    return await tasks_service.update_task(
        session, task, actor=actor, changes=TaskChanges(area=address)
    )


async def _field_changes(session: AsyncSession, actor: Actor, task: Task) -> list[dict[str, Any]]:
    entries = await case_service.list_entries(
        session, task, actor=actor, types=[EntryType.FIELD_CHANGED]
    )
    return [entry.payload for entry in entries.items]


async def _keys(session: AsyncSession, actor: Actor, **kwargs: Any) -> list[str]:
    outcome = await search_service.search_tasks(session, actor=actor, **kwargs)
    return [found.task.key for found in outcome.page.items]


@pytest.fixture
async def task(db_session: AsyncSession, task: Task) -> Task:
    """`TRK-1` как заведённая до правила: без области."""
    task.area = None
    await db_session.flush()
    return task


async def _new(
    session: AsyncSession, actor: Actor, project: Project, title: str, **kw: Any
) -> Task:
    """Задача с областью, если она названа; без `area` — «старая», без области."""
    created = await make_task(
        session, actor=actor, project=project, title=title, description="Для проверки", **kw
    )
    if "area" not in kw:
        created.area = None
        await session.flush()
    return created


# --- (а) Постановка и правка ---------------------------------------------------------------


async def test_update_sets_the_area_and_files_field_changed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    area = await _area(db_session, main_actor)
    assert task.area is None

    mutation = await _set(db_session, main_actor, task, "trk/X")

    assert task.area_id == area.id
    assert [(change.field, change.before, change.after) for change in mutation.changes] == [
        ("area", None, "TRK/x")
    ]
    assert await _field_changes(db_session, main_actor, task) == [
        {"field": "area", "before": None, "after": "TRK/x"}
    ]
    # В дело области ничего не пишется: в нём одна служебная запись `created`.
    own = (await EntryRepository(db_session).list_area_page(area.id)).items
    assert [entry.type for entry in own] == [EntryType.CREATED]


async def test_the_area_changes_with_a_record_each_time_and_cannot_be_cleared(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await _area(db_session, main_actor, "TRK/x")
    await _area(db_session, main_actor, "TRK/y", "Коммерция")

    await _set(db_session, main_actor, task, "TRK/x")
    await _set(db_session, main_actor, task, "TRK/y")
    same = await _set(db_session, main_actor, task, "TRK/y")
    with pytest.raises(AreaRequiredError):
        await _set(db_session, main_actor, task, None)

    assert not same.changed, "то же значение — ни версии, ни записи"
    assert task.area is not None and task.area.address == "TRK/y"
    assert [
        (item["before"], item["after"])
        for item in await _field_changes(db_session, main_actor, task)
    ] == [
        (None, "TRK/x"),
        ("TRK/x", "TRK/y"),
    ]


async def test_the_area_is_editable_in_open_and_in_progress_but_not_when_closed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await _area(db_session, main_actor)
    await tasks_service.transition_task(db_session, task, actor=main_actor, to=TaskStatus.OPEN)
    await _set(db_session, main_actor, task, "TRK/x")
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
    )
    await _set(db_session, main_actor, task, "TRK/core")
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
    assert (problem["field"], problem["reason"]) == ("area", "invalid_address")


async def test_an_unknown_area_is_refused(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    with pytest.raises(AreaNotFoundError):
        await _set(db_session, main_actor, task, "TRK/nope")


# --- (б) Отказы -----------------------------------------------------------------------------


async def test_an_area_of_another_project_is_a_mismatch_with_both_projects(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await projects_service.create_project(db_session, actor=main_actor, key="UI", title="Интерфейс")
    await _area(db_session, main_actor, "UI/board")

    with pytest.raises(AreaProjectMismatchError) as refused:
        await _set(db_session, main_actor, task, "UI/board")

    assert refused.value.details == {
        "area": "UI/board",
        "task_project": "TRK",
        "area_project": "UI",
    }
    assert task.area is None
    # И при создании: задача проекта `TRK` в область `UI` не встаёт.
    with pytest.raises(AreaProjectMismatchError):
        await _new(db_session, main_actor, project, "Новая", area="UI/board")


async def test_an_archived_area_cannot_be_set_but_can_be_left(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    area = await _area(db_session, main_actor)
    other = await _new(db_session, main_actor, project, "Вторая")
    await _set(db_session, main_actor, task, "TRK/x")
    await areas_service.archive_area(db_session, area, actor=main_actor, reason="Пауза")

    with pytest.raises(AreaArchivedError):
        await _set(db_session, main_actor, other, "TRK/x")
    with pytest.raises(AreaArchivedError):
        await _new(db_session, main_actor, project, "Третья", area="TRK/x")
    # Уже стоящее остаётся, а уйти из него можно в другую область (снять нельзя).
    await tasks_service.update_task(
        db_session, task, actor=main_actor, changes=TaskChanges(priority="high", area="TRK/x")
    )
    await _set(db_session, main_actor, task, "TRK/core")
    assert task.area is not None and task.area.address == "TRK/core"


async def test_the_area_of_a_task_in_an_archived_project_is_frozen(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    await _area(db_session, main_actor)
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")
    with pytest.raises(ProjectArchivedError):
        await _set(db_session, main_actor, task, "TRK/x")


# --- Создание и (в) наследование --------------------------------------------------------------


async def test_create_task_takes_the_area(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _area(db_session, main_actor)
    created = await _new(db_session, main_actor, project, "Внутри области", area="trk/x")
    assert created.area.address == "TRK/x"
    with pytest.raises(AreaRequiredError):
        await tasks_service.create_task(
            db_session, actor=main_actor, project=project, title="Без области", description="d"
        )


async def test_a_child_does_not_inherit_the_area_of_its_parent(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _area(db_session, main_actor)
    parent = await _new(db_session, main_actor, project, "Программа", area="TRK/x")
    child = await _new(db_session, main_actor, project, "Часть", area="TRK/core")
    await links_service.add_link(db_session, child, parent, actor=main_actor, kind=LinkKind.CHILD)

    assert parent.area is not None
    assert child.area is not None
    assert child.area.address == "TRK/core"


async def test_mcp_creates_a_child_with_its_own_area_not_the_parents(
    mcp_session: Connect,
    task_secret: str,
    project: Project,
    main_actor: Actor,
    db_session: AsyncSession,
) -> None:
    await _area(db_session, main_actor)
    async with mcp_session(task_secret) as session:
        parent = await call(
            session,
            "create_task",
            project="TRK",
            title="Программа",
            description="d",
            area="TRK/x",
        )
        child = await call(
            session,
            "create_task",
            project="TRK",
            area="TRK/core",
            title="Часть",
            description="d",
            parent=parent["key"],
        )
        card = await call(session, "get_task", key=child["key"])
        parent_card = await call(session, "get_task", key=parent["key"])

    assert card["task"]["area"]["address"] == "TRK/core"
    assert parent_card["task"]["area"] == {
        "address": "TRK/x",
        "title": "Популяризация",
        "description": "Каталоги",
        "archived_at": None,
    }


# --- (г) Перенос ----------------------------------------------------------------------------


async def test_move_replaces_the_area_and_files_field_changed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    board = await _area(db_session, main_actor, "UI/board", "Доска")
    await _area(db_session, main_actor)
    await _set(db_session, main_actor, task, "TRK/x")

    await tasks_service.move_task(
        db_session, task, actor=main_actor, project=ui, reason="Интерфейс", area="UI/board"
    )

    assert task.area_id == board.id
    assert (await _field_changes(db_session, main_actor, task))[-1] == {
        "field": "area",
        "before": "TRK/x",
        "after": "UI/board",
    }
    moves = await case_service.list_entries(
        db_session, task, actor=main_actor, types=[EntryType.MOVED]
    )
    assert len(moves.items) == 1


async def test_a_closed_task_in_an_archived_area_still_moves_to_a_live_one(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    await _area(db_session, main_actor, "UI/board", "Доска")
    area = await _area(db_session, main_actor)
    await _set(db_session, main_actor, task, "TRK/x")
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )
    await areas_service.archive_area(db_session, area, actor=main_actor, reason="Пауза")

    await tasks_service.move_task(
        db_session, task, actor=main_actor, project=ui, reason="Перенос", area="UI/board"
    )

    assert task.area is not None and task.area.address == "UI/board"


async def test_a_move_of_an_old_task_without_an_area_files_the_new_one_as_from_null(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    await move_task(db_session, task, actor=main_actor, project=ui, reason="Интерфейс")
    assert await _field_changes(db_session, main_actor, task) == [
        {"field": "area", "before": None, "after": "UI/core"}
    ]


# --- (д) Поиск ------------------------------------------------------------------------------


async def test_search_selects_by_the_area_of_the_task_itself(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _area(db_session, main_actor, "TRK/x")
    await _area(db_session, main_actor, "TRK/y", "Коммерция")
    inside = await _new(db_session, main_actor, project, "Внутри x", area="TRK/x")
    other = await _new(db_session, main_actor, project, "Внутри y", area="TRK/y")
    free = await _new(db_session, main_actor, project, "Без")
    child = await _new(db_session, main_actor, project, "Ребёнок задачи в x")
    await links_service.add_link(db_session, child, inside, actor=main_actor, kind=LinkKind.CHILD)

    assert await _keys(db_session, main_actor, query="area: TRK/x") == [inside.key]
    assert await _keys(db_session, main_actor, query="area: trk/Y") == [other.key]
    assert await _keys(db_session, main_actor, query="area: empty()") == [free.key, child.key]
    assert await _keys(db_session, main_actor, query="area: != TRK/x") == [
        other.key,
        free.key,
        child.key,
    ]
    assert await _keys(db_session, main_actor, query="area: in TRK/x, TRK/y") == [
        inside.key,
        other.key,
    ]
    assert await _keys(db_session, main_actor, query="area: not in TRK/x, TRK/y") == [
        free.key,
        child.key,
    ]
    assert await _keys(db_session, main_actor, query="area: TRK/x, empty()") == [
        inside.key,
        free.key,
        child.key,
    ]
    # Структурный фильтр — тем же путём.
    structured = [search_service.StructuredTerm(name="area", values=["TRK/y"])]
    assert await _keys(db_session, main_actor, structured=structured) == [other.key]


@pytest.mark.parametrize("address", ["TRK/nope", "NOPE/x", "TRK"])
async def test_an_unknown_area_in_a_query_is_refused(
    db_session: AsyncSession, main_actor: Actor, project: Project, address: str
) -> None:
    with pytest.raises(SearchValueInvalidError) as refused:
        await _keys(db_session, main_actor, query=f"area: {address}")
    assert refused.value.details["field"] == "area"


async def test_the_row_carries_the_area_only_when_asked(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await _area(db_session, main_actor)
    await _new(db_session, main_actor, project, "Внутри x", area="TRK/x")
    await _new(db_session, main_actor, project, "Без")

    narrow = await search_service.search_tasks(db_session, actor=main_actor, fields=["key"])
    asked = await search_service.search_tasks(db_session, actor=main_actor, fields=["key", "area"])

    assert [found.area for found in narrow.page.items] == [None, None]
    values = [found.area.value for found in asked.page.items if found.area]
    assert [value.address if value else None for value in values] == ["TRK/x", None]


# --- REST и MCP -----------------------------------------------------------------------------


async def test_rest_sets_reads_and_searches_the_area(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    main_actor: Actor,
    project: Project,
    task: Task,
) -> None:
    await _area(db_session, main_actor)
    key = task.key

    patched = await auth_client.patch(f"/api/v1/tasks/{key}", json={"area": "TRK/x"})
    created = await auth_client.post(
        "/api/v1/tasks",
        json={"project": "TRK", "title": "Новая", "description": "d", "area": "TRK/x"},
    )
    bad = await auth_client.patch(f"/api/v1/tasks/{key}", json={"area": "TRK/zzz"})
    package = await auth_client.get(f"/api/v1/tasks/{key}")
    found = await auth_client.get(
        "/api/v1/tasks", params={"query": "area: TRK/x", "fields": "key,area"}
    )
    structured = await auth_client.get("/api/v1/tasks", params={"area": "TRK/x", "fields": "key"})

    expected = {
        "address": "TRK/x",
        "title": "Популяризация",
        "description": "Каталоги",
        "archived_at": None,
    }
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["area"] == expected
    assert created.json()["data"]["area"] == expected
    assert (bad.status_code, bad.json()["error"]["code"]) == (404, "area_not_found")
    assert package.json()["data"]["task"]["area"] == expected
    rows = found.json()["data"]
    assert {row["key"] for row in rows} == {key, created.json()["data"]["key"]}
    assert all(row["area"] == {"address": "TRK/x", "title": "Популяризация"} for row in rows)
    assert len(structured.json()["data"]) == 2


async def test_mcp_sets_the_area_and_finds_the_task_by_it(
    mcp_session: Connect,
    task_secret: str,
    project: Project,
    task: Task,
    main_actor: Actor,
    db_session: AsyncSession,
) -> None:
    await _area(db_session, main_actor)
    key = task.key
    async with mcp_session(task_secret) as session:
        updated = await call(session, "update_task", key=key, changes={"area": "TRK/x"})
        found = await call(session, "search_tasks", query="area: TRK/x", fields=["key", "area"])
        by_argument = await call(session, "search_tasks", area=["empty()"], fields=["key"])
        refused = await refuse(session, "update_task", key=key, changes={"area": "UI/x"})
        cleared = await refuse(session, "update_task", key=key, changes={"area": None})
        card = await call(session, "get_task", key=key)

    assert updated["entries"]
    assert found["items"] == [{"key": key, "area": {"address": "TRK/x", "title": "Популяризация"}}]
    assert [row["key"] for row in by_argument["items"]] == []
    assert "project_not_found" in refused or "area_not_found" in refused
    assert "area_required" in cleared
    assert card["task"]["area"]["address"] == "TRK/x"
