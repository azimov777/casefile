"""Закрытый агенту проект: остатки в открытом деле (TRK-753, слово владельца TRK~28#6).

Механизм доступа (TRK-751) убирает закрытый проект из выборок и отказывает по адресу.
Остаётся то, что называет закрытый проект изнутри открытой задачи; четыре места и решение
по каждому:

1. опись и тела записей `link_added`/`moved`/`attached` - ключ заменён меткой, связь остаётся;
2. процитированное решение закрытого проекта - уходит из карточки (`decisions`);
3. `details.discussions` отказа `task_has_open_discussions` - метка вместо адреса, число то же;
4. блокер из закрытого проекта - в `state.blockers` метка, `features.blocked` не лжёт.

Мир - тот же, что в `test_project_access_selections.py`: `TRK` закрыт агенту `scout`.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.project_scope import stamp
from app.domain.project_access import CLOSED_PROJECT_LABEL, ProjectAccess
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import links as links_service
from app.services.auth import Actor
from conftest import Connect, call, refuse
from test_project_access_selections import World, as_agent, as_owner, leaks
from test_project_access_selections import world as selections_world

#: Мир тот же, что у перечня выборок: фикстура берётся оттуда под своим именем.
world = selections_world


@pytest.fixture
async def staged(db_session: AsyncSession, client: AsyncClient, world: World, main_actor: Actor):
    """Открытая задача связана с закрытым проектом всеми четырьмя способами."""
    open_task, closed_task = world.open_task, world.closed_task
    await links_service.add_link(
        db_session, open_task, closed_task, actor=main_actor, kind="blocked_by"
    )
    await case_service.record_moved(
        db_session,
        open_task,
        actor=main_actor,
        from_project="TRK",
        to_project="OPS",
        from_key="TRK-9",
        to_key=open_task.key,
        reason="Move",
    )
    discussion = await discussions_service.get_discussion(db_session, "TRK~1")
    await discussions_service.attach_task(db_session, discussion, open_task, actor=main_actor)
    decision = await case_service.append_project_entry(
        db_session, world.closed, actor=main_actor, type="decision", title="Decision TRK", body="b"
    )
    patched = await as_owner(client, world).patch(
        f"/api/v1/tasks/{open_task.key}", json={"decisions": [f"TRK#{decision.no}"]}
    )
    assert patched.status_code == 200, patched.text
    return world


async def test_the_open_task_package_names_no_closed_project(
    client: AsyncClient, staged: World
) -> None:
    key = staged.open_task.key
    owner = (await as_owner(client, staged).get(f"/api/v1/tasks/{key}")).json()["data"]
    seen = (await as_agent(client, staged).get(f"/api/v1/tasks/{key}")).json()["data"]

    assert leaks(owner["index"]), "the owner sees the keys in the index"
    assert len(owner["index"]) == len(seen["index"])  # опись не теряет записей
    assert leaks(seen) == [], seen
    # 1. связь и перенос остаются фактами без имени
    links = [item for item in seen["index"] if item["type"] == "link_added"]
    link = next(item for item in links if CLOSED_PROJECT_LABEL in item["title"])
    assert CLOSED_PROJECT_LABEL in link["title"]
    assert link["facts"]["other_key"] == CLOSED_PROJECT_LABEL
    moved = next(item for item in seen["index"] if item["type"] == "moved")
    assert moved["facts"]["from_key"] == CLOSED_PROJECT_LABEL
    assert moved["facts"]["to_key"] == key
    attached = next(
        item
        for item in seen["index"]
        if item["type"] == "attached" and CLOSED_PROJECT_LABEL in item["title"] + str(item["facts"])
    )
    assert attached["facts"]["discussion"] == CLOSED_PROJECT_LABEL
    # 2. процитированное решение закрытого проекта ушло из карточки
    assert owner["decisions"] and seen["decisions"] == []
    # 4. блокер: причина названа без имени, признак не врёт
    assert seen["state"]["blockers"] == [CLOSED_PROJECT_LABEL]
    assert seen["features"]["blocked"] is True
    # вопрос закрытого обсуждения по-прежнему держит задачу, но без заголовка и адреса
    assert (
        seen["features"]["open_blocking_questions"]
        == owner["features"]["open_blocking_questions"]
        > 0
    )
    assert CLOSED_PROJECT_LABEL in [q.get("discussion") for q in seen["state"]["questions"]]


async def test_entry_bodies_of_the_open_task_name_no_closed_project(
    client: AsyncClient, staged: World
) -> None:
    key = staged.open_task.key
    path = f"/api/v1/tasks/{key}/entries"
    types = ["link_added", "moved", "attached"]

    owner = (await as_owner(client, staged).get(path, params={"types": types})).json()
    seen = (await as_agent(client, staged).get(path, params={"types": types})).json()

    assert leaks(owner), "the owner reads the keys in the bodies"
    assert seen["data"] and leaks(seen) == [], seen


async def test_a_refusal_of_closing_names_no_closed_discussion(
    client: AsyncClient, staged: World
) -> None:
    """3. `task_has_open_discussions`: открытое обсуждение названо, закрытого проекта - метка."""
    path = f"/api/v1/tasks/{staged.open_task.key}/transition"
    body = {"to": "cancelled", "reason": "Not needed"}

    owner = await as_owner(client, staged).post(path, json=body)
    seen = await as_agent(client, staged).post(path, json=body)

    assert seen.status_code == owner.status_code == 409, seen.text
    shown = seen.json()["error"]
    assert shown["code"] == "task_has_open_discussions"
    assert leaks(shown) == [], shown
    assert sorted(shown["details"]["discussions"]) == sorted([CLOSED_PROJECT_LABEL, "OPS~1"])
    assert len(owner.json()["error"]["details"]["discussions"]) == 2


async def test_a_refusal_of_work_names_the_blocker_without_its_project(
    client: AsyncClient, staged: World
) -> None:
    """4. Вход в работу: блокер закрытого проекта держит задачу, но назван меткой."""
    key = staged.open_task.key
    sections = {"goal": "g", "context": "c", "constraints": "k", "output": "o", "checks": ["c"]}
    await as_owner(client, staged).patch(f"/api/v1/tasks/{key}", json=sections)
    agent = as_agent(client, staged)
    await agent.patch(f"/api/v1/tasks/{key}", json={"assignee": "scout"})
    opened = await agent.post(f"/api/v1/tasks/{key}/transition", json={"to": "open"})
    assert opened.status_code in (200, 409), opened.text

    refused = await agent.post(f"/api/v1/tasks/{key}/transition", json={"to": "in_progress"})

    shown = refused.json()["error"]
    assert shown["code"] == "task_blocked", refused.text
    assert shown["details"]["blockers"] == [CLOSED_PROJECT_LABEL]
    assert leaks(shown) == []


async def test_a_closed_blocker_is_not_reported(
    db_session: AsyncSession, client: AsyncClient, world: World, main_actor: Actor
) -> None:
    """Блокер закрытого проекта, уже закрытый сам, ни в `blockers`, ни в `blocked` не попадает."""
    await links_service.add_link(
        db_session, world.open_task, world.closed_warning, actor=main_actor, kind="relates"
    )
    seen = (await as_agent(client, world).get(f"/api/v1/tasks/{world.open_task.key}")).json()[
        "data"
    ]

    assert seen["state"]["blockers"] == [] and seen["features"]["blocked"] is False


async def test_the_unrestricted_actor_is_not_masked(
    db_session: AsyncSession, staged: World, main_actor: Actor
) -> None:
    stamp(db_session, ProjectAccess())
    index = await case_service.case_index(db_session, staged.open_task, actor=main_actor)

    assert any("TRK-" in item.title for item in index if item.type.value == "link_added")


async def test_mcp_names_no_closed_project_in_the_open_task(
    mcp_session: Connect, staged: World
) -> None:
    key = staged.open_task.key
    async with mcp_session(staged.secret) as session:
        package = await call(session, "get_task", key=key)
        entries = await call(
            session, "read_entries", key=key, types=["link_added", "moved", "attached"]
        )
        refusal = await refuse(session, "transition", key=key, to="cancelled", reason="Not needed")

    assert leaks(package) == [], package
    assert entries["items"] and leaks(entries) == [], entries
    assert package["state"]["blockers"] == [CLOSED_PROJECT_LABEL]
    assert package["features"]["blocked"] is True
    assert package["decisions"] == []
    assert "task_has_open_discussions" in refusal and leaks(refusal) == [], refusal
    assert CLOSED_PROJECT_LABEL in refusal
