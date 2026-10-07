"""Записи знания дела проекта (TRK-656, решение TRK#48, раздел 2): замена у заметки
(`finding` с `supersedes`), статус «действует / заменена» с прямым преемником при любом
чтении дела проекта и отбор `in_force`.

Обзорные проверки задачи, которые здесь измеряются:

- 2: заметка B заменяет заметку A — чтение по номеру отдаёт A заменённой с преемником B,
  B действующей, отбор `in_force` убирает A; то же в REST;
- 3: `supersedes` у заметки на решение и у решения на заметку — `entry_fields_invalid`,
  повторная замена заменённой заметки — `finding_not_in_force` с преемником;
- 4: `supersedes` в деле направления — по-прежнему `entry_fields_invalid`.

Решения проекта, их ссылки из задач и чтение проекта — `tests/test_project_decisions.py`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType, build_project_entry, read_payload
from app.domain.decisions import successors
from app.domain.errors import EntryFieldsInvalidError, FindingNotInForceError
from app.services import case as case_service
from app.services import directions as directions_service
from app.services.auth import Actor
from conftest import Connect, call, refuse

ENTRIES = "/api/v1/projects/TRK/entries"


async def _file(
    session: AsyncSession,
    project: Project,
    actor: Actor,
    entry_type: EntryType,
    title: str,
    *,
    supersedes: list[int] | None = None,
) -> int:
    entry = await case_service.append_project_entry(
        session, project, actor=actor, type=entry_type, title=title, supersedes=supersedes
    )
    return entry.no


def _standing(item: dict[str, Any]) -> tuple[int, str | None, int | None]:
    return item["no"], item["status"], item["superseded_by"]


# --- Домен -------------------------------------------------------------------------------


def test_an_entry_supersedes_only_an_earlier_entry_of_its_own_type() -> None:
    d, f = EntryType.DECISION, EntryType.FINDING
    assert successors([(1, f, []), (2, f, [1]), (3, d, []), (4, d, [3])]) == {1: 2, 3: 4}
    # Номер чужого типа в данных — обход проверки, а не замена: статус он не меняет.
    assert successors([(1, d, []), (2, f, [1])]) == {}


def test_supersedes_lives_on_a_finding_too_and_is_kept_even_empty() -> None:
    replacing = build_project_entry("TRK", type="finding", title="Факт", supersedes=[4, 2])
    plain = build_project_entry("TRK", type="finding", title="Факт")
    assert (replacing.payload, plain.payload) == ({"supersedes": [2, 4]}, {"supersedes": []})
    # Заметка задачи и заметка, подшитая до TRK-656, читаются с пустым списком: форма одна.
    assert read_payload(EntryType.FINDING, {}) == {"supersedes": []}


# --- Проверка 2: замена заметки и статус при чтении ---------------------------------------


async def test_a_finding_superseded_by_a_finding_reads_with_its_successor_through_mcp(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Проверка 2 (MCP): A заменена B — по номеру видно «заменена → B», B действует,
    `in_force=true` A не отдаёт, `in_force=false` отдаёт только её."""
    async with mcp_session(task_secret) as session:
        a = await call(session, "add_project_entry", key="TRK", type="finding", title="A")
        b = await call(
            session, "add_project_entry", key="TRK", type="finding", title="B", supersedes=[a["no"]]
        )
        decision = await call(
            session, "add_project_entry", key="TRK", type="decision", title="Решение"
        )
        await call(session, "add_project_entry", key="TRK", type="note", title="Нота")
        by_number = await call(session, "read_project_entries", key="TRK", nos=[a["no"]])
        successor = await call(session, "read_project_entries", key="TRK", nos=[b["no"]])
        in_force = await call(session, "read_project_entries", key="TRK", in_force=True)
        superseded = await call(session, "read_project_entries", key="TRK", in_force=False)
        everything = await call(session, "read_project_entries", key="TRK")

    [old] = by_number["items"]
    assert _standing(old) == (a["no"], "superseded", b["no"])
    [new] = successor["items"]
    assert _standing(new) == (b["no"], "in_force", None)
    assert new["payload"] == {"supersedes": [a["no"]]}
    assert [_standing(item) for item in in_force["items"]] == [
        (b["no"], "in_force", None),
        (decision["no"], "in_force", None),
    ]
    assert [item["no"] for item in superseded["items"]] == [a["no"]]
    # Записи без статуса — служебная `created` и заметка `note` — приходят с `null`.
    assert {(item["type"], item["status"]) for item in everything["items"]} == {
        ("created", None),
        ("finding", "superseded"),
        ("finding", "in_force"),
        ("decision", "in_force"),
        ("note", None),
    }


async def test_a_finding_superseded_by_a_finding_reads_the_same_through_rest(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, project: Project
) -> None:
    """Проверка 2 (REST): то же в `GET /projects/{key}/entries` — по номеру, списком, отбором
    `in_force` и одной записью; ответ REST совпадает с MCP поле в поле."""
    a = (await auth_client.post(ENTRIES, json={"type": "finding", "title": "A"})).json()["data"]
    created = await auth_client.post(
        ENTRIES, json={"type": "finding", "title": "B", "supersedes": [a["no"]]}
    )
    assert created.status_code == 201, created.text
    b = created.json()["data"]
    # Ответ подшивки статус не считает: он сохраняется ключом идемпотентности и устарел бы.
    assert (b["status"], b["superseded_by"], b["payload"]) == (
        None,
        None,
        {"supersedes": [a["no"]]},
    )

    by_number = await auth_client.get(ENTRIES, params={"nos": [a["no"]]})
    assert by_number.status_code == 200, by_number.text
    assert [_standing(item) for item in by_number.json()["data"]] == [
        (a["no"], "superseded", b["no"])
    ]
    one = (await auth_client.get(f"{ENTRIES}/{b['no']}")).json()["data"]
    assert _standing(one) == (b["no"], "in_force", None)
    in_force = await auth_client.get(ENTRIES, params={"in_force": "true"})
    assert [item["no"] for item in in_force.json()["data"]] == [b["no"]]
    superseded = await auth_client.get(ENTRIES, params={"in_force": "false"})
    assert [item["no"] for item in superseded.json()["data"]] == [a["no"]]

    async with mcp_session(task_secret) as session:
        from_mcp = await call(session, "read_project_entries", key="TRK")
    from_rest = await auth_client.get(ENTRIES)
    assert from_mcp["items"] == from_rest.json()["data"]


async def test_in_force_combines_with_the_other_filters(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """`in_force` складывается с `types`, `nos` и `after_no` по «и», страницы по курсору
    не теряют записей."""
    first = await _file(db_session, project, main_actor, EntryType.DECISION, "Решение 1")
    second = await _file(
        db_session, project, main_actor, EntryType.DECISION, "Решение 2", supersedes=[first]
    )
    fact = await _file(db_session, project, main_actor, EntryType.FINDING, "Ф1")
    later = await _file(db_session, project, main_actor, EntryType.FINDING, "Ф2")

    async def nos(**filters: Any) -> list[int]:
        page = await case_service.list_project_entries(
            db_session, project, actor=main_actor, **filters
        )
        return [item.no for item in page.items]

    assert await nos(in_force=True, types=[EntryType.FINDING]) == [fact, later]
    assert await nos(in_force=True, types=[EntryType.NOTE]) == []
    assert await nos(in_force=True, nos=[first, second]) == [second]
    assert await nos(in_force=True, after_no=second) == [fact, later]
    assert await nos(in_force=False, types=[EntryType.FINDING]) == []
    assert await nos(in_force=False, nos=[first, fact]) == [first]

    first_page = await case_service.list_project_entries(
        db_session, project, actor=main_actor, in_force=True, limit=1
    )
    assert [item.no for item in first_page.items] == [second]
    rest = await case_service.list_project_entries(
        db_session, project, actor=main_actor, in_force=True, cursor=first_page.next_cursor
    )
    assert [item.no for item in rest.items] == [fact, later]


# --- Проверка 3: отказы замены ------------------------------------------------------------


async def test_supersedes_names_only_entries_of_the_same_type(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Проверка 3: заметка не заменяет решение, решение — заметку: `entry_fields_invalid`
    с причиной по ожидаемому типу."""
    async with mcp_session(task_secret) as session:
        decision = await call(
            session, "add_project_entry", key="TRK", type="decision", title="Решение"
        )
        fact = await call(session, "add_project_entry", key="TRK", type="finding", title="Ф")
        finding_over_decision = await refuse(
            session,
            "add_project_entry",
            key="TRK",
            type="finding",
            title="Ф2",
            supersedes=[decision["no"]],
        )
        decision_over_finding = await refuse(
            session,
            "add_project_entry",
            key="TRK",
            type="decision",
            title="Решение 2",
            supersedes=[fact["no"]],
        )
        untouched = await call(session, "read_project_entries", key="TRK", in_force=True)

    assert "entry_fields_invalid" in finding_over_decision
    assert "not_a_finding" in finding_over_decision
    assert "entry_fields_invalid" in decision_over_finding
    assert "not_a_decision" in decision_over_finding
    assert [_standing(item) for item in untouched["items"]] == [
        (decision["no"], "in_force", None),
        (fact["no"], "in_force", None),
    ]


async def test_a_superseded_finding_is_not_superseded_twice(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Проверка 3: повторная замена заменённой заметки — отказ с преемником в `details`."""
    first = await _file(db_session, project, main_actor, EntryType.FINDING, "Первая")
    second = await _file(
        db_session, project, main_actor, EntryType.FINDING, "Вторая", supersedes=[first]
    )

    with pytest.raises(FindingNotInForceError) as refused:
        await _file(
            db_session, project, main_actor, EntryType.FINDING, "Третья", supersedes=[first]
        )

    assert refused.value.code == "finding_not_in_force"
    assert refused.value.details == {
        "findings": [{"ref": f"TRK#{first}", "superseded_by": f"TRK#{second}"}],
        "key": "TRK",
    }


async def test_rest_and_mcp_refuse_a_second_replacement_of_a_finding(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, project: Project
) -> None:
    """Проверка 3 в обеих дверях: `409 finding_not_in_force` и тот же код в MCP."""
    a = (await auth_client.post(ENTRIES, json={"type": "finding", "title": "A"})).json()["data"]
    b = await auth_client.post(
        ENTRIES, json={"type": "finding", "title": "B", "supersedes": [a["no"]]}
    )
    assert b.status_code == 201, b.text
    again = await auth_client.post(
        ENTRIES, json={"type": "finding", "title": "C", "supersedes": [a["no"]]}
    )
    assert again.status_code == 409, again.text
    error = again.json()["error"]
    assert error["code"] == "finding_not_in_force"
    assert error["details"]["findings"] == [
        {"ref": f"TRK#{a['no']}", "superseded_by": f"TRK#{b.json()['data']['no']}"}
    ]

    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "add_project_entry",
            key="TRK",
            type="finding",
            title="C",
            supersedes=[a["no"]],
        )
    assert "finding_not_in_force" in failure
    assert f"TRK#{b.json()['data']['no']}" in failure


async def test_supersedes_on_an_artifact_names_both_replaceable_types(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    fact = await _file(db_session, project, main_actor, EntryType.FINDING, "Ф")
    with pytest.raises(EntryFieldsInvalidError) as refused:
        await _file(
            db_session, project, main_actor, EntryType.ARTIFACT, "Артефакт", supersedes=[fact]
        )
    [problem] = refused.value.details["fields"]
    assert (problem["reason"], problem["allowed_for"]) == ("not_allowed", ["decision", "finding"])


# --- Проверка 4: дело направления и дело задачи без статуса -------------------------------


async def test_a_direction_case_keeps_refusing_supersedes_and_has_no_status(
    mcp_session: Connect,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    task_secret: str,
    project: Project,
    main_actor: Actor,
) -> None:
    """Проверка 4: `supersedes` у заметки направления — `entry_fields_invalid`; записи
    направления читаются без статуса, и отбор `in_force` их не отдаёт."""
    await directions_service.create_direction(
        db_session, actor=main_actor, address="TRK/x", title="X"
    )
    async with mcp_session(task_secret) as session:
        fact = await call(session, "add_project_entry", key="TRK/x", type="finding", title="Ф")
        refused = await refuse(
            session,
            "add_project_entry",
            key="TRK/x",
            type="finding",
            title="Ф2",
            supersedes=[fact["no"]],
        )
        listed = await call(session, "read_project_entries", key="TRK/x")
        in_force = await call(session, "read_project_entries", key="TRK/x", in_force=True)

    assert "entry_fields_invalid" in refused
    assert "supersedes" in refused
    assert {(item["status"], item["superseded_by"]) for item in listed["items"]} == {(None, None)}
    assert in_force["items"] == []
    rest = await auth_client.get(f"/api/v1/projects/TRK/directions/x/entries/{fact['no']}")
    assert rest.status_code == 200, rest.text
    assert (rest.json()["data"]["status"], rest.json()["data"]["payload"]) == (
        None,
        {"supersedes": []},
    )


async def test_a_task_finding_reads_without_a_status(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """У записи дела задачи статуса нет: решения и находки задач не заменяются."""
    async with mcp_session(task_secret) as session:
        await call(session, "add_entry", key=task.key, type="finding", title="Факт")
        listed = await call(session, "read_entries", key=task.key, types=["finding"])

    [fact] = listed["items"]
    assert (fact["status"], fact["superseded_by"], fact["payload"]) == (
        None,
        None,
        {"supersedes": []},
    )
