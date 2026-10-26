"""Связь областей `see_also` через MCP (TRK-735, решение TRK~24#12): `link` и `unlink` по
адресам областей с причиной, поле `see_also` в `get_project` области, отказы.

Вызовы идут настоящим клиентом SDK, как в `tests/test_mcp_tools.py`: разбор аргументов по
схеме и свёртка ответа живут не в теле инструмента. Сценарии связи областей проверены в
`tests/test_area_links_service.py`; здесь — граница MCP.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.services import areas as areas_service
from app.services.auth import Actor
from conftest import Connect, call, refuse

SOURCE = "TRK/core"
TARGET = "TRK/web"
REASON = "The web client reads the core rules"
SEE_ALSO_FIELDS = {"address", "title", "description", "reason"}


@pytest.fixture
async def neighbour(db_session: AsyncSession, main_actor: Actor, project: Project) -> None:
    """Вторая область проекта: цель связи."""
    del project
    await areas_service.create_area(
        db_session, actor=main_actor, address=TARGET, title="Web", description="Client"
    )


async def test_link_two_areas_shows_see_also_of_the_source_only(
    mcp_session: Connect, task_secret: str, neighbour: None
) -> None:
    """Обзорная проверка 2: `link` областей с причиной отвечает номерами `link_added` в делах
    обеих; `get_project` источника несёт один элемент `see_also`, цели и проекта — пустой
    `see_also`; после `unlink` у источника пусто."""
    del neighbour
    async with mcp_session(task_secret) as session:
        linked = await call(
            session, "link", key=SOURCE, kind="see_also", other=TARGET, reason=REASON
        )
        source_case = await call(session, "read_project_entries", key=SOURCE)
        target_case = await call(session, "read_project_entries", key=TARGET)
        source = await call(session, "get_project", key=SOURCE)
        target = await call(session, "get_project", key=TARGET)
        project = await call(session, "get_project", key="TRK")
        unlinked = await call(session, "unlink", key=SOURCE, kind="see_also", other=TARGET)
        source_after = await call(session, "get_project", key=SOURCE)
        source_case_after = await call(session, "read_project_entries", key=SOURCE)

    assert set(linked) == {"key", "entry", "other_entry"}
    assert linked["key"] == SOURCE
    own = source_case["items"][-1]
    other = target_case["items"][-1]
    assert (own["no"], own["type"]) == (linked["entry"], "link_added")
    assert (other["no"], other["type"]) == (linked["other_entry"], "link_added")
    assert [item["address"] for item in source["see_also"]] == [TARGET]
    assert set(source["see_also"][0]) == SEE_ALSO_FIELDS
    assert source["see_also"][0]["title"] == "Web"
    assert source["see_also"][0]["description"] == "Client"
    assert source["see_also"][0]["reason"] == REASON
    assert target["see_also"] == []
    assert project["see_also"] == []
    assert unlinked["key"] == SOURCE
    removed = source_case_after["items"][-1]
    assert (removed["no"], removed["type"]) == (unlinked["entry"], "link_removed")
    assert source_after["see_also"] == []


async def test_area_link_refusals(
    mcp_session: Connect, task_secret: str, task: Task, neighbour: None
) -> None:
    """Обзорная проверка 3: вид не `see_also` у адреса области, причина у задачи, вид
    `see_also` у задачи, связь областей без причины, причина у `unlink`."""
    del neighbour
    task_key = task.key
    other_key = "TRK-999"
    async with mcp_session(task_secret) as session:
        wrong_kind = await refuse(session, "link", key=SOURCE, kind="blocks", other=TARGET)
        wrong_kind_unlink = await refuse(session, "unlink", key=SOURCE, kind="blocks", other=TARGET)
        see_also_for_task = await refuse(
            session, "link", key=task_key, kind="see_also", other=other_key
        )
        reason_for_task = await refuse(
            session, "link", key=task_key, kind="relates", other=other_key, reason="why"
        )
        no_reason = await refuse(session, "link", key=SOURCE, kind="see_also", other=TARGET)
        blank_reason = await refuse(
            session, "link", key=SOURCE, kind="see_also", other=TARGET, reason="  "
        )
        reason_in_unlink = await refuse(
            session, "unlink", key=SOURCE, kind="see_also", other=TARGET, reason="why"
        )
        not_found = await refuse(session, "unlink", key=SOURCE, kind="see_also", other=TARGET)

    assert "invalid_link_kind" in wrong_kind
    assert "see_also" in wrong_kind
    assert "blocked_by" not in wrong_kind  # у областей один вид
    assert "invalid_link_kind" in wrong_kind_unlink
    assert "invalid_link_kind" in see_also_for_task
    assert "blocked_by" in see_also_for_task  # прежний перечень видов задачи
    assert "link_reason_not_allowed" in reason_for_task
    assert "area_link_reason_required" in no_reason
    assert "area_link_reason_required" in blank_reason
    assert "reason" in reason_in_unlink  # аргумента нет: отказ разбора, а не проглатывание
    assert "area_link_not_found" in not_found


async def test_a_repeated_area_link_answers_with_the_first_response(
    mcp_session: Connect, task_secret: str, neighbour: None
) -> None:
    """Обзорная проверка 3: повтор с тем же `idempotency_key` отдаёт первый ответ и второй
    записи не подшивает; без ключа повтор — `area_link_exists`."""
    del neighbour
    arguments: dict[str, Any] = {
        "key": SOURCE,
        "kind": "see_also",
        "other": TARGET,
        "reason": REASON,
        "idempotency_key": str(uuid.uuid4()),
    }
    async with mcp_session(task_secret) as session:
        first = await call(session, "link", **arguments)
        again = await call(session, "link", **arguments)
        conflict = await refuse(session, "link", **{**arguments, "reason": "Другая причина"})
        without_key = await refuse(
            session, "link", key=SOURCE, kind="see_also", other=TARGET, reason=REASON
        )
        case = await call(session, "read_project_entries", key=SOURCE, types=["link_added"])

    assert first == again
    assert "idempotency_key_reused" in conflict
    assert "area_link_exists" in without_key
    assert [item["no"] for item in case["items"]] == [first["entry"]]
