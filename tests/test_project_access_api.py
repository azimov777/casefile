"""Настройка доступа агента к проектам и сам доступ в трёх режимах (TRK-751).

Ручка `GET`/`PUT /participants/{name}/projects`: режим и ключи проектов, права «кто
настраивает» (TRK#79, TRK#73), коды отказа; проект, созданный агентом в режиме `only`,
попадает в его список; `except`, `all`, человек и общий агентский ключ видят всё.
Перечень выборок и точек по адресу - `test_project_access_selections.py`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenKind
from app.services import accounts as accounts_service
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor

PASSWORD = "correct horse battery staple"


async def _person(session: AsyncSession, name: str) -> Participant:
    created = await accounts_service.create_account(
        session, actor=TRACKER_ACTOR, email=f"{name}@example.com", name=name, password=PASSWORD
    )
    return created.account.participant


async def _bearer(
    session: AsyncSession, participant: Participant, kind: TokenKind = TokenKind.KEY
) -> dict[str, str]:
    issued = await tokens_service.issue_token(
        session, actor=TRACKER_ACTOR, participant=participant, name="k", kind=kind
    )
    return {"Authorization": f"Bearer {issued.secret}"}


async def _agent(
    session: AsyncSession, name: str = "scout", owner: Participant | None = None
) -> Participant:
    if owner is not None:
        return await participants_service.agent_of(session, client=name, owner=owner)
    return await participants_service.register_participant(
        session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name=name
    )


@pytest.fixture
async def two_projects(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> tuple[Project, Project]:
    ops = await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Открытый"
    )
    return project, ops


async def _put(
    client: AsyncClient, name: str, mode: str, projects: list[str], **kwargs: Any
) -> Any:
    return await client.put(
        f"/api/v1/participants/{name}/projects", json={"mode": mode, "projects": projects}, **kwargs
    )


async def _keys(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("/api/v1/projects", headers=headers)
    assert response.status_code == 200, response.text
    return sorted(item["key"] for item in response.json()["data"])


# --- Ручка ----------------------------------------------------------------------------------


async def test_the_default_is_all_with_an_empty_list(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _agent(db_session)

    response = await auth_client.get("/api/v1/participants/scout/projects")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"mode": "all", "projects": []}


async def test_put_saves_the_mode_and_the_keys_and_get_returns_them(
    auth_client: AsyncClient, db_session: AsyncSession, two_projects: tuple[Project, Project]
) -> None:
    await _agent(db_session)

    saved = await _put(auth_client, "scout", "only", ["ops", "TRK"])
    read = await auth_client.get("/api/v1/participants/scout/projects")

    assert saved.status_code == 200, saved.text
    assert saved.json()["data"] == {"mode": "only", "projects": ["OPS", "TRK"]}
    assert read.json()["data"] == saved.json()["data"]


async def test_all_clears_the_list_and_a_new_put_replaces_it(
    auth_client: AsyncClient, db_session: AsyncSession, two_projects: tuple[Project, Project]
) -> None:
    await _agent(db_session)
    await _put(auth_client, "scout", "except", ["TRK"])

    replaced = await _put(auth_client, "scout", "only", ["OPS"])
    cleared = await _put(auth_client, "scout", "all", ["OPS"])

    assert replaced.json()["data"] == {"mode": "only", "projects": ["OPS"]}
    assert cleared.json()["data"] == {"mode": "all", "projects": []}


async def test_an_unknown_project_or_mode_is_refused(
    auth_client: AsyncClient, db_session: AsyncSession, two_projects: tuple[Project, Project]
) -> None:
    await _agent(db_session)

    unknown = await _put(auth_client, "scout", "only", ["NOPE"])
    bad_mode = await _put(auth_client, "scout", "some", ["OPS"])

    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "project_not_found"
    assert bad_mode.status_code == 422
    assert bad_mode.json()["error"]["code"] == "project_access_mode_invalid"
    assert bad_mode.json()["error"]["details"]["allowed"] == ["all", "except", "only"]
    assert (await auth_client.get("/api/v1/participants/scout/projects")).json()["data"] == {
        "mode": "all",
        "projects": [],
    }


async def test_only_an_agent_has_a_project_access(
    auth_client: AsyncClient, db_session: AsyncSession, owner: Participant
) -> None:
    response = await _put(auth_client, "owner", "only", [])
    read = await auth_client.get("/api/v1/participants/owner/projects")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "participant_not_agent"
    assert read.json()["data"] == {"mode": "all", "projects": []}
    assert (await auth_client.get("/api/v1/participants/nobody/projects")).status_code == 404


# --- Кто настраивает ------------------------------------------------------------------------


async def test_a_person_configures_own_and_ownerless_agents_but_not_a_foreign_one(
    client: AsyncClient, auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    alice = await _person(db_session, "alice")
    bob = await _person(db_session, "bob")
    await _agent(db_session, "claude", owner=alice)
    await _agent(db_session, "claude", owner=bob)
    await _agent(db_session, "scout")
    headers = await _bearer(db_session, alice, TokenKind.SESSION)

    own = await _put(client, "claude_alice", "except", [], headers=headers)
    ownerless = await _put(client, "scout", "only", [], headers=headers)
    foreign = await _put(client, "claude_bob", "only", [], headers=headers)
    foreign_read = await client.get("/api/v1/participants/claude_bob/projects", headers=headers)
    by_admin = await _put(auth_client, "claude_bob", "only", [])

    assert (own.status_code, ownerless.status_code) == (200, 200)
    for refused in (foreign, foreign_read):
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "agent_owned_by_another"
    assert by_admin.status_code == 200


async def test_an_agent_cannot_change_its_own_access(
    client: AsyncClient, db_session: AsyncSession, two_projects: tuple[Project, Project]
) -> None:
    agent = await _agent(db_session)
    headers = await _bearer(db_session, agent)

    changed = await _put(client, "scout", "all", [], headers=headers)
    read = await client.get("/api/v1/participants/scout/projects", headers=headers)

    for refused in (changed, read):
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "permission_denied"
        assert refused.json()["error"]["details"]["reason"] == "account_required"


async def test_the_shared_agent_key_cannot_configure_either(
    client: AsyncClient, shared_secret: str, db_session: AsyncSession
) -> None:
    await _agent(db_session)

    response = await _put(
        client,
        "scout",
        "all",
        [],
        headers={"Authorization": f"Bearer {shared_secret}", "X-Actor-Label": "nightly_agent"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "account_required"


# --- Доступ в трёх режимах ------------------------------------------------------------------


async def test_the_three_modes_open_the_right_projects(
    client: AsyncClient,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    two_projects: tuple[Project, Project],
    shared_secret: str,
) -> None:
    agent = await _agent(db_session)
    headers = await _bearer(db_session, agent)
    shared = {"Authorization": f"Bearer {shared_secret}", "X-Actor-Label": "nightly_agent"}

    assert await _keys(client, headers) == ["OPS", "TRK"]  # по умолчанию: все

    await _put(auth_client, "scout", "only", ["OPS"])
    assert await _keys(client, headers) == ["OPS"]

    await _put(auth_client, "scout", "only", [])
    assert await _keys(client, headers) == []

    await _put(auth_client, "scout", "except", ["OPS"])
    assert await _keys(client, headers) == ["TRK"]

    await _put(auth_client, "scout", "all", [])
    assert await _keys(client, headers) == ["OPS", "TRK"]

    # Человек и общий агентский ключ ограничений не имеют, что бы ни стояло на агентах.
    await _put(auth_client, "scout", "only", [])
    assert await _keys(auth_client, {}) == ["OPS", "TRK"]
    assert await _keys(client, shared) == ["OPS", "TRK"]


async def test_the_access_is_on_the_participant_not_on_the_token(
    client: AsyncClient,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    two_projects: tuple[Project, Project],
) -> None:
    """Перевыпущенный ключ и ключ из другого вида токена говорят тем же доступом (TRK#75)."""
    agent = await _agent(db_session)
    await _put(auth_client, "scout", "only", ["TRK"])

    first = await _bearer(db_session, agent)
    second = await _bearer(db_session, agent)

    assert await _keys(client, first) == await _keys(client, second) == ["TRK"]


# --- Созданный проект ----------------------------------------------------------------------


async def test_a_project_made_by_an_agent_in_only_mode_joins_its_list(
    client: AsyncClient,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    two_projects: tuple[Project, Project],
) -> None:
    agent = await _agent(db_session)
    headers = await _bearer(db_session, agent)
    await _put(auth_client, "scout", "only", ["OPS"])

    created = await client.post(
        "/api/v1/projects", json={"key": "OWN", "title": "Свой"}, headers=headers
    )

    assert created.status_code == 201, created.text
    assert await _keys(client, headers) == ["OPS", "OWN"]
    assert (await client.get("/api/v1/projects/OWN", headers=headers)).status_code == 200
    stored = await auth_client.get("/api/v1/participants/scout/projects")
    assert stored.json()["data"] == {"mode": "only", "projects": ["OPS", "OWN"]}


async def test_a_project_made_by_an_agent_in_except_or_all_mode_is_seen(
    client: AsyncClient,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    two_projects: tuple[Project, Project],
) -> None:
    agent = await _agent(db_session)
    headers = await _bearer(db_session, agent)

    await _put(auth_client, "scout", "except", ["TRK"])
    await client.post("/api/v1/projects", json={"key": "AAA", "title": "A"}, headers=headers)
    await _put(auth_client, "scout", "all", [])
    await client.post("/api/v1/projects", json={"key": "BBB", "title": "B"}, headers=headers)

    assert await _keys(client, headers) == ["AAA", "BBB", "OPS", "TRK"]
    await _put(auth_client, "scout", "except", ["TRK"])
    assert await _keys(client, headers) == ["AAA", "BBB", "OPS"]
    stored = await auth_client.get("/api/v1/participants/scout/projects")
    assert stored.json()["data"] == {"mode": "except", "projects": ["TRK"]}


async def test_a_project_made_by_a_person_is_closed_to_an_only_agent(
    client: AsyncClient,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    two_projects: tuple[Project, Project],
) -> None:
    """Новый проект человека или другого агента в `only` закрыт, пока его не добавили."""
    agent = await _agent(db_session)
    headers = await _bearer(db_session, agent)
    await _put(auth_client, "scout", "only", ["OPS"])

    await auth_client.post("/api/v1/projects", json={"key": "NEW", "title": "Новый"})

    assert await _keys(client, headers) == ["OPS"]
    refused = await client.get("/api/v1/projects/NEW", headers=headers)
    assert refused.json()["error"]["code"] == "project_not_allowed"
    assert refused.json()["error"]["details"] == {"project": "NEW"}
