"""Область у новой задачи обязательна (TRK-677, решение проекта `TRK#57`, раздел 4).

`create_task` и `move_task` без области — `area_required`, `update_task(area=null)` — тот
же отказ: область можно сменить, но не снять. Старая задача без области — заведённая до
правила — читается и правится по другим полям как раньше, и область ей ставится.

Проверка стоит на входе вызова: трекер область не ставит и не подбирает, в `details`
отказа — проект и адреса его неархивных областей, выбор за агентом (`CONCEPT.md`, 3.3).
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import AreaRequiredError
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges
from conftest import AREA, Connect, call, make_area, refuse


@pytest.fixture
async def old_task(db_session: AsyncSession, task: Task) -> Task:
    """Задача без области — как заведённая до правила: в обход сервиса, строкой."""
    task.area = None
    await db_session.flush()
    return task


async def _empty_project(session: AsyncSession, actor: Actor, key: str = "EMP") -> Project:
    return await projects_service.create_project(session, actor=actor, key=key, title="Пустой")


# --- create_task ---------------------------------------------------------------------------


async def test_create_task_without_an_area_names_the_projects_areas(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    await make_area(db_session, main_actor, "TRK", "extra")
    archived = await make_area(db_session, main_actor, "TRK", "gone")
    await areas_service.archive_area(
        db_session, await areas_service.get_area(db_session, archived), actor=main_actor, reason="p"
    )

    with pytest.raises(AreaRequiredError) as refused:
        await tasks_service.create_task(
            db_session, actor=main_actor, project=project, title="Задача", description="описание"
        )

    assert refused.value.code == "area_required"
    assert refused.value.details == {"project": "TRK", "areas": ["TRK/core", "TRK/extra"]}


async def test_the_refusal_burns_no_task_number(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    with pytest.raises(AreaRequiredError):
        await tasks_service.create_task(
            db_session, actor=main_actor, project=project, title="Задача", description="описание"
        )
    created = await tasks_service.create_task(
        db_session,
        actor=main_actor,
        project=project,
        title="Задача",
        description="описание",
        area=AREA,
    )
    assert created.key == "TRK-1"


async def test_rest_create_without_an_area_is_422_with_the_areas(
    auth_client: AsyncClient, project: Project
) -> None:
    refused = await auth_client.post(
        "/api/v1/tasks", json={"project": "TRK", "title": "Новая", "description": "d"}
    )
    explicit_null = await auth_client.post(
        "/api/v1/tasks",
        json={"project": "TRK", "title": "Новая", "description": "d", "area": None},
    )

    for response in (refused, explicit_null):
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "area_required"
        assert error["details"] == {"project": "TRK", "areas": ["TRK/core"]}


async def test_rest_create_in_a_project_without_areas_has_an_empty_list(
    auth_client: AsyncClient, db_session: AsyncSession, main_actor: Actor
) -> None:
    await _empty_project(db_session, main_actor)

    refused = await auth_client.post(
        "/api/v1/tasks", json={"project": "EMP", "title": "Новая", "description": "d"}
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["details"] == {"project": "EMP", "areas": []}


async def test_mcp_create_without_an_area_names_the_areas_and_with_one_succeeds(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        text = await refuse(
            session, "create_task", project="TRK", title="Задача", description="описание"
        )
        created = await call(
            session, "create_task", project="TRK", title="Задача", description="описание", area=AREA
        )

    assert "area_required" in text
    assert "TRK/core" in text
    assert created["key"] == "TRK-1"


async def test_mcp_create_in_a_project_without_areas_is_refused_with_an_empty_list(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession, main_actor: Actor
) -> None:
    await _empty_project(db_session, main_actor)
    async with mcp_session(task_secret) as session:
        text = await refuse(
            session, "create_task", project="EMP", title="Задача", description="описание"
        )

    assert "area_required" in text
    assert '"areas": []' in text or "'areas': []" in text


# --- update_task ---------------------------------------------------------------------------


async def test_clearing_the_area_is_refused_and_changing_it_is_not(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    other = await make_area(db_session, main_actor, "TRK", "other")
    assert task.area is not None

    with pytest.raises(AreaRequiredError) as refused:
        await tasks_service.update_task(
            db_session, task, actor=main_actor, changes=TaskChanges(area=None)
        )
    await tasks_service.update_task(
        db_session, task, actor=main_actor, changes=TaskChanges(area=other)
    )

    assert refused.value.details["areas"] == ["TRK/core", "TRK/other"]
    assert task.area is not None
    assert task.area.address == other


async def test_rest_patch_with_a_null_area_is_422(
    auth_client: AsyncClient, project: Project, task: Task
) -> None:
    refused = await auth_client.patch(f"/api/v1/tasks/{task.key}", json={"area": None})
    untouched = await auth_client.patch(f"/api/v1/tasks/{task.key}", json={"priority": "high"})

    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "area_required"
    assert untouched.status_code == 200, untouched.text
    assert untouched.json()["data"]["area"]["address"] == AREA


async def test_mcp_update_with_a_null_area_is_refused_and_leaving_it_out_is_not(
    mcp_session: Connect, task_secret: str, project: Project, task: Task
) -> None:
    key = task.key
    async with mcp_session(task_secret) as session:
        text = await refuse(session, "update_task", key=key, changes={"area": None})
        await call(session, "update_task", key=key, changes={"priority": "high"})
        card = await call(session, "get_task", key=key)

    assert "area_required" in text
    assert card["task"]["area"]["address"] == AREA


# --- move_task -----------------------------------------------------------------------------


async def test_move_without_an_area_is_refused_and_with_one_replaces_it(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    board = await make_area(db_session, main_actor, "UI", "board")

    with pytest.raises(AreaRequiredError) as refused:
        await tasks_service.move_task(
            db_session, task, actor=main_actor, project=ui, reason="Интерфейс"
        )
    assert refused.value.details == {"project": "UI", "areas": ["UI/board"]}
    assert task.key == "TRK-1", "отказ ничего не перенёс"

    await tasks_service.move_task(
        db_session, task, actor=main_actor, project=ui, reason="Интерфейс", area=board
    )

    assert (task.key, task.area.address) == ("UI-1", "UI/board")
    changes = await case_service.list_entries(
        db_session, task, actor=main_actor, types=[EntryType.FIELD_CHANGED]
    )
    assert [item.payload for item in changes.items][-1] == {
        "field": "area",
        "before": AREA,
        "after": "UI/board",
    }


async def test_move_refuses_a_foreign_and_an_archived_area(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    from app.domain.errors import AreaArchivedError, AreaProjectMismatchError

    ui = await projects_service.create_project(
        db_session, actor=main_actor, key="UI", title="Интерфейс"
    )
    gone = await make_area(db_session, main_actor, "UI", "gone")
    await areas_service.archive_area(
        db_session, await areas_service.get_area(db_session, gone), actor=main_actor, reason="п"
    )

    with pytest.raises(AreaProjectMismatchError):
        await tasks_service.move_task(
            db_session, task, actor=main_actor, project=ui, reason="Интерфейс", area=AREA
        )
    with pytest.raises(AreaArchivedError):
        await tasks_service.move_task(
            db_session, task, actor=main_actor, project=ui, reason="Интерфейс", area=gone
        )
    assert task.key == "TRK-1"


async def test_rest_move_needs_the_area_of_the_target_project(
    auth_client: AsyncClient, db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    await projects_service.create_project(db_session, actor=main_actor, key="UI", title="UI")
    await make_area(db_session, main_actor, "UI", "board")

    refused = await auth_client.post(
        f"/api/v1/tasks/{task.key}/move", json={"project": "UI", "reason": "Интерфейс"}
    )
    moved = await auth_client.post(
        f"/api/v1/tasks/{task.key}/move",
        json={"project": "UI", "reason": "Интерфейс", "area": "UI/board"},
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "area_required"
    assert refused.json()["error"]["details"] == {"project": "UI", "areas": ["UI/board"]}
    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["area"]["address"] == "UI/board"


async def test_mcp_move_needs_the_area_for_one_key_and_for_a_list(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    main_actor: Actor,
    project: Project,
    task: Task,
) -> None:
    await projects_service.create_project(db_session, actor=main_actor, key="UI", title="UI")
    await make_area(db_session, main_actor, "UI", "board")
    key = task.key
    async with mcp_session(task_secret) as session:
        single = await refuse(session, "move_task", key=key, project="UI", reason="Причина")
        listed = await call(session, "move_task", key=[key], project="UI", reason="Причина")
        moved = await call(
            session, "move_task", key=key, project="UI", reason="Причина", area="UI/board"
        )
        card = await call(session, "get_task", key=moved["key"])

    assert "area_required" in single
    [outcome] = listed["results"]
    assert (outcome["outcome"], outcome["code"]) == ("error", "area_required")
    assert card["task"]["area"]["address"] == "UI/board"


# --- Старые задачи без области -------------------------------------------------------------


async def test_a_task_filed_before_the_rule_reads_edits_and_takes_an_area(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    old_task: Task,
) -> None:
    key = old_task.key
    async with mcp_session(task_secret) as session:
        before: dict[str, Any] = await call(session, "get_task", key=key)
        await call(session, "update_task", key=key, changes={"priority": "high"})
        text = await refuse(session, "update_task", key=key, changes={"area": None})
        await call(session, "update_task", key=key, changes={"area": AREA})
        after: dict[str, Any] = await call(session, "get_task", key=key)

    assert before["task"]["area"] is None
    assert "area_required" in text
    assert after["task"]["priority"] == "high"
    assert after["task"]["area"]["address"] == AREA
