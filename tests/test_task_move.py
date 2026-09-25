"""Перенос задачи в другой проект (TRK-172): ключи, прежний ключ везде, запись `moved`, отказы.

Правила — `CONCEPT.md`, 3.3 («Перенос в другой проект»), 3.4 (запись `moved`), 4.4 (поиск
по прежнему ключу), решения `TRK-171#11`–`#22` и открытые места, решённые в TRK-172:
перенос в тот же проект — `task_already_in_project`; одновременные переносы идут по
одному через очередь изменений; прежние ключи едут в архиве переноса установки колонкой
задачи.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import AppError, PermissionDeniedError
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.authors import label_author
from app.domain.case import EntryType
from app.domain.errors import (
    ProjectArchivedError,
    TaskAlreadyInProjectError,
    TaskMoveReasonRequiredError,
    TaskVersionConflictError,
)
from app.domain.links import LinkKind
from app.domain.tasks import TaskStatus
from app.domain.tokens import TokenScope
from app.services import case as case_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from conftest import Connect, call, refuse

MOVE = "/api/v1/tasks/{key}/move"


async def _ui(session: AsyncSession, actor: Actor) -> Project:
    return await projects_service.create_project(session, actor=actor, key="UI", title="Интерфейс")


async def _new_task(session: AsyncSession, actor: Actor, project: Project, title: str) -> Task:
    return await tasks_service.create_task(
        session, actor=actor, project=project, title=title, description="Для переноса"
    )


# --- Ключи --------------------------------------------------------------------------------


async def test_a_move_gives_the_next_number_and_keeps_the_left_key(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    """TRK-1 → UI: следующий номер UI, прежний ключ в `previous_keys`, запись `moved`."""
    ui = await _ui(db_session, main_actor)
    await _new_task(db_session, main_actor, ui, "Уже в UI")
    version = task.version

    moved = await tasks_service.move_task(
        db_session, task, actor=main_actor, project=ui, reason="  Задача интерфейса  "
    )

    assert (task.key, task.project_id, task.previous_keys) == ("UI-2", ui.id, ["TRK-1"])
    assert task.version == version + 1
    assert moved.entry.type is EntryType.MOVED
    assert moved.entry.task_id == task.id
    assert moved.entry.title == "Moved: TRK-1 -> UI-2"
    assert moved.entry.payload == {
        "from_project": "TRK",
        "to_project": "UI",
        "from_key": "TRK-1",
        "to_key": "UI-2",
        "reason": "Задача интерфейса",
    }
    # Счётчик UI сдвинулся на выданный номер, TRK — нет: номер TRK-1 закреплён за задачей.
    assert (ui.last_task_number, project.last_task_number) == (2, 1)


async def test_the_previous_key_reads_the_task_and_is_never_handed_out_again(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    ui = await _ui(db_session, main_actor)
    await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason="r")

    assert await tasks_service.get_task(db_session, "trk-1") is task
    assert await tasks_service.get_task(db_session, "UI-1") is task
    fresh = await _new_task(db_session, main_actor, project, "Новая в TRK")
    assert fresh.key == "TRK-2"


async def test_returning_to_a_project_gives_back_the_key_it_had_there(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    """TRK-1 → UI-1 → OPS-1 → TRK: снова TRK-1, счётчик TRK не двигается (`TRK-171#9`, п. 2)."""
    ui = await _ui(db_session, main_actor)
    ops = await projects_service.create_project(db_session, actor=main_actor, key="OPS", title="O")

    await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason="1")
    await tasks_service.move_task(db_session, task, actor=main_actor, project=ops, reason="2")
    back = await tasks_service.move_task(
        db_session, task, actor=main_actor, project=project, reason="3"
    )

    assert task.key == "TRK-1"
    assert task.previous_keys == ["UI-1", "OPS-1"]
    assert project.last_task_number == 1
    assert back.entry.payload["to_key"] == "TRK-1"
    # И обратно в UI — снова UI-1, а TRK-1 встаёт в конец прежних.
    await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason="4")
    assert (task.key, task.previous_keys) == ("UI-1", ["OPS-1", "TRK-1"])
    assert ui.last_task_number == 1


async def test_a_closed_task_moves_and_keeps_its_status_links_and_case(
    db_session: AsyncSession, main_actor: Actor, task_actor: Actor, project: Project, task: Task
) -> None:
    """Статус не важен (`TRK-171#9`, п. 9); родство держится не на ключах (п. 3)."""
    ui = await _ui(db_session, main_actor)
    child = await tasks_service.create_task(
        db_session, actor=task_actor, project=project, title="Ребёнок", description="Остаётся"
    )
    await links_service.add_link(db_session, task, child, actor=task_actor, kind=LinkKind.PARENT)
    await tasks_service.transition_task(
        db_session, child, actor=task_actor, to=TaskStatus.CANCELLED, reason="Лишняя"
    )
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.CANCELLED, reason="Отменена"
    )
    entries_before = await case_service.case_index(db_session, task, actor=main_actor)

    await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason="r")

    assert task.status is TaskStatus.CANCELLED
    assert (child.key, child.project_id) == ("TRK-2", project.id)
    package = await tasks_service.read_task_package(db_session, "UI-1", actor=main_actor)
    assert [item.other.key for item in package.children] == ["TRK-2"]
    assert [item.no for item in package.index] == [
        *(item.no for item in entries_before),
        len(entries_before) + 1,
    ]
    parent = (await tasks_service.read_task_package(db_session, "TRK-2", actor=main_actor)).parent
    assert parent is not None and parent.other.key == "UI-1"


# --- Отказы -------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_a_move_without_a_reason_is_refused(
    db_session: AsyncSession, main_actor: Actor, task: Task, reason: str | None
) -> None:
    ui = await _ui(db_session, main_actor)
    with pytest.raises(TaskMoveReasonRequiredError) as error:
        await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason=reason)
    assert error.value.details == {"key": "TRK-1"}
    assert (task.key, task.previous_keys) == ("TRK-1", [])


async def test_a_move_into_its_own_project_is_refused(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    with pytest.raises(TaskAlreadyInProjectError) as error:
        await tasks_service.move_task(
            db_session, task, actor=main_actor, project=project, reason="r"
        )
    assert error.value.details == {"key": "TRK-1", "project": "TRK"}
    assert project.last_task_number == 1


async def test_a_task_token_does_not_move(
    db_session: AsyncSession, main_actor: Actor, task_actor: Actor, task: Task
) -> None:
    ui = await _ui(db_session, main_actor)
    with pytest.raises(PermissionDeniedError):
        await tasks_service.move_task(db_session, task, actor=task_actor, project=ui, reason="r")


@pytest.mark.parametrize("archived", ["source", "target"])
async def test_a_move_into_or_out_of_an_archived_project_is_refused(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task, archived: str
) -> None:
    """`TRK-171#9`, п. 10: ни в архивный проект, ни из него, и номер не сгорает."""
    ui = await _ui(db_session, main_actor)
    frozen = project if archived == "source" else ui
    await projects_service.archive_project(db_session, frozen, actor=main_actor, reason="Архив")

    with pytest.raises(ProjectArchivedError) as error:
        await tasks_service.move_task(db_session, task, actor=main_actor, project=ui, reason="r")

    assert error.value.details["key"] == frozen.key
    assert (task.key, ui.last_task_number) == ("TRK-1", 0)


async def test_a_stale_version_is_refused(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    ui = await _ui(db_session, main_actor)
    with pytest.raises(TaskVersionConflictError):
        await tasks_service.move_task(
            db_session,
            task,
            actor=main_actor,
            project=ui,
            reason="r",
            expected_version=task.version + 5,
        )


# --- Прежний ключ везде, где принимается ключ ----------------------------------------------


async def _moved_ui_task(client: AsyncClient) -> dict[str, Any]:
    """UI-1 с записью `#2`, ребёнок TRK-1, ссылка UI-1#2 в деле TRK-1 — и перенос в TRK.

    Та же расстановка, что в живой проверке задачи (UI-5): закрытая задача, ребёнок в
    другом проекте и ссылка на её запись в чужом деле.
    """
    for key, title in (("TRK", "Бэкенд"), ("UI", "Интерфейс")):
        created = await client.post("/api/v1/projects", json={"key": key, "title": title})
        assert created.status_code == 201, created.text
    for project, title in (("UI", "Экран"), ("TRK", "Ребёнок из TRK")):
        created = await client.post(
            "/api/v1/tasks", json={"project": project, "title": title, "description": "d"}
        )
        assert created.status_code == 201, created.text
    note = await client.post(
        "/api/v1/tasks/UI-1/entries", json={"type": "finding", "title": "Факт"}
    )
    assert note.json()["data"]["no"] == 2
    linked = await client.post(
        "/api/v1/tasks/UI-1/links", json={"kind": "parent", "other": "TRK-1"}
    )
    assert linked.status_code == 201, linked.text
    ref = await client.post(
        "/api/v1/tasks/TRK-1/entries",
        json={"type": "note", "title": "См. факт", "refs": ["UI-1#2"]},
    )
    assert ref.status_code == 201, ref.text
    # Закрыты оба: родитель закрывается только после ребёнка.
    for key in ("TRK-1", "UI-1"):
        closed = await client.post(
            f"/api/v1/tasks/{key}/transition", json={"to": "cancelled", "reason": "Закрыта"}
        )
        assert closed.status_code == 200, closed.text
    response = await client.post(
        MOVE.format(key="ui-1"), json={"project": "trk", "reason": "UI переезжает в TRK"}
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def test_rest_reads_writes_links_and_refs_by_the_previous_key(
    auth_client: AsyncClient,
) -> None:
    card = await _moved_ui_task(auth_client)
    assert (card["key"], card["previous_keys"], card["project"]["key"]) == (
        "TRK-2",
        ["UI-1"],
        "TRK",
    )
    assert card["status"] == "cancelled"

    read = await auth_client.get("/api/v1/tasks/UI-1")
    assert read.status_code == 200, read.text
    package = read.json()["data"]
    assert package["task"]["key"] == "TRK-2"
    assert package["task"]["previous_keys"] == ["UI-1"]
    assert [item["key"] for item in package["children"]] == ["TRK-1"]
    moved = package["index"][-1]
    assert moved["type"] == "moved"
    assert moved["facts"] == {"type": "moved", "from_key": "UI-1", "to_key": "TRK-2"}

    entry = await auth_client.get("/api/v1/tasks/UI-1/entries/2")
    assert entry.status_code == 200 and entry.json()["data"]["task_key"] == "TRK-2"
    full = await auth_client.get(f"/api/v1/tasks/UI-1/entries/{moved['no']}")
    assert full.json()["data"]["payload"] == {
        "from_project": "UI",
        "to_project": "TRK",
        "from_key": "UI-1",
        "to_key": "TRK-2",
        "reason": "UI переезжает в TRK",
    }

    added = await auth_client.post(
        "/api/v1/tasks/UI-1/entries",
        json={"type": "note", "title": "После переезда", "refs": ["UI-1#2", "UI-1", "TRK-2#2"]},
    )
    assert added.status_code == 201, added.text
    assert added.json()["data"]["task_key"] == "TRK-2"
    # Ссылки хранятся как написаны: записи неизменяемы, и текст не переписывается.
    assert added.json()["data"]["refs"] == ["UI-1#2", "UI-1", "TRK-2#2"]
    # Старая ссылка в чужом деле по-прежнему читается как была.
    foreign = await auth_client.get("/api/v1/tasks/TRK-1/entries/3")
    assert foreign.json()["data"]["refs"] == ["UI-1#2"]
    missing = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries",
        json={"type": "note", "title": "Нет такой", "refs": ["UI-1#99"]},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["details"]["fields"][0]["reason"] == "unknown_entry"

    other = await auth_client.post(
        "/api/v1/tasks", json={"project": "TRK", "title": "Соседка", "description": "d"}
    )
    other_key = other.json()["data"]["key"]
    linked = await auth_client.post(
        f"/api/v1/tasks/{other_key}/links", json={"kind": "relates", "other": "UI-1"}
    )
    assert linked.status_code == 201, linked.text
    unlinked = await auth_client.delete(f"/api/v1/tasks/UI-1/links/relates/{other_key}")
    assert unlinked.status_code == 204, unlinked.text


async def test_search_finds_the_task_and_its_children_by_the_previous_key(
    auth_client: AsyncClient,
) -> None:
    await _moved_ui_task(auth_client)

    by_key = await auth_client.get("/api/v1/tasks", params={"query": "key: UI-1"})
    by_list = await auth_client.get("/api/v1/tasks", params={"key": ["ui-1"]})
    children = await auth_client.get("/api/v1/tasks", params={"query": "parent: UI-1"})
    not_it = await auth_client.get(
        "/api/v1/tasks", params={"query": "project: TRK and key: != UI-1"}
    )

    assert [row["key"] for row in by_key.json()["data"]] == ["TRK-2"]
    assert by_key.json()["data"][0]["previous_keys"] == ["UI-1"]
    assert [row["key"] for row in by_list.json()["data"]] == ["TRK-2"]
    assert [row["key"] for row in children.json()["data"]] == ["TRK-1"]
    assert [row["key"] for row in not_it.json()["data"]] == ["TRK-1"]


async def test_a_new_task_in_the_old_project_does_not_get_the_moved_key(
    auth_client: AsyncClient,
) -> None:
    await _moved_ui_task(auth_client)
    created = await auth_client.post(
        "/api/v1/tasks", json={"project": "UI", "title": "Новая", "description": "d"}
    )
    assert created.json()["data"]["key"] == "UI-2"
    # UI-1 по-прежнему ведёт на перенесённую задачу, а не на новую.
    assert (await auth_client.get("/api/v1/tasks/UI-1")).json()["data"]["task"]["key"] == "TRK-2"
    # Обратный перенос возвращает задаче её ключ UI-1, а не UI-3.
    back = await auth_client.post(MOVE.format(key="TRK-2"), json={"project": "UI", "reason": "r"})
    assert back.status_code == 200, back.text
    assert (back.json()["data"]["key"], back.json()["data"]["previous_keys"]) == (
        "UI-1",
        ["TRK-2"],
    )


async def test_a_continuation_named_by_a_previous_key_stays_in_work(
    auth_client: AsyncClient,
) -> None:
    """`remarks_in_work` соединяет резолюцию с продолжением и по прежнему ключу."""
    await _moved_ui_task(auth_client)
    await auth_client.post(
        "/api/v1/tasks", json={"project": "UI", "title": "Продолжение", "description": "d"}
    )
    remark = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries", json={"type": "remark", "title": "Вышло не то"}
    )
    remark_no = remark.json()["data"]["no"]
    resolved = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries",
        json={
            "type": "resolution",
            "payload": {"remark_no": remark_no, "outcome": "accepted", "task": "UI-2"},
        },
    )
    assert resolved.status_code == 201, resolved.text
    moved = await auth_client.post(MOVE.format(key="UI-2"), json={"project": "TRK", "reason": "r"})
    assert moved.json()["data"]["key"] == "TRK-3"

    found = await auth_client.get("/api/v1/tasks", params={"query": "remarks_in_work: 1"})
    assert [row["key"] for row in found.json()["data"]] == ["TRK-1"]


async def test_rest_move_refusals(
    auth_client: AsyncClient, client: AsyncClient, task_secret: str, main_secret: str
) -> None:
    await _moved_ui_task(auth_client)

    same = await auth_client.post(MOVE.format(key="UI-1"), json={"project": "TRK", "reason": "r"})
    blank = await auth_client.post(MOVE.format(key="UI-1"), json={"project": "UI", "reason": " "})
    unknown = await auth_client.post(
        MOVE.format(key="UI-1"), json={"project": "NOPE", "reason": "r"}
    )
    archived = await auth_client.post("/api/v1/projects/UI/archive", json={"reason": "Пуст"})
    assert archived.status_code == 200, archived.text
    into_archive = await auth_client.post(
        MOVE.format(key="UI-1"), json={"project": "UI", "reason": "r"}
    )
    # Прежний ключ архивного проекта ведёт на задачу и из архива (`TRK-171#9`, п. 11).
    read = await auth_client.get("/api/v1/tasks/UI-1")
    client.headers["Authorization"] = f"Bearer {task_secret}"
    forbidden = await client.post(MOVE.format(key="UI-1"), json={"project": "UI", "reason": "r"})
    client.headers["Authorization"] = f"Bearer {main_secret}"

    assert (same.status_code, same.json()["error"]["code"]) == (409, "task_already_in_project")
    assert same.json()["error"]["details"] == {"key": "TRK-2", "project": "TRK"}
    assert (blank.status_code, blank.json()["error"]["code"]) == (422, "task_move_reason_required")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "project_not_found")
    assert (into_archive.status_code, into_archive.json()["error"]["code"]) == (
        409,
        "project_archived",
    )
    assert read.status_code == 200 and read.json()["data"]["task"]["key"] == "TRK-2"
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "permission_denied")


# --- MCP ----------------------------------------------------------------------------------


async def test_mcp_moves_only_with_the_main_set_and_answers_by_the_previous_key(
    mcp_session: Connect, main_secret: str, task_secret: str, project: Project, task: Task
) -> None:
    async with mcp_session(task_secret) as session:
        task_tools = {tool.name for tool in (await session.list_tools()).tools}
        forbidden = await refuse(session, "move_task", key="TRK-1", project="TRK", reason="r")
    async with mcp_session(main_secret) as session:
        await call(session, "create_project", key="UI", title="Интерфейс")
        no_reason = await refuse(session, "move_task", key="TRK-1", project="UI", reason=" ")
        same = await refuse(session, "move_task", key="TRK-1", project="TRK", reason="r")
        moved = await call(session, "move_task", key="trk-1", project="ui", reason="Интерфейс")
        card = await call(session, "get_task", key="TRK-1")
        filed = await call(session, "add_entry", key="TRK-1", type="note", title="По старому")
        referred = await call(
            session, "add_entry", key="UI-1", type="finding", title="Ссылка", refs=["TRK-1#1"]
        )
        found = await call(session, "search_tasks", key=["TRK-1"], fields=["previous_keys"])
        entries = await call(session, "read_entries", key="TRK-1", types=["moved"])
        back = await call(session, "move_task", key="UI-1", project="TRK", reason="Вернулась")

    assert "move_task" not in task_tools
    assert "permission_denied" in forbidden
    assert "task_move_reason_required" in no_reason
    assert "task_already_in_project" in same
    assert moved == {"key": "UI-1", "previous_keys": ["TRK-1"], "version": 2, "no": 2}
    assert card["task"]["key"] == "UI-1" and card["task"]["previous_keys"] == ["TRK-1"]
    assert card["index"][-1]["facts"] == {"type": "moved", "from_key": "TRK-1", "to_key": "UI-1"}
    assert filed["task_key"] == "UI-1"
    assert referred["task_key"] == "UI-1"
    assert found["items"] == [{"key": "UI-1", "previous_keys": ["TRK-1"]}]
    [entry] = entries["items"]
    assert entry["payload"]["reason"] == "Интерфейс"
    assert back == {"key": "TRK-1", "previous_keys": ["UI-1"], "version": 3, "no": 5}


# --- Одновременные переносы -----------------------------------------------------------------

MOVER = Actor(author=label_author("mover"), scope=TokenScope.MAIN)


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Сессии поверх движка прогона: каждая коммитит по-настоящему (`docs/notes/testing.md`)."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def racing(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[dict[str, str]]:
    """Три закоммиченных проекта с уникальными на прогон ключами и задача в первом."""
    mark = uuid.uuid4().hex[:5].upper()
    keys = {name: f"MV{name}{mark}" for name in ("A", "B", "C")}
    async with committing_sessions() as session:
        projects = [
            await projects_service.create_project(session, actor=MOVER, key=key, title=key)
            for key in keys.values()
        ]
        created = await _new_task(session, MOVER, projects[0], "Гонка переносов")
        await session.commit()
        ids = {"task": created.id, "projects": [item.id for item in projects]}
    try:
        yield keys
    finally:
        async with committing_sessions() as session:
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(
                text("DELETE FROM entries WHERE task_id = :task OR project_id = ANY(:projects)"),
                ids,
            )
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            await session.execute(text("DELETE FROM tasks WHERE id = :task"), {"task": ids["task"]})
            await session.execute(
                text("DELETE FROM projects WHERE id = ANY(:projects)"),
                {"projects": ids["projects"]},
            )
            await session.commit()


async def _move_in_own_session(
    sessions: async_sessionmaker[AsyncSession], key: str, target: str
) -> str:
    """Перенос в своей транзакции: задача читается до очереди, как её читает роутер."""
    async with sessions() as session:
        try:
            task = await tasks_service.get_task(session, key)
            project = await projects_service.get_project(session, target)
            moved = await tasks_service.move_task(
                session, task, actor=MOVER, project=project, reason=f"Перенос: {target}"
            )
            await session.commit()
            return moved.task.key
        except AppError as exc:
            await session.rollback()
            return exc.code


async def test_simultaneous_moves_go_one_by_one(
    committing_sessions: async_sessionmaker[AsyncSession], racing: dict[str, str]
) -> None:
    """Два переноса разом в разные проекты: оба проходят по очереди, ключи не теряются."""
    first = f"{racing['A']}-1"

    outcomes = await asyncio.gather(
        _move_in_own_session(committing_sessions, first, racing["B"]),
        _move_in_own_session(committing_sessions, first, racing["C"]),
    )

    assert sorted(outcomes) == sorted([f"{racing['B']}-1", f"{racing['C']}-1"])
    async with committing_sessions() as session:
        task = await tasks_service.get_task(session, first)
        moved = (
            await session.scalars(
                select(Entry).where(Entry.task_id == task.id, Entry.type == EntryType.MOVED)
            )
        ).all()
    assert task.key in outcomes
    assert task.previous_keys[0] == first and len(task.previous_keys) == 2
    assert sorted(entry.no for entry in moved) == [2, 3]


async def test_simultaneous_moves_into_one_project_let_one_through(
    committing_sessions: async_sessionmaker[AsyncSession], racing: dict[str, str]
) -> None:
    """Два переноса разом в один проект: второй видит задачу уже там, номер не сгорает."""
    first = f"{racing['A']}-1"

    outcomes = await asyncio.gather(
        _move_in_own_session(committing_sessions, first, racing["B"]),
        _move_in_own_session(committing_sessions, first, racing["B"]),
    )

    assert sorted(outcomes) == sorted([f"{racing['B']}-1", "task_already_in_project"])
    async with committing_sessions() as session:
        project = await projects_service.get_project(session, racing["B"])
    assert project.last_task_number == 1
