"""Описание проекта не длиннее 320 знаков и едет в карточке задачи (TRK-158).

Правила — `CONCEPT.md`, 3.2 («Карточка», валидации проекта) и 4.2 (пакет преемника):
предел считается в знаках, а не в байтах, длинный текст не обрезается, а отклоняется
`project_description_too_long`; карточка задачи в `get_task` и `GET /tasks/{key}` несёт
описание проекта, строка поиска — нет. Перенос старых длинных описаний проверяет
`tests/test_migrations.py`.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.errors import ProjectDescriptionTooLongError
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.services import projects as service
from app.services.auth import Actor
from conftest import Connect, call, refuse

#: Кириллица на пределе: 320 знаков, 640 байт в UTF-8. Предел в байтах её бы отверг.
AT_LIMIT = "ё" * MAX_PROJECT_DESCRIPTION_LENGTH
OVER_LIMIT = AT_LIMIT + "ж"


def test_the_limit_is_the_one_the_concept_names() -> None:
    assert MAX_PROJECT_DESCRIPTION_LENGTH == 320
    assert len(AT_LIMIT.encode()) == 640


# --- Сценарии -------------------------------------------------------------------------


async def test_creation_takes_a_description_of_exactly_the_limit(
    db_session: AsyncSession, main_actor: Actor
) -> None:
    created = await service.create_project(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация", description=AT_LIMIT
    )

    assert created.description == AT_LIMIT


async def test_creation_refuses_one_character_over_the_limit(
    db_session: AsyncSession, main_actor: Actor
) -> None:
    with pytest.raises(ProjectDescriptionTooLongError) as refused:
        await service.create_project(
            db_session, actor=main_actor, key="OPS", title="Эксплуатация", description=OVER_LIMIT
        )

    assert refused.value.code == "project_description_too_long"
    assert refused.value.details == {"length": 321, "max_length": 320}


async def test_the_limit_is_counted_after_trimming(
    db_session: AsyncSession, main_actor: Actor
) -> None:
    created = await service.create_project(
        db_session,
        actor=main_actor,
        key="OPS",
        title="Эксплуатация",
        description=f"  {AT_LIMIT}\n",
    )

    assert created.description == AT_LIMIT


async def test_update_refuses_a_long_description_and_keeps_the_old_one(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    with pytest.raises(ProjectDescriptionTooLongError):
        await service.update_project(db_session, project, actor=main_actor, description=OVER_LIMIT)

    await db_session.refresh(project)
    assert project.description == "Бэкенд трекера"

    updated = await service.update_project(
        db_session, project, actor=main_actor, description=AT_LIMIT
    )
    assert updated.description == AT_LIMIT


# --- REST -----------------------------------------------------------------------------


async def test_rest_refuses_a_long_description_with_its_own_code(
    auth_client: AsyncClient, project: Project
) -> None:
    """Код предметный, а не `validation_error`: схема длину не режет, режет домен."""
    created = await auth_client.post(
        "/api/v1/projects", json={"key": "OPS", "title": "Эксплуатация", "description": OVER_LIMIT}
    )
    patched = await auth_client.patch("/api/v1/projects/TRK", json={"description": OVER_LIMIT})
    accepted = await auth_client.patch("/api/v1/projects/TRK", json={"description": AT_LIMIT})

    for refused in (created, patched):
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "project_description_too_long"
        assert error["details"] == {"length": 321, "max_length": 320}
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["description"] == AT_LIMIT


async def test_the_task_card_carries_the_project_description(
    auth_client: AsyncClient, task: Task
) -> None:
    package = await auth_client.get("/api/v1/tasks/TRK-1")

    assert package.status_code == 200, package.text
    assert package.json()["data"]["task"]["project"] == {
        "key": "TRK",
        "title": "Трекер",
        "description": "Бэкенд трекера",
        "archived_at": None,
    }


async def test_a_search_row_names_the_project_without_its_description(
    auth_client: AsyncClient, task: Task
) -> None:
    found = await auth_client.get("/api/v1/tasks", params={"project": "TRK"})

    assert found.status_code == 200, found.text
    [row] = found.json()["data"]
    assert row["project"] == {"key": "TRK", "title": "Трекер"}


# --- MCP ------------------------------------------------------------------------------


async def test_get_task_carries_the_project_description(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    async with mcp_session(task_secret) as session:
        package = await call(session, "get_task", key="TRK-1")
        found = await call(session, "search_tasks", project=["TRK"], fields=["key", "project"])

    assert package["task"]["project"] == {
        "key": "TRK",
        "title": "Трекер",
        "description": "Бэкенд трекера",
        "archived_at": None,
    }
    [row] = found["items"]
    assert row["project"] == {"key": "TRK", "title": "Трекер"}


async def test_mcp_refuses_a_long_description_with_its_own_code(
    mcp_session: Connect, main_secret: str, project: Project
) -> None:
    async with mcp_session(main_secret) as session:
        created = await refuse(
            session, "create_project", key="OPS", title="Эксплуатация", description=OVER_LIMIT
        )
        updated = await refuse(session, "update_project", key="TRK", description=OVER_LIMIT)
        accepted = await call(session, "update_project", key="TRK", description=AT_LIMIT)
        card = await call(session, "get_project", key="TRK")

    assert "project_description_too_long" in created
    assert "project_description_too_long" in updated
    assert accepted["key"] == "TRK"
    assert card["description"] == AT_LIMIT
