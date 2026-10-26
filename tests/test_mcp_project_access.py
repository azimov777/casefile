"""Доступ агента к проектам через MCP (TRK-747, слово владельца TRK~28#6).

Логика доступа живёт в слое сервисов (TRK-751, TRK#62); здесь граница MCP: агент с режимом
`only` или `except` приходит настоящим клиентом SDK, закрытый проект исчезает из его
выдач, а по адресу отказ `project_not_allowed` доезжает текстом с ключом проекта.

Мир: `TRK` (фикстуры `project` и `task`, задача `TRK-1`) и `OPS` (задача `OPS-1`).
"""

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories.participant_projects import ParticipantProjectRepository
from app.domain.participants import ParticipantKind
from app.domain.project_access import ProjectAccessMode
from app.domain.tokens import TokenKind
from app.services import area_links as area_links_service
from app.services import areas as areas_service
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor
from conftest import Connect, call, make_task, refuse

CLOSED = "TRK"
OPEN = "OPS"
CLOSED_TEXT = "project_not_allowed"


@dataclass(frozen=True, slots=True)
class World:
    closed_project: Project
    open_project: Project
    closed_task: Task
    open_task: Task


@pytest.fixture
async def world(db_session: AsyncSession, main_actor: Actor, project: Project, task: Task) -> World:
    ops = await projects_service.create_project(
        db_session, actor=main_actor, key=OPEN, title="Открытый"
    )
    open_task = await make_task(
        db_session, actor=main_actor, project=ops, title="Открытая", description="Задача OPS"
    )
    return World(project, ops, task, open_task)


async def _agent(
    session: AsyncSession, name: str, mode: ProjectAccessMode, projects: list[Project]
) -> str:
    """Агент с режимом доступа и ключом: его секрет."""
    agent: Participant = await participants_service.register_participant(
        session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name=name
    )
    await ParticipantProjectRepository(session).replace_access(
        agent, mode, [item.id for item in projects]
    )
    issued = await tokens_service.issue_token(
        session, actor=TRACKER_ACTOR, participant=agent, name=name, kind=TokenKind.KEY
    )
    return issued.secret


@pytest.fixture
async def only_nothing(db_session: AsyncSession, world: World) -> str:
    """Агент в режиме `only` без единого проекта: открыто ничего."""
    del world
    return await _agent(db_session, "scout", ProjectAccessMode.ONLY, [])


@pytest.fixture
async def except_closed(db_session: AsyncSession, world: World) -> str:
    """Агент в режиме `except`: закрыт только `TRK`."""
    return await _agent(db_session, "ranger", ProjectAccessMode.EXCEPT, [world.closed_project])


async def test_only_agent_without_projects_sees_nothing_and_is_refused_by_address(
    mcp_session: Connect, only_nothing: str, world: World
) -> None:
    """Обзорная проверка 2: `list_projects` и `search_tasks` пусты, а `get_task`,
    `get_project`, `create_task` и `wait_journal` с закрытым проектом отвечают
    `project_not_allowed` с ключом проекта."""
    closed_key = world.closed_task.key
    async with mcp_session(only_nothing) as session:
        projects = await call(session, "list_projects")
        found = await call(session, "search_tasks", query="")
        task_text = await refuse(session, "get_task", key=closed_key)
        project_text = await refuse(session, "get_project", key=CLOSED)
        create_text = await refuse(
            session,
            "create_task",
            project=CLOSED,
            area=f"{CLOSED}/core",
            title="Новая",
            description="Нельзя",
        )
        wait_text = await refuse(session, "wait_journal", project=CLOSED)
        wait_task_text = await refuse(session, "wait_journal", task=closed_key)
        search_text = await refuse(session, "search_tasks", project=[CLOSED])

    assert projects["items"] == []
    assert found["items"] == []
    assert '"reason": "project_not_allowed"' in search_text
    assert f'"value": "{CLOSED}"' in search_text
    for text in (task_text, project_text, create_text, wait_text, wait_task_text):
        assert f": {CLOSED_TEXT}: " in text, text
        assert f'"project": "{CLOSED}"' in text, text


async def test_only_agent_is_refused_the_same_way_for_a_project_never_opened(
    mcp_session: Connect, only_nothing: str
) -> None:
    """Отказ не подталкивает завести проект заново: в тексте нет `create_project`, а
    сам проект назван и тем, что он есть, и тем, что он закрыт этому агенту."""
    async with mcp_session(only_nothing) as session:
        text = await refuse(session, "get_project", key=CLOSED)

    assert "closed" in text
    assert "create" not in text.lower()
    assert "owner" in text


async def test_except_agent_works_in_the_open_projects_as_before(
    mcp_session: Connect, except_closed: str, world: World
) -> None:
    """Обзорная проверка 3: при `except` с одним закрытым проектом открытые читаются и
    правятся как раньше, закрытый исчез из списка и отвечает отказом с названием."""
    open_key = world.open_task.key
    closed_key = world.closed_task.key
    async with mcp_session(except_closed) as session:
        projects = await call(session, "list_projects")
        found = await call(session, "search_tasks", query="")
        read = await call(session, "get_task", key=open_key, brief=True)
        updated = await call(
            session, "update_task", key=open_key, changes={"title": "Открытая, правка"}
        )
        entry = await call(session, "add_entry", key=open_key, type="note", title="Заметка агента")
        refused = await refuse(session, "get_task", key=closed_key)
        refused_write = await refuse(
            session, "add_entry", key=closed_key, type="note", title="Нельзя"
        )

    assert [item["key"] for item in projects["items"]] == [OPEN]
    assert [item["key"] for item in found["items"]] == [open_key]
    assert read["task"]["key"] == open_key
    assert updated["key"] == open_key
    assert entry["no"] > 0
    for text in (refused, refused_write):
        assert f": {CLOSED_TEXT}: " in text, text
        assert f'"project": "{CLOSED}"' in text, text


async def test_closed_agent_sees_no_see_also_of_a_closed_area(
    mcp_session: Connect,
    db_session: AsyncSession,
    main_actor: Actor,
    except_closed: str,
    world: World,
) -> None:
    """Связь областей (TRK-735): `get_project` области открытого проекта не называет
    область закрытого в `see_also`, а у человека она видна."""
    web = await areas_service.create_area(
        db_session, actor=main_actor, address=f"{OPEN}/web", title="Web", description=""
    )
    api = await areas_service.create_area(
        db_session, actor=main_actor, address=f"{OPEN}/api", title="Api", description=""
    )
    core = await areas_service.get_area(db_session, f"{CLOSED}/core")
    del world
    await area_links_service.add_area_link(
        db_session, web, core, actor=main_actor, reason="Клиент читает правила ядра"
    )
    await area_links_service.add_area_link(
        db_session, web, api, actor=main_actor, reason="Клиент ходит в api"
    )
    async with mcp_session(except_closed) as session:
        seen = await call(session, "get_project", key=f"{OPEN}/web")

    assert [item["address"] for item in seen["see_also"]] == [f"{OPEN}/api"]
