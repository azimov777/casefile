"""Архивирование и восстановление проекта (TRK-159): причина, записи, заморозка, оба интерфейса.

Правила — `CONCEPT.md`, 3.2 («Архивирование») и таблицы валидаций 3.2 и 3.3: причина
обязательна в обе стороны; архивный проект и его задачи заморожены для любых изменений
(`project_archived`), кроме восстановления и снятия связи (`TRK-164#9`, вариант C); чтение
работает; повторный архив — `project_archived`, восстановление живого —
`project_not_archived`. Скрытие архивных из списков и поиска без `project:` — TRK-160,
здесь не проверяется.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.case import EntryType
from app.domain.errors import (
    ProjectArchivedError,
    ProjectNotArchivedError,
    ProjectReasonRequiredError,
)
from app.domain.tasks import TaskStatus
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import journal as journal_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.freeze import UNFROZEN_ENTRY_TYPES
from app.services.tasks import TaskChanges
from conftest import Connect, call, refuse

ARCHIVE = "/api/v1/projects/{key}/archive"
RESTORE = "/api/v1/projects/{key}/restore"


async def _second_task(session: AsyncSession, actor: Actor, project: Project) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        project=project,
        title="Вторая задача",
        description="Для связей",
        assignee="owner",
    )


async def _live_project(session: AsyncSession, actor: Actor) -> Project:
    return await projects_service.create_project(session, actor=actor, key="OPS", title="Живой")


async def _archive(session: AsyncSession, project: Project, actor: Actor) -> None:
    await projects_service.archive_project(session, project, actor=actor, reason="Заброшен")


# --- Причина и записи -------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_archiving_without_a_reason_is_refused(
    db_session: AsyncSession, project: Project, main_actor: Actor, reason: str | None
) -> None:
    """Обзорная проверка 1: архив без причины — отказ, проект остаётся живым."""
    with pytest.raises(ProjectReasonRequiredError) as error:
        await projects_service.archive_project(db_session, project, actor=main_actor, reason=reason)

    assert error.value.details == {"key": "TRK", "action": "archive"}
    assert project.archived_at is None


async def test_archiving_files_an_archived_entry_with_the_reason(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor
) -> None:
    """Обзорная проверка 2: `archived` с причиной в деле проекта; задачи не трогаются."""
    status_before = task.status

    entry = await projects_service.archive_project(
        db_session, project, actor=main_actor, reason="  Репозиторий заброшен  "
    )

    assert entry.type is EntryType.ARCHIVED
    assert (entry.project_id, entry.task_id) == (project.id, None)
    assert entry.title == "Project archived"
    assert entry.payload == {"reason": "Репозиторий заброшен"}
    assert project.archived_at == entry.created_at
    await db_session.refresh(task)
    assert task.status is status_before


async def test_restoring_files_a_restored_entry_and_clears_the_time(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    await _archive(db_session, project, main_actor)

    with pytest.raises(ProjectReasonRequiredError):
        await projects_service.restore_project(db_session, project, actor=main_actor, reason=" ")
    entry = await projects_service.restore_project(
        db_session, project, actor=main_actor, reason="Вернулись к работе"
    )

    assert entry.type is EntryType.RESTORED
    assert entry.payload == {"reason": "Вернулись к работе"}
    assert project.archived_at is None


async def test_archive_and_restore_need_the_main_set(
    db_session: AsyncSession, project: Project, main_actor: Actor, task_actor: Actor
) -> None:
    with pytest.raises(PermissionDeniedError):
        await projects_service.archive_project(db_session, project, actor=task_actor, reason="x")
    await _archive(db_session, project, main_actor)
    with pytest.raises(PermissionDeniedError):
        await projects_service.restore_project(db_session, project, actor=task_actor, reason="x")


async def test_archiving_twice_and_restoring_an_active_project_are_refused(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Обзорная проверка 1: повторный архив — `project_archived`, восстановление живого —
    `project_not_archived`."""
    with pytest.raises(ProjectNotArchivedError):
        await projects_service.restore_project(db_session, project, actor=main_actor, reason="x")

    await _archive(db_session, project, main_actor)
    with pytest.raises(ProjectArchivedError) as error:
        await projects_service.archive_project(db_session, project, actor=main_actor, reason="y")

    assert error.value.details["key"] == "TRK"
    page = await EntryRepository(db_session).list_project_page(
        project.id, types=[EntryType.ARCHIVED], limit=10
    )
    assert len(page.items) == 1


async def test_the_archived_entry_reaches_the_journal(
    db_session: AsyncSession, project: Project, main_actor: Actor, task_actor: Actor
) -> None:
    """Обзорная проверка 2: записи архива приходят в ленту с ключом проекта."""
    start = await EntryRepository(db_session).latest_seq()
    await _archive(db_session, project, main_actor)
    await projects_service.restore_project(db_session, project, actor=main_actor, reason="Снова")

    page = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, project="TRK"),
        after=start,
    )

    assert [(i.entry.type, i.project_key, i.task_key) for i in page.items] == [
        (EntryType.ARCHIVED, "TRK", None),
        (EntryType.RESTORED, "TRK", None),
    ]


# --- Заморозка --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scene:
    """Всё, над чем пробуются изменения: архивный проект, две его задачи и задача живого
    проекта — чтобы новая связь снаружи тоже была изменением, а не подготовкой."""

    project: Project
    task: Task
    other: Task
    outsider: Task


type Change = Callable[[AsyncSession, Scene, Actor], Awaitable[Any]]


async def _create_task(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await tasks_service.create_task(
        s, actor=a, project=x.project, title="Новая", description="x"
    )


async def _add_entry(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await case_service.add_entry(s, x.task, actor=a, type=EntryType.NOTE, title="Заметка")


async def _add_summary(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await case_service.add_summary(
        s, x.task, actor=a, done="Сделано", remaining="Ничего", blockers="Ничего", next_step="-"
    )


async def _ask(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await case_service.ask(
        s, x.task, actor=a, addressees=["owner"], title="Вопрос?", blocking=False
    )


async def _add_project_entry(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await case_service.append_project_entry(
        s, x.project, actor=a, type=EntryType.DECISION, title="Решение"
    )


async def _update_task(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await tasks_service.update_task(s, x.task, actor=a, changes=TaskChanges(title="Другое"))


async def _assign(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await tasks_service.update_task(s, x.task, actor=a, changes=TaskChanges(assignee=None))


async def _transition(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await tasks_service.transition_task(s, x.task, actor=a, to=TaskStatus.OPEN)


async def _link(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await links_service.add_link(s, x.task, x.other, actor=a, kind="relates")


async def _link_from_outside(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await links_service.add_link(s, x.outsider, x.task, actor=a, kind="blocked_by")


async def _set_attribute(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await attributes_service.set_attribute(s, x.project, actor=a, name="repo", value="x")


async def _remove_attribute(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await attributes_service.remove_attribute(
        s, x.project, actor=a, name="branch", reason="x"
    )


async def _update_project(s: AsyncSession, x: Scene, a: Actor) -> Any:
    return await projects_service.update_project(s, x.project, actor=a, title="Новое название")


#: Порядок — тот, в котором они проходят после восстановления: правка названия задачи
#: возможна только в `backlog`, поэтому она раньше перехода.
CHANGES: dict[str, Change] = {
    "create_task": _create_task,
    "add_entry": _add_entry,
    "add_summary": _add_summary,
    "ask": _ask,
    "add_project_entry": _add_project_entry,
    "update_task": _update_task,
    "update_task_assignee": _assign,
    "transition": _transition,
    "link": _link,
    "link_from_a_live_project": _link_from_outside,
    "set_attribute": _set_attribute,
    "remove_attribute": _remove_attribute,
    "update_project": _update_project,
}


@pytest.fixture
async def scene(db_session: AsyncSession, project: Project, task: Task, main_actor: Actor) -> Scene:
    """Архивный проект `TRK` с двумя задачами и атрибутом и живая задача `OPS-1`."""
    other = await _second_task(db_session, main_actor, project)
    live = await _live_project(db_session, main_actor)
    outsider = await _second_task(db_session, main_actor, live)
    await attributes_service.set_attribute(
        db_session, project, actor=main_actor, name="branch", value="main"
    )
    await _archive(db_session, project, main_actor)
    return Scene(project=project, task=task, other=other, outsider=outsider)


@pytest.mark.parametrize("change", CHANGES.values(), ids=CHANGES.keys())
async def test_every_change_in_an_archived_project_is_refused(
    db_session: AsyncSession, scene: Scene, main_actor: Actor, change: Change
) -> None:
    """Обзорная проверка 1: после архива любое изменение отвечает `project_archived`."""
    seq = await EntryRepository(db_session).latest_seq()

    with pytest.raises(ProjectArchivedError) as error:
        await change(db_session, scene, main_actor)

    assert error.value.details["key"] == "TRK"
    archived_at = scene.project.archived_at
    assert archived_at is not None
    assert error.value.details["archived_at"] == archived_at.isoformat()
    # Ни одной записи в ленте: отказ случился до подшивки.
    assert await EntryRepository(db_session).latest_seq() == seq


async def test_the_archive_is_named_before_the_scenario_rules(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor
) -> None:
    """Проверка стоит первым шагом: переход с открытым блокером отвечает архивом, а не
    `task_blocked`, правка раздела вне `backlog` — архивом, а не `task_field_locked`."""
    blocker = await _second_task(db_session, main_actor, project)
    await tasks_service.transition_task(db_session, task, actor=main_actor, to=TaskStatus.OPEN)
    await links_service.add_link(db_session, task, blocker, actor=main_actor, kind="blocked_by")
    await _archive(db_session, project, main_actor)

    with pytest.raises(ProjectArchivedError):
        await tasks_service.transition_task(
            db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
        )
    with pytest.raises(ProjectArchivedError):
        await tasks_service.update_task(
            db_session, task, actor=main_actor, changes=TaskChanges(goal="Другая цель")
        )


async def test_the_case_append_guards_scenarios_that_check_nothing_first(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor
) -> None:
    """Гарантия в подшивке: служебную запись в дело задачи архивного проекта не подшить,
    даже минуя первый шаг сценария."""
    await _archive(db_session, project, main_actor)

    with pytest.raises(ProjectArchivedError):
        await case_service.record_created(db_session, task, actor=main_actor)


def test_only_the_archive_itself_and_link_removal_pass_the_freeze() -> None:
    expected = {EntryType.ARCHIVED, EntryType.RESTORED, EntryType.LINK_REMOVED}
    assert expected == UNFROZEN_ENTRY_TYPES


async def test_reads_work_in_an_archived_project(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor, task_actor: Actor
) -> None:
    """Обзорная проверка 1: карточка и дело задачи, проект, его дело и поиск читаются."""
    await _archive(db_session, project, main_actor)

    package = await tasks_service.read_task_package(db_session, "TRK-1", actor=task_actor)
    entries = await case_service.list_entries(db_session, task, actor=task_actor)
    card = await projects_service.read_project(db_session, "trk", actor=task_actor)
    project_entries = await case_service.list_project_entries(db_session, project, actor=task_actor)
    found = await search_service.search_tasks(db_session, actor=task_actor, query="project: TRK")

    assert package.task.key == "TRK-1"
    assert entries.items[0].type is EntryType.CREATED
    assert card.archived_at is not None
    assert project_entries.items[-1].type is EntryType.ARCHIVED
    assert [item.task.key for item in found.page.items] == ["TRK-1"]


async def test_unlink_with_an_archived_task_is_allowed_and_filed_in_both_cases(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor
) -> None:
    """`TRK-164#9`, вариант C: связь с задачей архивного проекта снимается без
    восстановления, `link_removed` ложится и в дело замороженной задачи."""
    live = await _live_project(db_session, main_actor)
    outsider = await _second_task(db_session, main_actor, live)
    await links_service.add_link(db_session, outsider, task, actor=main_actor, kind="blocked_by")
    await _archive(db_session, project, main_actor)
    assert await links_service.open_blockers(db_session, outsider) == ["TRK-1"]

    await links_service.remove_link(db_session, task, outsider, actor=main_actor, kind="blocks")

    assert await links_service.open_blockers(db_session, outsider) == []
    frozen = await EntryRepository(db_session).list_page(
        task.id, types=[EntryType.LINK_REMOVED], limit=10
    )
    assert [entry.payload for entry in frozen.items] == [{"kind": "blocks", "other": "OPS-1"}]
    # Новая связь с той же задачей — снова отказ.
    with pytest.raises(ProjectArchivedError):
        await links_service.add_link(
            db_session, outsider, task, actor=main_actor, kind="blocked_by"
        )


async def test_restore_allows_every_change_again(
    db_session: AsyncSession, scene: Scene, main_actor: Actor
) -> None:
    """Обзорная проверка 1: после `restore` с причиной всё снова разрешено."""
    await projects_service.restore_project(
        db_session, scene.project, actor=main_actor, reason="Снова"
    )

    for change in CHANGES.values():
        await change(db_session, scene, main_actor)


# --- REST -------------------------------------------------------------------------------


async def test_rest_archives_freezes_and_restores(
    auth_client: AsyncClient, project: Project, task: Task
) -> None:
    missing = await auth_client.post(ARCHIVE.format(key="TRK"), json={})
    blank = await auth_client.post(ARCHIVE.format(key="TRK"), json={"reason": "  "})
    assert missing.status_code == 422
    assert (blank.status_code, blank.json()["error"]["code"]) == (422, "project_reason_required")

    archived = await auth_client.post(ARCHIVE.format(key="trk"), json={"reason": "Заброшен"})
    assert archived.status_code == 200, archived.text
    assert archived.json()["data"]["archived_at"] is not None

    refusals = [
        await auth_client.post(
            "/api/v1/tasks", json={"project": "TRK", "title": "t", "description": "d"}
        ),
        await auth_client.post(
            "/api/v1/tasks/TRK-1/entries", json={"type": "note", "title": "Заметка"}
        ),
        await auth_client.post(
            "/api/v1/projects/TRK/entries", json={"type": "note", "title": "Заметка"}
        ),
        await auth_client.post("/api/v1/tasks/TRK-1/transition", json={"to": "open"}),
        await auth_client.patch("/api/v1/tasks/TRK-1", json={"title": "Другое"}),
        await auth_client.put("/api/v1/projects/TRK/attributes/repo", json={"value": "x"}),
        await auth_client.patch("/api/v1/projects/TRK", json={"title": "Другое"}),
        await auth_client.post(ARCHIVE.format(key="TRK"), json={"reason": "Ещё раз"}),
    ]
    assert [(r.status_code, r.json()["error"]["code"]) for r in refusals] == [
        (409, "project_archived")
    ] * len(refusals)

    assert (await auth_client.get("/api/v1/tasks/TRK-1")).status_code == 200
    assert (await auth_client.get("/api/v1/tasks/TRK-1/entries")).status_code == 200
    card = await auth_client.get("/api/v1/projects/TRK")
    assert card.json()["data"]["archived_at"] == archived.json()["data"]["archived_at"]
    entries = await auth_client.get("/api/v1/projects/TRK/entries", params={"types": ["archived"]})
    assert [(e["type"], e["payload"], e["project_key"]) for e in entries.json()["data"]] == [
        ("archived", {"reason": "Заброшен"}, "TRK")
    ]

    restored = await auth_client.post(RESTORE.format(key="TRK"), json={"reason": "Снова"})
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["archived_at"] is None
    again = await auth_client.post(RESTORE.format(key="TRK"), json={"reason": "Снова"})
    assert (again.status_code, again.json()["error"]["code"]) == (409, "project_not_archived")
    note = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries", json={"type": "note", "title": "Заметка"}
    )
    assert note.status_code == 201, note.text


async def test_rest_archive_needs_the_main_set(
    client: AsyncClient, task_secret: str, project: Project
) -> None:
    client.headers["Authorization"] = f"Bearer {task_secret}"
    response = await client.post(ARCHIVE.format(key="TRK"), json={"reason": "x"})
    assert (response.status_code, response.json()["error"]["code"]) == (403, "permission_denied")


async def test_the_task_card_carries_the_project_archive_time(
    auth_client: AsyncClient, project: Project, task: Task
) -> None:
    """Обзорная проверка 1: карточка задачи несёт `project.archived_at` (TRK-167)."""
    active = await auth_client.get("/api/v1/tasks/TRK-1")
    assert active.json()["data"]["task"]["project"]["archived_at"] is None

    archived = await auth_client.post(ARCHIVE.format(key="TRK"), json={"reason": "Заброшен"})
    assert archived.status_code == 200, archived.text
    archived_at = archived.json()["data"]["archived_at"]
    card = await auth_client.get("/api/v1/tasks/TRK-1")

    assert archived_at is not None
    assert card.json()["data"]["task"]["project"]["archived_at"] == archived_at


# --- MCP --------------------------------------------------------------------------------


async def test_mcp_archive_tools_are_only_in_the_main_set(
    mcp_session: Connect, main_secret: str, task_secret: str
) -> None:
    """Обзорная проверка 4: `tools/list` токеном `main` показывает оба инструмента,
    токеном `task` — ни одного."""
    async with mcp_session(main_secret) as session:
        main_tools = {tool.name for tool in (await session.list_tools()).tools}
    async with mcp_session(task_secret) as session:
        task_tools = {tool.name for tool in (await session.list_tools()).tools}

    assert {"archive_project", "restore_project"} <= main_tools
    assert not {"archive_project", "restore_project"} & task_tools


async def test_mcp_archives_freezes_unlinks_and_restores(
    mcp_session: Connect, main_secret: str, project: Project, task: Task
) -> None:
    async with mcp_session(main_secret) as session:
        await call(session, "create_project", key="OPS", title="Живой")
        await call(session, "create_task", project="OPS", title="Снаружи", description="Ждёт TRK-1")
        await call(session, "link", key="OPS-1", kind="blocked_by", other="TRK-1")

        no_reason = await refuse(session, "archive_project", key="TRK", reason=" ")
        archived = await call(session, "archive_project", key="trk", reason="Заброшен")
        twice = await refuse(session, "archive_project", key="TRK", reason="Ещё")
        entry = await refuse(session, "add_entry", key="TRK-1", type="note", title="Заметка")
        created = await refuse(
            session, "create_task", project="TRK", title="Новая", description="x"
        )
        card = await call(session, "get_task", key="TRK-1")
        project_card = await call(session, "get_project", key="TRK")
        found = await call(session, "search_tasks", project=["TRK"], fields=["key"])
        unlinked = await call(session, "unlink", key="TRK-1", kind="blocks", other="OPS-1")
        restored = await call(session, "restore_project", key="TRK", reason="Снова")
        not_archived = await refuse(session, "restore_project", key="TRK", reason="Снова")
        note = await call(session, "add_entry", key="TRK-1", type="note", title="Заметка")

    assert "project_reason_required" in no_reason
    assert archived["key"] == "TRK" and archived["archived_at"] is not None
    assert "project_archived" in twice
    assert "project_archived" in entry
    assert "project_archived" in created
    assert card["task"]["key"] == "TRK-1"
    # Обзорная проверка 1 (TRK-167): архив виден в карточке задачи без `get_project`.
    assert card["task"]["project"]["archived_at"] == archived["archived_at"]
    assert project_card["archived_at"] == archived["archived_at"]
    assert (project_card["index"][-1]["type"], project_card["index"][-1]["facts"]) == (
        "archived",
        {"type": "archived"},
    )
    assert [row["key"] for row in found["items"]] == ["TRK-1"]
    assert unlinked is not None
    assert restored["archived_at"] is None and restored["no"] == archived["no"] + 1
    assert "project_not_archived" in not_archived
    assert note["no"] > 0


async def test_mcp_archive_is_refused_to_a_task_token(
    mcp_session: Connect, task_secret: str, main_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        refused = await session.call_tool("archive_project", {"key": "TRK", "reason": "x"})
    assert refused.is_error
