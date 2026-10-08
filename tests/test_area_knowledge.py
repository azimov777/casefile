"""Знание в деле области (TRK-658, решение TRK#57, разделы 5–6): замена решений и заметок
через `supersedes` и статус «действует / заменена» тем же расчётом, что у дела проекта;
чтение области в форме проекта; решение области в поле задачи `decisions` и в отборе
`decision:`.

Обзорные проверки задачи, которые здесь измеряются (область `X/mcp` проверок — `TRK/mcp`):

- 2: в деле области заметка A, заметка B с `supersedes=[A]` и решение C — `get_project`
  отдаёт C в `decisions` и B в `findings`, A нет, в описи нет решений и заметок;
  `read_project_entries(in_force=false)` отдаёт только A;
- 3: ссылка задачи на решение области принимается и находится отбором `decision`; ссылка
  на заметку области — `not_a_decision`; на заменённое решение — `decision_not_in_force`;
  `supersedes` с номером записи другого дела — `entry_fields_invalid`.

Перенос установки с записью области, которая заменяет другую, — `tests/test_archive.py`.
Та же механика у дела проекта — `tests/test_project_knowledge.py` и
`tests/test_project_decisions.py`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.errors import DecisionNotInForceError
from app.domain.fields import FieldProblem
from app.domain.tasks import normalize_decision_ref, split_decision_ref
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges
from conftest import Connect, call, refuse, without_empty_standing

AREA_ENTRIES = "/api/v1/projects/TRK/areas/mcp/entries"


def _standing(item: dict[str, Any]) -> tuple[int, str | None, int | None]:
    return item["no"], item.get("status"), item.get("superseded_by")


# --- Домен: ссылка на решение области -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("TRK/mcp#3", "TRK/mcp#3"), (" trk/MCP#7 ", "TRK/mcp#7"), ("ops/ui-kit#12", "OPS/ui-kit#12")],
)
def test_an_area_decision_ref_is_an_area_address_and_an_entry_number(
    raw: str, expected: str
) -> None:
    assert normalize_decision_ref(raw) == expected
    owner, _, no = expected.partition("#")
    assert split_decision_ref(expected) == (owner, int(no))


@pytest.mark.parametrize(
    "raw",
    ["TRK/mcp#0", "TRK/mcp#007", "TRK/mc_p#1", "TRK/#1", "TRK-1/mcp#2", "T/mcp#1", "TRK/mcp"],
)
def test_a_malformed_area_decision_ref_is_not_a_decision_ref(raw: str) -> None:
    with pytest.raises(FieldProblem) as problem:
        normalize_decision_ref(raw)
    assert problem.value.details["reason"] == "not_a_decision_ref"


# --- Проверка 2: чтение области в форме проекта -------------------------------------------


async def test_get_project_reads_an_area_with_its_knowledge_in_force_and_an_index_without_it(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Проверка 2: A заменена B, C действует. `get_project` по адресу области отдаёт C в
    `decisions`, B в `findings`, A не отдаёт нигде, опись — без решений и заметок, но с
    заметкой `note`; `index_omitted` считает все записи знания, заменённую тоже.
    `in_force=false` отдаёт только A, `in_force=true` — B и C, A по номеру — «заменена → B»."""
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        a = await call(session, "add_project_entry", key="TRK/mcp", type="finding", title="A")
        b = await call(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="finding",
            title="B",
            supersedes=[a["no"]],
        )
        c = await call(session, "add_project_entry", key="TRK/mcp", type="decision", title="C")
        note = await call(session, "add_project_entry", key="TRK/mcp", type="note", title="Нота")
        card = await call(session, "get_project", key="TRK/mcp")
        superseded = await call(session, "read_project_entries", key="TRK/mcp", in_force=False)
        in_force = await call(session, "read_project_entries", key="TRK/mcp", in_force=True)
        by_number = await call(session, "read_project_entries", key="TRK/mcp", nos=[a["no"]])

    assert card["decisions"] == [{"ref": f"TRK/mcp#{c['no']}", "title": "C"}]
    assert card["findings"] == [{"ref": f"TRK/mcp#{b['no']}", "title": "B"}]
    assert f"TRK/mcp#{a['no']}" not in str(card)
    assert [(line["no"], line["type"]) for line in card["index"]] == [
        (1, "created"),
        (note["no"], "note"),
    ]
    assert card["index_omitted"] == {"decision": 1, "finding": 2}
    assert card["areas"] == []
    assert [_standing(item) for item in superseded["items"]] == [(a["no"], "superseded", b["no"])]
    assert [_standing(item) for item in in_force["items"]] == [
        (b["no"], "in_force", None),
        (c["no"], "in_force", None),
    ]
    [old] = by_number["items"]
    assert (old["area"], old["payload"]) == ("TRK/mcp", {"supersedes": []})
    assert _standing(old) == (a["no"], "superseded", b["no"])


async def test_rest_reads_area_entries_with_the_status_mcp_gives(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, project: Project
) -> None:
    """REST `…/areas/{area_key}/entries` и `…/entries/{no}` отдают статус и преемника у
    решения и заметки области, а запись без статуса — с `null`; ответ совпадает с MCP поле
    в поле."""
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        a = await call(session, "add_project_entry", key="TRK/mcp", type="finding", title="A")
        b = await call(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="finding",
            title="B",
            supersedes=[a["no"]],
        )
        from_mcp = await call(session, "read_project_entries", key="TRK/mcp")

    listed = await auth_client.get(AREA_ENTRIES)
    one = await auth_client.get(f"{AREA_ENTRIES}/{a['no']}")

    assert listed.status_code == 200, listed.text
    assert [_standing(item) for item in listed.json()["data"]] == [
        (1, None, None),
        (a["no"], "superseded", b["no"]),
        (b["no"], "in_force", None),
    ]
    assert from_mcp["items"] == without_empty_standing(listed.json()["data"])
    assert one.status_code == 200, one.text
    assert _standing(one.json()["data"]) == (a["no"], "superseded", b["no"])


# --- Проверка 3: решение области в поле задачи и в отборе ---------------------------------


async def test_a_task_cites_an_area_decision_and_search_finds_it_by_that_reference(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Проверка 3: `update_task(decisions=["TRK/mcp#C"])` принимается — в любом регистре
    адреса, — `search_tasks(decision=["TRK/mcp#C"])` находит задачу, `get_task` показывает
    решение области со статусом, а после замены — «заменено → преемник»."""
    key = task.key  # строка задачи гаснет после отказа в той же транзакции теста
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        c = await call(session, "add_project_entry", key="TRK/mcp", type="decision", title="C")
        ref = f"TRK/mcp#{c['no']}"
        updated = await call(
            session, "update_task", key=key, changes={"decisions": [f"trk/MCP#{c['no']}"]}
        )
        found = await call(session, "search_tasks", decision=[ref], fields=["key"])
        by_query = await call(session, "search_tasks", query=f"decision: {ref}", fields=["key"])
        before = await call(session, "get_task", key=key)
        d = await call(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="decision",
            title="D",
            supersedes=[c["no"]],
        )
        after = await call(session, "get_task", key=key)
        history = await call(session, "search_tasks", decision=[ref], fields=["key"])

    assert updated["key"] == key
    assert [item["key"] for item in found["items"]] == [key]
    assert [item["key"] for item in by_query["items"]] == [key]
    assert before["decisions"] == [
        {"ref": ref, "title": "C", "status": "in_force", "superseded_by": None}
    ]
    assert after["decisions"] == [
        {
            "ref": ref,
            "title": "C",
            "status": "superseded",
            "superseded_by": {
                "ref": f"TRK/mcp#{d['no']}",
                "title": "D",
                "status": "in_force",
            },
        }
    ]
    assert [item["key"] for item in history["items"]] == [key]


async def test_an_area_finding_cited_as_a_decision_is_not_a_decision(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Проверка 3: ссылка на заметку области в `decisions` — `task_fields_invalid` с
    причиной `not_a_decision`; несуществующие область, проект и запись называются своими
    причинами — теми же, что у ссылок записи в `refs`."""
    key = task.key  # строка задачи гаснет после отказа в той же транзакции теста
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        fact = await call(session, "add_project_entry", key="TRK/mcp", type="finding", title="Ф")
        not_a_decision = await refuse(
            session,
            "update_task",
            key=key,
            changes={"decisions": [f"TRK/mcp#{fact['no']}"]},
        )
        missing = await refuse(
            session,
            "update_task",
            key=key,
            changes={"decisions": ["TRK/mcp#99", "TRK/nope#1", "NOPE/mcp#1"]},
        )
        unknown_in_search = await refuse(session, "search_tasks", decision=["TRK/nope#1"])

    assert "task_fields_invalid" in not_a_decision
    assert "not_a_decision" in not_a_decision
    assert '"got": "finding"' in not_a_decision
    for reason, ref in (
        ("unknown_entry", "TRK/mcp#99"),
        ("unknown_area", "TRK/nope#1"),
        ("unknown_project", "NOPE/mcp#1"),
    ):
        assert f'"reason": "{reason}"' in missing and f'"ref": "{ref}"' in missing, missing
    assert "decision_not_found" in unknown_in_search


async def test_a_new_reference_to_a_superseded_area_decision_is_refused_with_its_successor(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    """Проверка 3: после замены C решением D новая ссылка на C — `decision_not_in_force`,
    преемник D в `details`; ссылка на D проходит."""
    area = await areas_service.create_area(
        db_session, actor=main_actor, address="TRK/mcp", title="MCP-сервер"
    )
    c = await case_service.append_project_entry(
        db_session, area, actor=main_actor, type="decision", title="C"
    )
    d = await case_service.append_project_entry(
        db_session, area, actor=main_actor, type="decision", title="D", supersedes=[c.no]
    )

    with pytest.raises(DecisionNotInForceError) as refused:
        await tasks_service.update_task(
            db_session,
            task,
            actor=main_actor,
            changes=TaskChanges(decisions=[f"TRK/mcp#{c.no}"]),
        )
    await tasks_service.update_task(
        db_session, task, actor=main_actor, changes=TaskChanges(decisions=[f"TRK/mcp#{d.no}"])
    )

    assert refused.value.details["decisions"] == [
        {"ref": f"TRK/mcp#{c.no}", "superseded_by": f"TRK/mcp#{d.no}"}
    ]
    assert task.decisions == [f"TRK/mcp#{d.no}"]


async def test_supersedes_with_a_number_of_another_case_is_refused(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Проверка 3: `supersedes` называет записи только своего дела. Номер, который есть
    лишь в деле проекта, — `unknown_entry` по адресу области; номер, под которым в соседней
    области заметка, а в этой — решение, сверяется со своим делом — `not_a_finding`."""
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        await call(session, "create_project", key="TRK/ui", title="Интерфейс")
        for title in ("П1", "П2", "П3"):
            await call(session, "add_project_entry", key="TRK", type="finding", title=title)
        project_only = await call(
            session, "add_project_entry", key="TRK", type="finding", title="Заметка проекта"
        )
        decision = await call(
            session, "add_project_entry", key="TRK/mcp", type="decision", title="Решение"
        )
        neighbour = await call(
            session, "add_project_entry", key="TRK/ui", type="finding", title="Заметка соседа"
        )
        foreign_number = await refuse(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="finding",
            title="Мимо",
            supersedes=[project_only["no"]],
        )
        same_number = await refuse(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="finding",
            title="Мимо",
            supersedes=[neighbour["no"]],
        )
        untouched = await call(session, "read_project_entries", key="TRK", in_force=False)

    assert decision["no"] == neighbour["no"]
    assert "entry_fields_invalid" in foreign_number
    assert '"reason": "unknown_entry"' in foreign_number
    assert f'"ref": "TRK/mcp#{project_only["no"]}"' in foreign_number
    assert "entry_fields_invalid" in same_number
    assert "not_a_finding" in same_number
    assert untouched["items"] == []


async def test_the_project_decisions_of_state_leave_area_decisions_out(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Блок `state` называет решения ПРОЕКТА после правки разделов (TRK-643); решения
    области — дело другой сущности, их там нет: задача о них не просила."""
    key = task.key  # строка задачи гаснет после отказа в той же транзакции теста
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        await call(session, "add_project_entry", key="TRK/mcp", type="decision", title="C")
        project_decision = await call(
            session, "add_project_entry", key="TRK", type="decision", title="Решение проекта"
        )
        state = (await call(session, "get_task", key=key, brief=True))["state"]

    assert state["project_decisions_after_card"] == [f"TRK#{project_decision['no']}"]
