"""Архивный проект скрыт по умолчанию и виден по явному названию (TRK-160).

Правила — `CONCEPT.md`, 3.2 («Архивирование»), 3.6 и 4.4: архивный проект не показывают
список проектов и `bootstrap` без `include_archived`; его задачи не находит поиск, пока
отбор не назовёт их равенством или вхождением — проект в `project`, саму задачу в `key`,
её родителя в `parent` (`TRK-164#9`, `TRK-151#17`); его вопросы и замечания не попадают во
«входящую» без названного проекта, а вопросы — и в счётчик первого экрана. Лента и чтение
по ключу не скрывают ничего.

Мир теста: архивный `TRK` с задачами TRK-1 и TRK-2, живой `OPS` с OPS-1; TRK-2 — ребёнок
OPS-1. В TRK-1 и OPS-1 по открытому вопросу владельцу и по замечанию.
"""

from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.case import EntryType
from app.domain.search import Operator
from app.services import case as case_service
from app.services import journal as journal_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.search import StructuredTerm
from conftest import Connect, call


@dataclass(frozen=True, slots=True)
class World:
    archived: Project
    live: Project
    frozen: Task
    child: Task
    outsider: Task


@pytest.fixture
async def world(db_session: AsyncSession, project: Project, task: Task, main_actor: Actor) -> World:
    live = await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Живой"
    )
    outsider = await tasks_service.create_task(
        db_session, actor=main_actor, project=live, title="Программа", description="Родитель"
    )
    child = await tasks_service.create_task(
        db_session,
        actor=main_actor,
        project=project,
        title="Ребёнок",
        description="Ребёнок программы",
    )
    await links_service.add_link(db_session, outsider, child, actor=main_actor, kind="parent")
    for item in (task, outsider):
        await case_service.ask(
            db_session, item, actor=main_actor, addressees=["owner"], title="Как?", blocking=True
        )
        await case_service.add_entry(
            db_session, item, actor=main_actor, type=EntryType.REMARK, title="Замечание"
        )
    return World(archived=project, live=live, frozen=task, child=child, outsider=outsider)


async def _archive(session: AsyncSession, world: World, actor: Actor) -> None:
    await projects_service.archive_project(session, world.archived, actor=actor, reason="Заброшен")


async def _keys(session: AsyncSession, actor: Actor, query: str | None = None) -> list[str]:
    found = await search_service.search_tasks(session, actor=actor, query=query)
    return [item.task.key for item in found.page.items]


# --- Список проектов ------------------------------------------------------------------


async def test_list_projects_hides_archived_unless_asked(
    db_session: AsyncSession, world: World, main_actor: Actor, task_actor: Actor
) -> None:
    """Обзорная проверка 1: без `include_archived` архивного нет, с ним — есть; по ключу
    он читается."""
    await _archive(db_session, world, main_actor)

    hidden = await projects_service.list_projects(db_session, actor=task_actor)
    shown = await projects_service.list_projects(
        db_session, actor=task_actor, include_archived=True
    )
    card = await projects_service.read_project(db_session, "trk", actor=task_actor)

    assert [item.key for item in hidden.items] == ["OPS"]
    # Порядок списка — время заведения, а оба проекта заведены одной транзакцией теста.
    assert sorted(item.key for item in shown.items) == ["OPS", "TRK"]
    assert card.archived_at is not None


# --- Поиск ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (None, ["OPS-1"]),
        ("status: backlog", ["OPS-1"]),
        ("project: TRK", ["TRK-1", "TRK-2"]),
        ("project: in TRK, OPS", ["OPS-1", "TRK-1", "TRK-2"]),
        ("project: != OPS", []),
        ("key: TRK-1", ["TRK-1"]),
        ("key: in TRK-1, OPS-1", ["OPS-1", "TRK-1"]),
        ("key: != OPS-1", []),
        ("parent: OPS-1", ["TRK-2"]),
        ("parent: empty()", ["OPS-1"]),
        # Названное в одной ветке `or` не открывает архив остальным: TRK-2 в backlog, но
        # не названа.
        ("key: TRK-1 or status: backlog", ["OPS-1", "TRK-1"]),
    ],
)
async def test_search_finds_archived_tasks_only_by_name(
    db_session: AsyncSession,
    world: World,
    main_actor: Actor,
    task_actor: Actor,
    query: str | None,
    expected: list[str],
) -> None:
    """Обзорная проверка 2: без названия архивных задач нет, с `project:`, `key:` и
    `parent:` — есть."""
    await _archive(db_session, world, main_actor)

    assert await _keys(db_session, task_actor, query) == expected


async def test_structured_filter_and_total_follow_the_same_rule(
    db_session: AsyncSession, world: World, main_actor: Actor, task_actor: Actor
) -> None:
    await _archive(db_session, world, main_actor)

    everything = await search_service.search_tasks(db_session, actor=task_actor, with_total=True)
    named = await search_service.search_tasks(
        db_session,
        actor=task_actor,
        structured=[StructuredTerm(name="project", values=["TRK"])],
        with_total=True,
    )
    negated = await search_service.search_tasks(
        db_session,
        actor=task_actor,
        structured=[StructuredTerm(name="key", values=["TRK-1"], operator=Operator.NE)],
    )

    assert ([i.task.key for i in everything.page.items], everything.page.total) == (["OPS-1"], 1)
    assert ([i.task.key for i in named.page.items], named.page.total) == (["TRK-1", "TRK-2"], 2)
    assert [i.task.key for i in negated.page.items] == ["OPS-1"]


async def test_restore_returns_the_tasks_to_search(
    db_session: AsyncSession, world: World, main_actor: Actor, task_actor: Actor
) -> None:
    await _archive(db_session, world, main_actor)
    await projects_service.restore_project(
        db_session, world.archived, actor=main_actor, reason="Снова"
    )

    assert await _keys(db_session, task_actor) == ["OPS-1", "TRK-1", "TRK-2"]


# --- Входящая и счётчик ---------------------------------------------------------------


async def test_inbox_and_the_counter_leave_out_archived_projects(
    db_session: AsyncSession, world: World, main_actor: Actor, task_actor: Actor, owner: Participant
) -> None:
    """Обзорная проверка 2: вопросы и замечания архивного проекта — только по названию,
    счётчик уменьшается на его вопросы."""
    before = await case_service.count_open_questions(db_session, participant=owner)
    await _archive(db_session, world, main_actor)

    questions = await case_service.list_questions(db_session, actor=task_actor)
    named_questions = await case_service.list_questions(
        db_session, actor=task_actor, project=world.archived
    )
    remarks = await case_service.list_remarks(db_session, actor=task_actor)
    named_remarks = await case_service.list_remarks(
        db_session, actor=task_actor, project=world.archived
    )
    history = await case_service.list_questions(db_session, actor=task_actor, open_only=False)
    after = await case_service.count_open_questions(db_session, participant=owner)

    assert [item.task_key for item in questions.items] == ["OPS-1"]
    assert [item.task_key for item in named_questions.items] == ["TRK-1"]
    assert [item.task_key for item in remarks.items] == ["OPS-1"]
    assert [item.task_key for item in named_remarks.items] == ["TRK-1"]
    assert [item.task_key for item in history.items] == ["OPS-1"]
    assert (before, after) == (2, 1)


# --- Лента ----------------------------------------------------------------------------


async def test_the_journal_still_carries_the_archived_project(
    db_session: AsyncSession, world: World, main_actor: Actor, task_actor: Actor
) -> None:
    """Обзорная проверка 3: лента без фильтра и с фильтром по задаче отдаёт архив."""
    start = await EntryRepository(db_session).latest_seq()
    await _archive(db_session, world, main_actor)

    tail = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session),
        after=start,
    )
    frozen = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, task=["TRK-1"]),
        after=0,
    )

    assert [(i.entry.type, i.project_key) for i in tail.items] == [(EntryType.ARCHIVED, "TRK")]
    assert {i.task_key for i in frozen.items} == {"TRK-1"}
    assert EntryType.QUESTION in {i.entry.type for i in frozen.items}


# --- REST -----------------------------------------------------------------------------


async def test_rest_hides_the_archive_by_default(auth_client: AsyncClient, world: World) -> None:
    """Обзорные проверки 1–3 через REST."""
    before = await auth_client.get("/api/v1/bootstrap")
    archived = await auth_client.post("/api/v1/projects/TRK/archive", json={"reason": "Заброшен"})
    assert archived.status_code == 200, archived.text

    def keys(response, field: str = "key") -> list[str]:
        assert response.status_code == 200, response.text
        return [item[field] for item in response.json()["data"]]

    projects = await auth_client.get("/api/v1/projects")
    all_projects = await auth_client.get("/api/v1/projects", params={"include_archived": True})
    card = await auth_client.get("/api/v1/projects/TRK")
    bootstrap = await auth_client.get("/api/v1/bootstrap")
    full_bootstrap = await auth_client.get("/api/v1/bootstrap", params={"include_archived": True})
    tasks = await auth_client.get("/api/v1/tasks")
    by_project = await auth_client.get("/api/v1/tasks", params={"project": "TRK"})
    by_key = await auth_client.get("/api/v1/tasks", params={"query": "key: TRK-1"})
    by_parent = await auth_client.get("/api/v1/tasks", params={"parent": "OPS-1"})
    questions = await auth_client.get("/api/v1/questions")
    named_questions = await auth_client.get("/api/v1/questions", params={"project": "TRK"})
    remarks = await auth_client.get("/api/v1/remarks")
    named_remarks = await auth_client.get("/api/v1/remarks", params={"project": "TRK"})
    journal = await auth_client.get("/api/v1/journal", params={"task": "TRK-1"})

    assert keys(projects) == ["OPS"]
    assert sorted(keys(all_projects)) == ["OPS", "TRK"]
    assert card.json()["data"]["archived_at"] == archived.json()["data"]["archived_at"]
    assert [p["key"] for p in bootstrap.json()["data"]["projects"]] == ["OPS"]
    assert sorted(p["key"] for p in full_bootstrap.json()["data"]["projects"]) == ["OPS", "TRK"]
    assert before.json()["data"]["open_questions"] == 2
    assert bootstrap.json()["data"]["open_questions"] == 1
    assert full_bootstrap.json()["data"]["open_questions"] == 1
    assert (keys(tasks), tasks.json()["meta"]["total"]) == (["OPS-1"], 1)
    assert keys(by_project) == ["TRK-1", "TRK-2"]
    assert keys(by_key) == ["TRK-1"]
    assert keys(by_parent) == ["TRK-2"]
    assert keys(questions, "task_key") == ["OPS-1"]
    assert keys(named_questions, "task_key") == ["TRK-1"]
    assert keys(remarks, "task_key") == ["OPS-1"]
    assert keys(named_remarks, "task_key") == ["TRK-1"]
    assert set(keys(journal, "task_key")) == {"TRK-1"}


# --- MCP ------------------------------------------------------------------------------


async def test_mcp_hides_the_archive_by_default(
    mcp_session: Connect, task_secret: str, main_secret: str, world: World
) -> None:
    """Обзорные проверки 1–3 через MCP."""
    async with mcp_session(main_secret) as session:
        await call(session, "archive_project", key="TRK", reason="Заброшен")
    async with mcp_session(task_secret) as session:
        listed = await call(session, "list_projects")
        everything = await call(session, "list_projects", include_archived=True)
        card = await call(session, "get_project", key="TRK")
        found = await call(session, "search_tasks", fields=["key"])
        by_project = await call(session, "search_tasks", query="project: TRK", fields=["key"])
        by_key = await call(session, "search_tasks", key=["TRK-1"], fields=["key"])
        by_parent = await call(session, "search_tasks", parent=["OPS-1"], fields=["key"])
        tail = await call(session, "wait_journal", after=0, task="TRK-1")

    def keys(result: dict) -> list[str]:
        return [row["key"] for row in result["items"]]

    assert listed["items"] == [{"key": "OPS", "title": "Живой", "archived_at": None}]
    assert sorted((r["key"], r["archived_at"] is None) for r in everything["items"]) == [
        ("OPS", True),
        ("TRK", False),
    ]
    assert card["archived_at"] is not None
    assert keys(found) == ["OPS-1"]
    assert keys(by_project) == ["TRK-1", "TRK-2"]
    assert keys(by_key) == ["TRK-1"]
    assert keys(by_parent) == ["TRK-2"]
    assert tail["items"] and {item["task_key"] for item in tail["items"]} == {"TRK-1"}
