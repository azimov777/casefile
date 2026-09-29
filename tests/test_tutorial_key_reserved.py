"""Ключ `START` закреплён за учебным проектом (`TRK-384`).

Учебный проект узнаётся по ключу — решение владельца, пометки в схеме нет. Поэтому
второй проект с этим ключом не заводится ни человеком, ни агентом: отказ
`project_key_reserved` в REST и в MCP. Засев — сама установка — заводит его как раньше.
Переименования ключа в трекере нет вовсе: правка с `key` отклоняется формой.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.domain.authors import AuthorKind
from app.domain.errors import ProjectKeyReservedError
from app.domain.tutorial import TUTORIAL_PROJECT_KEY
from app.services import projects as projects_service
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.tutorial import seed_tutorial_on_boot
from conftest import Connect, refuse

#: Ключ учебного проекта так, как его может набрать человек или прислать агент.
SPELLINGS = [TUTORIAL_PROJECT_KEY, TUTORIAL_PROJECT_KEY.lower(), "Start"]


@pytest.mark.parametrize("key", SPELLINGS)
async def test_rest_refuses_the_tutorial_key_and_names_why(
    auth_client: AsyncClient, key: str
) -> None:
    response = await auth_client.post("/api/v1/projects", json={"key": key, "title": "Свой"})

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "project_key_reserved"
    assert error["message"] == "Project key is reserved for the tutorial project"
    assert error["details"] == {"key": TUTORIAL_PROJECT_KEY, "reserved_for": "tutorial"}
    listed = await auth_client.get("/api/v1/projects")
    assert TUTORIAL_PROJECT_KEY not in {row["key"] for row in listed.json()["data"]}


async def test_rest_refuses_it_with_the_same_reason_while_the_tutorial_project_exists(
    auth_client: AsyncClient, db_session: AsyncSession, owner: Participant
) -> None:
    """Ключ закреплён, а не просто занят: причина та же, что и без проекта `START`."""
    seed = await seed_tutorial_on_boot(db_session)
    assert seed.created

    response = await auth_client.post(
        "/api/v1/projects", json={"key": TUTORIAL_PROJECT_KEY, "title": "Свой"}
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "project_key_reserved"


@pytest.mark.parametrize("key", SPELLINGS)
async def test_mcp_refuses_the_tutorial_key_with_the_same_code(
    mcp_session: Connect, main_secret: str, key: str
) -> None:
    async with mcp_session(main_secret) as session:
        failure = await refuse(session, "create_project", key=key, title="Свой")

    assert "project_key_reserved" in failure
    assert "Project key is reserved for the tutorial project" in failure


async def test_mcp_names_the_reserved_key_in_the_argument_description(
    mcp_session: Connect, main_secret: str
) -> None:
    """Агент узнаёт о закреплённом ключе до вызова — из метадаты аргумента."""
    async with mcp_session(main_secret) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    description = tools["create_project"].input_schema["properties"]["key"]["description"]
    assert "`START`" in description and "`project_key_reserved`" in description


async def test_rest_cannot_rename_another_project_into_the_tutorial_key(
    auth_client: AsyncClient, project: Project
) -> None:
    """Переименования ключа нет: `key` в правке — отказ формы, ключ остаётся прежним."""
    refused = await auth_client.patch(
        f"/api/v1/projects/{project.key}", json={"key": TUTORIAL_PROJECT_KEY}
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "validation_error"
    assert (await auth_client.get(f"/api/v1/projects/{project.key}")).status_code == 200
    assert (await auth_client.get(f"/api/v1/projects/{TUTORIAL_PROJECT_KEY}")).status_code == 404


async def test_mcp_cannot_rename_another_project_into_the_tutorial_key(
    mcp_session: Connect, main_secret: str, project: Project, auth_client: AsyncClient
) -> None:
    async with mcp_session(main_secret) as session:
        failure = await refuse(
            session, "update_project", key=project.key, new_key=TUTORIAL_PROJECT_KEY
        )

    assert "extra_forbidden" in failure
    assert (await auth_client.get(f"/api/v1/projects/{TUTORIAL_PROJECT_KEY}")).status_code == 404


async def test_the_service_refuses_a_person_and_lets_the_installation_through(
    db_session: AsyncSession, main_actor: Actor
) -> None:
    """Правило стоит в сценарии — одной точке для REST, MCP и засева."""
    with pytest.raises(ProjectKeyReservedError):
        await projects_service.create_project(
            db_session, actor=main_actor, key=TUTORIAL_PROJECT_KEY, title="Свой"
        )

    made = await projects_service.create_project(
        db_session, actor=TRACKER_ACTOR, key=TUTORIAL_PROJECT_KEY, title="Учебный"
    )
    assert made.key == TUTORIAL_PROJECT_KEY
    assert made.created_by.kind is AuthorKind.TRACKER


async def test_the_seed_still_creates_start_on_an_empty_installation(
    db_session: AsyncSession, owner: Participant
) -> None:
    seed = await seed_tutorial_on_boot(db_session)

    assert seed.created
    assert seed.project is not None
    assert seed.project.key == TUTORIAL_PROJECT_KEY
    assert seed.tasks
