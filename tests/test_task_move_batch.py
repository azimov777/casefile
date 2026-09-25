"""Пакетный перенос (TRK-309): список ключей, итог по каждой задаче, отказы вызова целиком.

Решение владельца TRK-309#2: каждая задача переносится сама по себе, ответ — `moved`,
`already` или `error` по каждому элементу списка. Отказы, общие для всего списка (набор,
причина, размер списка, неизвестный или архивный целевой проект), отвечают целиком и до
первого переноса (TRK-309#6). Одиночный перенос — `tests/test_task_move.py`, без правок.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import (
    ProjectArchivedError,
    ProjectNotFoundError,
    TaskMoveBatchSizeInvalidError,
    TaskMoveReasonRequiredError,
)
from app.domain.tasks import MAX_MOVE_KEYS
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskAlreadyThere, TaskMoved, TaskMoveRefused
from conftest import Connect, call, refuse

MOVE_BATCH = "/api/v1/tasks/move"


async def _ui_with_tasks(session: AsyncSession, actor: Actor, count: int) -> Project:
    """Проект UI с задачами UI-1 … UI-count."""
    ui = await projects_service.create_project(session, actor=actor, key="UI", title="Интерфейс")
    for number in range(1, count + 1):
        await tasks_service.create_task(
            session, actor=actor, project=ui, title=f"Экран {number}", description="Перенос"
        )
    return ui


async def _moved_entries(session: AsyncSession, task: Task) -> list[Entry]:
    found = await session.scalars(
        select(Entry).where(Entry.task_id == task.id, Entry.type == EntryType.MOVED)
    )
    return list(found.all())


# --- Сценарий ------------------------------------------------------------------------------


async def test_a_batch_gives_one_outcome_per_key_in_list_order(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    """Перенесена, уже в целевом проекте, неизвестный ключ — три итога с кодами."""
    await _ui_with_tasks(db_session, main_actor, 1)

    outcomes = await tasks_service.move_tasks(
        db_session,
        ["ui-1", "TRK-1", "NOPE-9"],
        actor=main_actor,
        project_key="trk",
        reason="  Репозиторий один  ",
    )

    moved, already, refused = outcomes
    assert moved == TaskMoved(key="ui-1", from_key="UI-1", to_key="TRK-2", no=2)
    assert already == TaskAlreadyThere(key="TRK-1", to_key="TRK-1")
    assert isinstance(refused, TaskMoveRefused) and refused.key == "NOPE-9"
    assert (refused.refusal.code, refused.refusal.details) == (
        "task_not_found",
        {"key": "NOPE-9"},
    )
    carried = await tasks_service.get_task(db_session, "UI-1")
    assert (carried.key, carried.previous_keys) == ("TRK-2", ["UI-1"])
    [entry] = await _moved_entries(db_session, carried)
    assert entry.no == 2 and entry.payload["reason"] == "Репозиторий один"
    # Уже лежавшая в TRK задача не получила ни записи, ни версии.
    assert await _moved_entries(db_session, task) == []


async def test_new_numbers_follow_the_list_order_and_repeats_answer_already(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    """UI-3, UI-1, UI-2 → TRK-2, TRK-3, TRK-4; повтор того же ключа — `already`."""
    await _ui_with_tasks(db_session, main_actor, 3)

    outcomes = await tasks_service.move_tasks(
        db_session,
        ["UI-3", "UI-1", "UI-2", "UI-3"],
        actor=main_actor,
        project_key="TRK",
        reason="r",
    )

    assert [(item.key, item.to_key) for item in outcomes if isinstance(item, TaskMoved)] == [
        ("UI-3", "TRK-2"),
        ("UI-1", "TRK-3"),
        ("UI-2", "TRK-4"),
    ]
    assert outcomes[3] == TaskAlreadyThere(key="UI-3", to_key="TRK-2")
    assert project.last_task_number == 4


async def test_a_refused_task_leaves_the_rest_moved(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    """Задача архивного исходного проекта — `error/project_archived`, соседи переносятся.

    Отказ стоит между двумя переносами: точка сохранения откатывает только его, и
    следующий перенос после отката идёт в тот же проект без ошибки сессии.
    """
    ui = await _ui_with_tasks(db_session, main_actor, 1)
    ops = await projects_service.create_project(db_session, actor=main_actor, key="OPS", title="O")
    await tasks_service.create_task(
        db_session, actor=main_actor, project=ops, title="Архивная", description="d"
    )
    await projects_service.archive_project(db_session, ops, actor=main_actor, reason="Архив")

    outcomes = await tasks_service.move_tasks(
        db_session, ["TRK-1", "OPS-1", "UI-1"], actor=main_actor, project_key="UI", reason="r"
    )

    first, refused, last = outcomes
    assert first == TaskMoved(key="TRK-1", from_key="TRK-1", to_key="UI-2", no=2)
    assert isinstance(refused, TaskMoveRefused)
    assert (refused.refusal.code, refused.refusal.details["key"]) == ("project_archived", "OPS")
    assert last == TaskAlreadyThere(key="UI-1", to_key="UI-1")
    still = await tasks_service.get_task(db_session, "OPS-1")
    assert still.key == "OPS-1" and await _moved_entries(db_session, still) == []
    assert ui.last_task_number == 2


# --- Отказы всего вызова -------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, MAX_MOVE_KEYS + 1])
async def test_a_list_out_of_range_is_refused_before_any_move(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task, count: int
) -> None:
    ui = await _ui_with_tasks(db_session, main_actor, 0)
    keys = ["TRK-1"] * count

    with pytest.raises(TaskMoveBatchSizeInvalidError) as error:
        await tasks_service.move_tasks(
            db_session, keys, actor=main_actor, project_key="UI", reason="r"
        )

    assert error.value.details == {"tasks": count, "min": 1, "max": MAX_MOVE_KEYS}
    assert (task.key, ui.last_task_number) == ("TRK-1", 0)


async def test_an_archived_target_refuses_the_whole_call(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await _ui_with_tasks(db_session, main_actor, 0)
    await projects_service.archive_project(db_session, ui, actor=main_actor, reason="Архив")

    with pytest.raises(ProjectArchivedError) as error:
        await tasks_service.move_tasks(
            db_session, ["TRK-1"], actor=main_actor, project_key="UI", reason="r"
        )

    assert error.value.details["key"] == "UI"
    assert await _moved_entries(db_session, task) == []


async def test_scope_reason_and_unknown_project_refuse_the_whole_call(
    db_session: AsyncSession, main_actor: Actor, task_actor: Actor, project: Project, task: Task
) -> None:
    await _ui_with_tasks(db_session, main_actor, 0)

    with pytest.raises(PermissionDeniedError):
        await tasks_service.move_tasks(
            db_session, ["TRK-1"], actor=task_actor, project_key="UI", reason="r"
        )
    with pytest.raises(TaskMoveReasonRequiredError) as blank:
        await tasks_service.move_tasks(
            db_session, ["TRK-1"], actor=main_actor, project_key="UI", reason=" "
        )
    with pytest.raises(ProjectNotFoundError):
        await tasks_service.move_tasks(
            db_session, ["TRK-1"], actor=main_actor, project_key="NOPE", reason="r"
        )

    assert blank.value.details == {}
    assert task.key == "TRK-1"


# --- REST ----------------------------------------------------------------------------------


async def test_rest_batch_answers_per_key_and_refuses_a_long_list(
    auth_client: AsyncClient,
) -> None:
    for key in ("TRK", "UI"):
        created = await auth_client.post("/api/v1/projects", json={"key": key, "title": key})
        assert created.status_code == 201, created.text
    for project in ("UI", "TRK"):
        created = await auth_client.post(
            "/api/v1/tasks", json={"project": project, "title": "Задача", "description": "d"}
        )
        assert created.status_code == 201, created.text

    moved = await auth_client.post(
        MOVE_BATCH, json={"keys": ["UI-1", "TRK-1", "NOPE-1"], "project": "TRK", "reason": "r"}
    )
    too_long = await auth_client.post(
        MOVE_BATCH, json={"keys": ["UI-1"] * (MAX_MOVE_KEYS + 1), "project": "TRK", "reason": "r"}
    )
    empty = await auth_client.post(MOVE_BATCH, json={"keys": [], "project": "TRK", "reason": "r"})
    read = await auth_client.get("/api/v1/tasks/UI-1")

    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["results"] == [
        {"key": "UI-1", "outcome": "moved", "from_key": "UI-1", "to_key": "TRK-2", "no": 2},
        {"key": "TRK-1", "outcome": "already", "to_key": "TRK-1"},
        {
            "key": "NOPE-1",
            "outcome": "error",
            "code": "task_not_found",
            "message": "Task not found",
            "details": {"key": "NOPE-1"},
        },
    ]
    for refused in (too_long, empty):
        assert (refused.status_code, refused.json()["error"]["code"]) == (
            422,
            "task_move_batch_size_invalid",
        )
    assert read.json()["data"]["task"]["key"] == "TRK-2"


# --- MCP -----------------------------------------------------------------------------------


async def test_mcp_moves_a_list_and_keeps_the_single_answer(
    mcp_session: Connect, main_secret: str, project: Project, task: Task
) -> None:
    async with mcp_session(main_secret) as session:
        await call(session, "create_project", key="UI", title="Интерфейс")
        await call(session, "create_task", project="UI", title="Экран", description="d")
        batch = await call(
            session, "move_task", key=["UI-1", "TRK-1", "NOPE-1"], project="TRK", reason="r"
        )
        single = await call(session, "move_task", key="TRK-2", project="UI", reason="Назад")
        one = await call(session, "move_task", key=["UI-1"], project="UI", reason="r")
        too_long = await refuse(
            session, "move_task", key=["UI-1"] * (MAX_MOVE_KEYS + 1), project="TRK", reason="r"
        )
        entries = await call(session, "read_entries", key="UI-1", types=["moved"])

    assert batch == {
        "results": [
            {"key": "UI-1", "outcome": "moved", "from_key": "UI-1", "to_key": "TRK-2", "no": 2},
            {"key": "TRK-1", "outcome": "already", "to_key": "TRK-1"},
            {
                "key": "NOPE-1",
                "outcome": "error",
                "code": "task_not_found",
                "message": "Task not found",
                "details": {"key": "NOPE-1"},
            },
        ]
    }
    assert single == {"key": "UI-1", "previous_keys": ["TRK-2"], "version": 3, "no": 3}
    assert one == {"results": [{"key": "UI-1", "outcome": "already", "to_key": "UI-1"}]}
    assert "task_move_batch_size_invalid" in too_long
    assert [entry["payload"]["reason"] for entry in entries["items"]] == ["r", "Назад"]
