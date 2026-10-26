"""Доступ агента к проектам: перечень всех выборок и всех точек по адресу (TRK-751).

Слово владельца — TRK~28#6: на участнике-агенте стоит режим `all` / `except` / `only` и
список проектов. Закрытый проект исчезает у агента из каждой выборки и отвечает
`project_not_allowed` по адресу. Главный риск — забытая выборка, поэтому каждая из
перечня TRK-729#7 названа здесь своим тестом, а тест-перечень в конце сверяет саму
таблицу выборок с кодом.

Мир: `TRK` (фикстуры `project` и `task`) и `OPS`; в каждом по задаче с вопросом агенту
`scout`, замечанием, обсуждением, предупреждением, областью и файлом. Агент `scout` в
режиме `only` с проектом `OPS`: `TRK` ему закрыт.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.file import File
from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.project_scope import stamp
from app.db.repositories.participant_projects import ParticipantProjectRepository
from app.domain.participants import ParticipantKind
from app.domain.project_access import ProjectAccess, ProjectAccessMode
from app.domain.tokens import TokenKind
from app.services import area_links as area_links_service
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import files as files_service
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor
from conftest import Connect, call, make_task, refuse
from test_closing_warning import close_mixed, working

CLOSED = "TRK"
OPEN = "OPS"
#: Ключ закрытого проекта в любом написании: `TRK`, `TRK-1`, `TRK/core`, `TRK~1`.
CLOSED_MARK = re.compile(r"\bTRK\b|TRK-\d|TRK/|TRK~")


@dataclass(frozen=True, slots=True)
class World:
    closed: Project
    open: Project
    closed_task: Task
    open_task: Task
    closed_warning: Task
    open_warning: Task
    agent: Participant
    secret: str
    owner_secret: str


async def _agent_secret(session: AsyncSession, agent: Participant) -> str:
    issued = await tokens_service.issue_token(
        session, actor=TRACKER_ACTOR, participant=agent, name="scout key", kind=TokenKind.KEY
    )
    return issued.secret


async def _fill(
    session: AsyncSession, project: Project, task: Task, actor: Actor, agent: Participant
) -> None:
    """Вопрос агенту, замечание, обсуждение с вопросом человеку, файл."""
    await case_service.file_legacy_task_question(
        session, task, actor=actor, addressees=[agent.name], title="Как?", blocking=False
    )
    await case_service.add_entry(
        session, task, actor=actor, type="remark", title=f"Замечание {project.key}"
    )
    await discussions_service.ask_about_task(
        session, task, actor=actor, addressees=["owner"], title=f"Вопрос {project.key}"
    )
    await files_service.upload_file(
        session,
        actor=actor,
        project=project.key,
        name=f"{project.key.lower()}.txt",
        data=b"x",
        mime_type="text/plain",
    )


@pytest.fixture
async def world(
    db_session: AsyncSession,
    project: Project,
    task: Task,
    main_actor: Actor,
    main_secret: str,
) -> World:
    ops = await projects_service.create_project(
        db_session, actor=main_actor, key=OPEN, title="Открытый"
    )
    open_task = await make_task(
        db_session, actor=main_actor, project=ops, title="Открытая", description="Задача OPS"
    )
    agent = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="scout"
    )
    closed_warning = await working(db_session, main_actor, project, "Закрытое предупреждение")
    open_warning = await working(db_session, main_actor, ops, "Открытое предупреждение")
    for done in (closed_warning, open_warning):
        await close_mixed(db_session, main_actor, done)
    for item_project, item_task in ((project, task), (ops, open_task)):
        await _fill(db_session, item_project, item_task, main_actor, agent)
    await ParticipantProjectRepository(db_session).replace_access(
        agent, ProjectAccessMode.ONLY, [ops.id]
    )
    return World(
        closed=project,
        open=ops,
        closed_task=task,
        open_task=open_task,
        closed_warning=closed_warning,
        open_warning=open_warning,
        agent=agent,
        secret=await _agent_secret(db_session, agent),
        owner_secret=main_secret,
    )


def as_agent(client: AsyncClient, world: World) -> AsyncClient:
    client.headers["Authorization"] = f"Bearer {world.secret}"
    return client


def as_owner(client: AsyncClient, world: World) -> AsyncClient:
    client.headers["Authorization"] = f"Bearer {world.owner_secret}"
    return client


def leaks(payload: Any) -> list[str]:
    """Упоминания закрытого проекта в любом написании - во всём ответе целиком."""
    return CLOSED_MARK.findall(str(payload))


# --- Выборки: закрытый проект исчезает, открытый остаётся -------------------------------

#: Перечень выборок REST: имя - (путь, параметры, ключ данных, что должно остаться).
SELECTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "list_projects": ("/api/v1/projects", {}),
    "search_tasks": ("/api/v1/tasks", {"query": "", "limit": 100}),
    "journal": ("/api/v1/journal", {"after": 0, "limit": 200}),
    "inbox_questions": ("/api/v1/questions", {"any_addressee": True}),
    "inbox_remarks": ("/api/v1/remarks", {}),
    "discussions": ("/api/v1/discussions", {}),
    "discussions_waiting_on_human": ("/api/v1/discussions", {"status": "open", "turn": "human"}),
}


@pytest.mark.parametrize("name", sorted(SELECTIONS))
async def test_a_closed_project_is_absent_from_a_selection(
    name: str, client: AsyncClient, world: World
) -> None:
    path, params = SELECTIONS[name]

    everything = await as_owner(client, world).get(path, params=params)
    seen = await as_agent(client, world).get(path, params=params)

    assert everything.status_code == seen.status_code == 200, seen.text
    assert leaks(everything.json()), f"{name}: the world has nothing in {CLOSED} to hide"
    assert leaks(seen.json()) == [], f"{name} leaks {CLOSED}: {seen.text}"
    assert re.search(r"\bOPS\b|OPS-\d|OPS/|OPS~", str(seen.json())), f"{name} lost {OPEN}"


async def test_the_first_screen_counts_only_open_projects(
    client: AsyncClient, world: World
) -> None:
    """`read_bootstrap`: проекты, вопросы к агенту, предупреждения и обсуждения человека."""
    everything = (await as_owner(client, world).get("/api/v1/bootstrap")).json()["data"]
    seen = (await as_agent(client, world).get("/api/v1/bootstrap")).json()["data"]

    assert {item["key"] for item in everything["projects"]} == {CLOSED, OPEN}
    assert [item["key"] for item in seen["projects"]] == [OPEN]
    assert seen["open_questions"] == 1  # вопрос в OPS; вопрос в TRK ему не виден
    assert seen["open_warnings"] == 1 and everything["open_warnings"] == 2
    assert seen["open_discussions"] == 1 and everything["open_discussions"] == 2


async def test_search_cannot_name_a_closed_project_into_view(
    client: AsyncClient, world: World
) -> None:
    """Отбор `project: TRK` закрытый проект не открывает, а `parent`/`under` не обходят."""
    agent = as_agent(client, world)
    named = await agent.get("/api/v1/tasks", params={"query": f"project: {CLOSED}"})
    keyed = await agent.get("/api/v1/tasks", params={"query": f"key: {world.closed_task.key}"})

    assert leaks(named.json()) == [] or named.status_code == 422
    assert [item["key"] for item in keyed.json().get("data", [])] == []


async def test_the_journal_and_inbox_refuse_to_name_a_closed_project(
    client: AsyncClient, world: World
) -> None:
    """Названный закрытый проект в ленте, входящей и обсуждениях - отказ, не пустота."""
    agent = as_agent(client, world)
    for path, params in (
        ("/api/v1/journal", {"project": CLOSED}),
        ("/api/v1/journal", {"task": world.closed_task.key}),
        ("/api/v1/questions", {"project": CLOSED, "any_addressee": True}),
        ("/api/v1/remarks", {"project": CLOSED}),
        ("/api/v1/discussions", {"project": CLOSED}),
        ("/api/v1/discussions", {"task": world.closed_task.key}),
    ):
        response = await agent.get(path, params=params)
        assert response.status_code == 403, (path, params, response.text)
        assert response.json()["error"]["code"] == "project_not_allowed"
        assert response.json()["error"]["details"]["project"] == CLOSED


async def test_the_task_package_hides_links_and_discussions_of_a_closed_project(
    db_session: AsyncSession, client: AsyncClient, world: World, main_actor: Actor
) -> None:
    """Связь и родство с задачей закрытого проекта не показываются; `blocked` не врёт."""
    from app.services import links as links_service

    await links_service.add_link(
        db_session, world.open_task, world.closed_task, actor=main_actor, kind="blocked_by"
    )
    await links_service.add_link(
        db_session, world.open_task, world.closed_warning, actor=main_actor, kind="relates"
    )

    package = (await as_agent(client, world).get(f"/api/v1/tasks/{world.open_task.key}")).json()

    data = package["data"]
    # Опись дела - история открытого дела: запись `link_added` называет ключ как факт.
    shown = {key: data[key] for key in ("links", "parent", "children", "discussions", "decisions")}
    assert leaks(shown) == [] and leaks(data["state"]["blockers"]) == []
    assert data["features"]["blocked"] is True


async def test_the_see_also_of_an_area_hides_a_closed_project(
    db_session: AsyncSession, client: AsyncClient, world: World, main_actor: Actor
) -> None:
    """Связи областей (`see_also`, `see_also_from`) с областью закрытого проекта скрыты."""
    ours = await areas_service.get_area(db_session, "TRK/core")
    theirs = await areas_service.get_area(db_session, "OPS/core")
    await area_links_service.add_area_link(
        db_session, ours, theirs, actor=main_actor, reason="Смежное"
    )
    await area_links_service.add_area_link(
        db_session, theirs, ours, actor=main_actor, reason="Смежное"
    )

    card_as_owner = await as_owner(client, world).get("/api/v1/projects/OPS/areas/core")
    card_as_agent = await as_agent(client, world).get("/api/v1/projects/OPS/areas/core")
    assert leaks(card_as_owner.json()), "the card of the open area names the closed one"
    assert card_as_agent.status_code == 200 and leaks(card_as_agent.json()) == []

    stamp(db_session, ProjectAccess.of("only", [world.open.id]))
    assert await area_links_service.list_see_also(db_session, theirs) == []
    assert await area_links_service.list_see_also_from(db_session, theirs) == []
    stamp(db_session, ProjectAccess())
    assert len(await area_links_service.list_see_also(db_session, theirs)) == 1


async def test_files_follow_the_project_of_the_file(
    db_session: AsyncSession, world: World, main_actor: Actor
) -> None:
    """Файлы тоже читаются через проект (TRK/files#3, п. 5): список, выдача, замена,
    удаление, вложение в запись и название закрытого проекта в списке."""
    from app.domain.errors import FileCountMismatchError, ProjectNotAllowedError

    agent = Actor(
        author=world.agent.author,
        participant=world.agent,
        project_access=ProjectAccess.of("only", [world.open.id]),
    )
    everything = await files_service.list_files(db_session, actor=main_actor)
    stamp(db_session, agent.project_access)

    seen = await files_service.list_files(db_session, actor=agent)
    assert {card.project_key for card in everything.items} == {CLOSED, OPEN}
    assert {card.project_key for card in seen.items} == {OPEN}
    closed_file = next(card for card in everything.items if card.project_key == CLOSED)
    with pytest.raises(ProjectNotAllowedError) as refused:
        await files_service.open_file(db_session, closed_file.id, actor=agent)
    assert refused.value.details == {"project": CLOSED}
    with pytest.raises(ProjectNotAllowedError):
        await files_service.replace_file(db_session, closed_file.id, actor=agent, data=b"y")
    with pytest.raises(ProjectNotAllowedError):
        await files_service.delete_file(db_session, closed_file.id, actor=agent)
    with pytest.raises(ProjectNotAllowedError):
        await files_service.upload_file(
            db_session, actor=agent, project=CLOSED, name="a.txt", data=b"x", mime_type="text/plain"
        )
    with pytest.raises(ProjectNotAllowedError):
        await files_service.list_files(db_session, actor=agent, project=CLOSED)
    # Отбор для удаления (TRK-741) не видит файлов закрытого проекта: число и удаление
    # считаются только по открытому.
    old = datetime.now(UTC) - timedelta(days=400)
    for card in everything.items:
        file = await db_session.get(File, card.id)
        assert file is not None
        file.mime_type, file.created_at = "image/png", old
    await db_session.flush()
    visible = await files_service.list_files(db_session, actor=agent, unopened=True)
    assert {card.project_key for card in visible.items} == {OPEN}
    with pytest.raises(FileCountMismatchError) as mismatch:
        await files_service.delete_matching(
            db_session, actor=agent, expected_count=2, unopened=True
        )
    assert mismatch.value.details == {"expected": 2, "actual": 1}
    deleted = await files_service.delete_matching(
        db_session, actor=agent, expected_count=1, unopened=True
    )
    assert {card.project_key for card in deleted} == {OPEN}
    stamp(db_session, ProjectAccess())
    assert not (await files_service.read_file(db_session, closed_file.id, actor=main_actor)).deleted
    stamp(db_session, agent.project_access)
    with pytest.raises(ProjectNotAllowedError):
        await case_service.add_entry(
            db_session,
            world.open_task,
            actor=agent,
            type="note",
            title="Вложение",
            files=[closed_file.id],
        )


async def test_the_journal_stream_carries_the_access_in_its_filter(
    db_session: AsyncSession, world: World
) -> None:
    """Поток читает ленту в своих сессиях: доступ едет в фильтре, с сессии запроса."""
    from app.services import journal as journal_service

    stamp(db_session, ProjectAccess.of("only", [world.open.id]))
    journal_filter = await journal_service.resolve_filter(db_session)

    assert journal_filter.access == ProjectAccess.of("only", [world.open.id])


# --- По прямому адресу: отказ с ключом проекта --------------------------------------------


def _forbidden(response: Any) -> None:
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "project_not_allowed", error
    assert error["details"]["project"] == CLOSED


async def test_reads_by_address_of_a_closed_project_are_refused(
    client: AsyncClient, world: World
) -> None:
    """`get_project`, `get_task`, `get_discussion`, `get_area`, `get_owner`, дело проекта."""
    agent = as_agent(client, world)
    for path in (
        f"/api/v1/projects/{CLOSED}",
        f"/api/v1/projects/{CLOSED}/entries",
        f"/api/v1/projects/{CLOSED}/areas",
        f"/api/v1/projects/{CLOSED}/areas/core",
        f"/api/v1/projects/{CLOSED}/areas/core/entries",
        f"/api/v1/tasks/{world.closed_task.key}",
        f"/api/v1/tasks/{world.closed_task.key}/entries",
        "/api/v1/discussions/TRK~1",
        "/api/v1/discussions/TRK~1/entries",
    ):
        _forbidden(await agent.get(path))


async def test_writes_into_a_closed_project_are_refused(client: AsyncClient, world: World) -> None:
    """Создание задачи, запись в дело, запись в дело проекта, обсуждение, архив."""
    agent = as_agent(client, world)
    _forbidden(
        await agent.post(
            "/api/v1/tasks",
            json={"project": CLOSED, "area": "TRK/core", "title": "Чужая", "description": "d"},
        )
    )
    _forbidden(
        await agent.post(
            f"/api/v1/tasks/{world.closed_task.key}/entries", json={"type": "note", "title": "n"}
        )
    )
    _forbidden(
        await agent.post(f"/api/v1/projects/{CLOSED}/archive", json={"reason": "Нет причины"})
    )
    _forbidden(
        await agent.post(
            "/api/v1/discussions",
            json={"project": CLOSED, "title": "Чужое", "tasks": []},
        )
    )


async def test_a_move_into_a_closed_project_is_refused(client: AsyncClient, world: World) -> None:
    """`move_task`: целевой проект закрыт - отказ; из закрытого проекта задачу не взять."""
    agent = as_agent(client, world)
    _forbidden(
        await agent.post(
            f"/api/v1/tasks/{world.open_task.key}/move",
            json={"project": CLOSED, "area": "TRK/core", "reason": "Туда"},
        )
    )
    _forbidden(
        await agent.post(
            f"/api/v1/tasks/{world.closed_task.key}/move",
            json={"project": OPEN, "area": "OPS/core", "reason": "Оттуда"},
        )
    )


async def test_a_link_to_a_task_of_a_closed_project_is_refused(
    client: AsyncClient, world: World
) -> None:
    """`add_link` со второй задачей из закрытого проекта - в обе стороны."""
    agent = as_agent(client, world)
    _forbidden(
        await agent.post(
            f"/api/v1/tasks/{world.open_task.key}/links",
            json={"kind": "relates", "other": world.closed_task.key},
        )
    )
    _forbidden(
        await agent.post(
            f"/api/v1/tasks/{world.closed_task.key}/links",
            json={"kind": "relates", "other": world.open_task.key},
        )
    )


@pytest.mark.parametrize(
    "ref",
    [
        "TRK-1#1",  # запись дела задачи закрытого проекта
        "TRK-1",  # задача закрытого проекта
        "TRK#1",  # запись дела закрытого проекта
        "TRK/core#1",  # запись дела области закрытого проекта
        "TRK~1",  # обсуждение закрытого проекта
        "TRK~1#1",  # запись обсуждения закрытого проекта
    ],
)
async def test_a_reference_into_a_closed_project_is_refused(
    ref: str, client: AsyncClient, world: World
) -> None:
    """`refs` записи - запись в закрытый проект: `project_not_allowed`, не `unknown_*`."""
    response = await as_agent(client, world).post(
        f"/api/v1/tasks/{world.open_task.key}/entries",
        json={"type": "note", "title": "Ссылка", "refs": [ref]},
    )

    _forbidden(response)


async def test_a_cited_decision_of_a_closed_project_is_refused(
    db_session: AsyncSession, client: AsyncClient, world: World, main_actor: Actor
) -> None:
    """Поле `decisions` задачи: решение закрытого проекта не цитируется."""
    entry = await case_service.append_project_entry(
        db_session, world.closed, actor=main_actor, type="decision", title="Решение", body="b"
    )
    response = await as_agent(client, world).patch(
        f"/api/v1/tasks/{world.open_task.key}", json={"decisions": [f"TRK#{entry.no}"]}
    )

    _forbidden(response)


async def test_an_open_project_works_as_before(client: AsyncClient, world: World) -> None:
    agent = as_agent(client, world)

    for path in (
        f"/api/v1/projects/{OPEN}",
        f"/api/v1/tasks/{world.open_task.key}",
        f"/api/v1/projects/{OPEN}/areas",
    ):
        assert (await agent.get(path)).status_code == 200, path
    created = await agent.post(
        f"/api/v1/tasks/{world.open_task.key}/entries", json={"type": "note", "title": "Своё"}
    )
    assert created.status_code == 201, created.text


# --- MCP: тот же сценарий отвечает тем же ----------------------------------------------


async def test_mcp_sees_and_refuses_the_same_way(mcp_session: Connect, world: World) -> None:
    open_key, closed_key = world.open_task.key, world.closed_task.key
    async with mcp_session(world.secret) as session:
        projects = await call(session, "list_projects")
        found = await call(session, "search_tasks", query="")
        refusal = await refuse(session, "get_task", key=closed_key)
        moved = await refuse(
            session,
            "move_task",
            key=open_key,
            project=CLOSED,
            area="TRK/core",
            reason="Туда",
        )

    assert [item["key"] for item in projects["items"]] == [OPEN]
    assert leaks(found) == []
    assert "project_not_allowed" in refusal and CLOSED in refusal
    assert "project_not_allowed" in moved


async def test_mcp_wait_journal_refuses_a_closed_project_and_filters_the_rest(
    mcp_session: Connect, world: World
) -> None:
    async with mcp_session(world.secret) as session:
        refusal = await refuse(session, "wait_journal", project=CLOSED, after=0)
        tail = await call(session, "wait_journal", after=0, limit=200)

    assert "project_not_allowed" in refusal
    assert leaks(tail) == []
    assert tail["items"], "the open project's entries are in the tail"


# --- Тест-перечень -----------------------------------------------------------------------


def _selection_sources() -> Iterator[str]:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app"
    for path in sorted(root.rglob("*.py")):
        yield path.read_text(encoding="utf-8")


def test_every_selection_function_takes_the_access() -> None:
    """Перечень TRK-729#7 против кода: выборка без `access` читает всё молча.

    Каждая выборка репозитория, которая отдаёт строки установки поперёк проектов, обязана
    принимать `access` и вшивать `open_to`. Новая выборка, не попавшая в таблицу, - повод
    дописать и её, и строку в `SELECTIONS` выше.
    """
    import inspect

    from app.db.repositories.discussions import DiscussionRepository
    from app.db.repositories.entries import EntryRepository
    from app.db.repositories.files import FileRepository
    from app.db.repositories.projects import ProjectRepository
    from app.db.repositories.search import TaskSearchRepository

    across_projects = {
        (ProjectRepository, "list_page"),
        (TaskSearchRepository, "search_page"),
        (EntryRepository, "questions_page"),
        (EntryRepository, "remarks_page"),
        (EntryRepository, "count_questions"),
        (EntryRepository, "count_open_warnings"),
        (EntryRepository, "journal_page"),
        (DiscussionRepository, "page"),
        (DiscussionRepository, "count_waiting_on_humans"),
        (FileRepository, "list_page"),
        (FileRepository, "matching"),
    }
    for owner, method in across_projects:
        source = inspect.getsource(getattr(owner, method))
        assert "access" in inspect.signature(getattr(owner, method)).parameters, (owner, method)
        assert re.search(r"open_to\(\s*access", source), (
            f"{owner.__name__}.{method} does not apply the access"
        )


def test_a_direct_read_goes_through_the_gate() -> None:
    """Точки по адресу: `get_project` и `get_task` сверяются с доступом сессии."""
    import inspect

    from app.services import projects, tasks

    assert "require_open" in inspect.getsource(projects.get_project)
    assert "require_open" in inspect.getsource(tasks.get_task)
