"""Черновик знания в деле задачи и признак «не поднято» (TRK-659, решение TRK#57, раздел 8).

Решение или находка дела задачи с адресом подъёма `draft_for` — черновик; поднимает его
запись дела адресата (проекта задачи или его области) со ссылкой на черновик в `refs`.
Признак `open_drafts` — число неподнятых черновиков: в `get_task`, в строке и отборе
`search_tasks`, в REST задачи и списка; у черновика в чтении дела — `lifted_by`.

Обзорные проверки задачи, которые здесь измеряются (задача `X-1` и область `X/mcp`
проверок — `TRK-1` и `TRK/mcp`):

- 2: `test_a_draft_counts_in_open_drafts_until_an_entry_of_its_area_lifts_it`;
- 3: `test_a_draft_address_of_another_project_is_refused`,
  `test_a_draft_address_of_a_missing_or_archived_area_is_refused`,
  `test_a_draft_address_on_a_note_or_an_attempt_is_refused`.
"""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryContext, EntryType, build_entry, read_payload
from app.domain.errors import EntryFieldsInvalidError
from app.services import projects as projects_service
from app.services.auth import Actor
from conftest import Connect, call, move_task, refuse


def _details(refusal: str) -> dict[str, Any]:
    """Подробности отказа инструмента: строка `details: {...}` под `code: message`."""
    _, _, details = refusal.partition("details: ")
    parsed: dict[str, Any] = json.loads(details)
    return parsed


def _draft_problem(refusal: str) -> dict[str, Any]:
    """Замечание к полю `draft_for` из отказа `entry_fields_invalid`."""
    assert "entry_fields_invalid" in refusal, refusal
    [problem] = [item for item in _details(refusal)["fields"] if item["field"] == "draft_for"]
    return problem


def _keys(page: dict[str, Any]) -> list[str]:
    return [item["key"] for item in page["items"]]


_CONTEXT = EntryContext(task_key="TRK-1", checks=["Проверка"])


# --- Домен: форма адреса ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [("TRK", "TRK"), (" trk ", "TRK"), ("TRK/mcp", "TRK/mcp"), ("trk/MCP", "TRK/mcp")],
)
def test_a_draft_address_is_kept_canonical(raw: str, canonical: str) -> None:
    """Адрес ложится в нагрузку каноническим: два написания одного адреса развели бы
    черновик с подъёмом."""
    draft = build_entry(_CONTEXT, type="finding", title="Факт", payload={"draft_for": raw})
    assert draft.payload == {"draft_for": canonical}


@pytest.mark.parametrize("raw", ["", "TRK-1", "TRK#7", "TRK/mc_p", "T", "docs/x.md", "TRK/"])
def test_a_malformed_draft_address_is_not_an_address(raw: str) -> None:
    with pytest.raises(EntryFieldsInvalidError) as refused:
        build_entry(_CONTEXT, type="decision", title="Выбор", payload={"draft_for": raw})
    [problem] = refused.value.details["fields"]
    assert (problem["field"], problem["reason"]) == ("draft_for", "not_an_address")


def test_a_decision_without_an_address_is_no_draft() -> None:
    """Без адреса нагрузки нет, как до черновиков; при чтении ключ стоит `null`, как
    `supersedes: []` у записи задачи (TRK-565: одна форма в REST и MCP)."""
    draft = build_entry(_CONTEXT, type="decision", title="Выбор")
    assert draft.payload == {}
    assert read_payload(EntryType.DECISION, {}) == {"supersedes": [], "draft_for": None}
    assert read_payload(EntryType.FINDING, {"draft_for": "TRK/mcp"}) == {
        "supersedes": [],
        "draft_for": "TRK/mcp",
    }


# --- Проверка 2: признак, отбор, подъём ---------------------------------------------------


async def test_a_draft_counts_in_open_drafts_until_an_entry_of_its_area_lifts_it(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Проверка 2: черновик `finding` в `TRK-1` с адресом `TRK/mcp` — признак 1 в `get_task`,
    отбор по признаку (аргументом и строкой языка) находит задачу, у черновика пустой
    `lifted_by`. После `add_project_entry(key="TRK/mcp", type="finding", refs=["TRK-1#N"])`
    признак 0, отбор задачу не находит, а `lifted_by` называет поднявшую запись."""
    key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        draft = await call(
            session,
            "add_entry",
            key=key,
            type="finding",
            title="Ответ подшивки короче записи",
            draft_for="TRK/mcp",
        )
        before = await call(session, "get_task", key=key)
        by_argument = await call(session, "search_tasks", open_drafts=1)
        by_query = await call(session, "search_tasks", query="open_drafts: > 0")
        [unlifted] = (await call(session, "read_entries", key=key, nos=[draft["no"]]))["items"]

        lift = await call(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="finding",
            title="Ответ подшивки короче записи",
            refs=[f"{key}#{draft['no']}"],
        )
        after = await call(session, "get_task", key=key)
        none_left = await call(session, "search_tasks", query="open_drafts: > 0")
        zero = await call(session, "search_tasks", open_drafts=0)
        [lifted] = (await call(session, "read_entries", key=key, nos=[draft["no"]]))["items"]

    assert before["features"]["open_drafts"] == 1
    assert _keys(by_argument) == [key] == _keys(by_query)
    assert by_argument["items"][0]["features"]["open_drafts"] == 1
    assert unlifted["payload"] == {"supersedes": [], "draft_for": "TRK/mcp"}
    assert unlifted["lifted_by"] == []

    assert after["features"]["open_drafts"] == 0
    assert key not in _keys(none_left)
    assert key in _keys(zero)
    assert lifted["lifted_by"] == [f"TRK/mcp#{lift['no']}"]


async def test_only_an_entry_of_the_addressee_case_lifts_a_draft(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Ссылка на черновик из чужого дела — проекта вместо области, соседней области, другой
    задачи — подъёмом не считается; запись без ссылки в деле адресата — тоже."""
    key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        await call(session, "create_project", key="TRK/db", title="База")
        draft = await call(
            session, "add_entry", key=key, type="decision", title="Выбор", draft_for="TRK/mcp"
        )
        ref = f"{key}#{draft['no']}"
        await call(session, "add_project_entry", key="TRK", type="note", title="Ссылка", refs=[ref])
        await call(
            session, "add_project_entry", key="TRK/db", type="note", title="Ссылка", refs=[ref]
        )
        await call(session, "add_project_entry", key="TRK/mcp", type="decision", title="Без")
        other = await call(
            session,
            "create_task",
            project="TRK",
            area="TRK/core",
            title="Соседняя",
            description="Ссылается на черновик",
        )
        await call(session, "add_entry", key=other["key"], type="note", title="Ссылка", refs=[ref])
        card = await call(session, "get_task", key=key)
        [entry] = (await call(session, "read_entries", key=key, nos=[draft["no"]]))["items"]

    assert card["features"]["open_drafts"] == 1
    assert entry["lifted_by"] == []


async def test_a_draft_that_replaces_a_project_decision_is_lifted_with_supersedes(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Шаг 5 карточки: черновик решения для дела проекта, заменяющий решение проекта,
    поднимается решением с `supersedes` и ссылкой — признак гаснет, прежнее решение
    заменено. Поднимает любая запись адресата, в том числе не того типа."""
    key = task.key
    async with mcp_session(task_secret) as session:
        old = await call(session, "add_project_entry", key="TRK", type="decision", title="Было")
        draft = await call(
            session, "add_entry", key=key, type="decision", title="Стало", draft_for="TRK"
        )
        second = await call(
            session, "add_entry", key=key, type="finding", title="Факт", draft_for="trk"
        )
        counted = (await call(session, "get_task", key=key))["features"]["open_drafts"]
        lift = await call(
            session,
            "add_project_entry",
            key="TRK",
            type="decision",
            title="Стало",
            refs=[f"{key}#{draft['no']}"],
            supersedes=[old["no"]],
        )
        await call(
            session,
            "add_project_entry",
            key="TRK",
            type="note",
            title="Факт поднят заметкой",
            refs=[f"{key}#{second['no']}"],
        )
        card = await call(session, "get_task", key=key)
        decisions = await call(session, "get_project", key="TRK")

    assert counted == 2
    assert card["features"]["open_drafts"] == 0
    assert decisions["decisions"] == [{"ref": f"TRK#{lift['no']}", "title": "Стало"}]


async def test_a_lift_by_the_previous_key_stays_a_lift_after_a_move(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    main_actor: Actor,
    task: Task,
) -> None:
    """Ссылка хранится как написана (TRK#112): подъём прежним ключом остаётся
    подъёмом, когда задача переехала в другой проект и получила новый ключ."""
    old_key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        draft = await call(
            session, "add_entry", key=old_key, type="finding", title="Факт", draft_for="TRK/mcp"
        )
        await call(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="finding",
            title="Факт",
            refs=[f"{old_key}#{draft['no']}"],
        )
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация"
    )
    moved = await move_task(db_session, task, actor=main_actor, project=other, reason="Переезд")
    await db_session.flush()
    async with mcp_session(task_secret) as session:
        card = await call(session, "get_task", key=moved.task.key)
        [entry] = (await call(session, "read_entries", key=moved.task.key, nos=[draft["no"]]))[
            "items"
        ]

    assert moved.task.key != old_key
    assert card["features"]["open_drafts"] == 0
    assert entry["lifted_by"] == ["TRK/mcp#2"]


async def test_closing_files_a_draft_and_does_not_wait_for_its_lift(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Запись закрытия принимает адрес подъёма, как `add_entry`; закрытие признак не держит
    (TRK#22): задача уходит в `done` с неподнятым черновиком и находится отбором."""
    key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "transition", key=key, to="open")
        await call(session, "transition", key=key, to="in_progress")
        closed = await call(
            session,
            "close_task",
            key=key,
            entries=[
                {"type": "decision", "title": "Правило", "draft_for": "TRK"},
                {"type": "artifact", "title": "Ветка task/TRK-1"},
            ],
            verdicts=[{"check_no": 1, "outcome": "passed", "evidence": "тест"}],
            summary={
                "done": "Сделано",
                "remaining": "nothing",
                "blockers": "nothing",
                "next_step": "no steps",
                "unmeasured": "nothing",
            },
        )
        card = await call(session, "get_task", key=key)
        found = await call(session, "search_tasks", query="status: done and open_drafts: > 0")
        [draft] = (await call(session, "read_entries", key=key, types=["decision"]))["items"]

    assert closed["status"] == "done"
    assert card["features"]["open_drafts"] == 1
    assert _keys(found) == [key]
    assert (draft["payload"]["draft_for"], draft["lifted_by"]) == ("TRK", [])


async def test_rest_reads_the_feature_the_filter_and_the_lifts_mcp_gives(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, task: Task
) -> None:
    """REST: признак в пакете задачи и в строке списка, отбор параметром `open_drafts` и
    строкой языка, `lifted_by` и `draft_for` в чтении дела списком и по номеру; запись, не
    черновик, несёт `lifted_by: null`."""
    key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        draft = await call(
            session, "add_entry", key=key, type="finding", title="Факт", draft_for="TRK/mcp"
        )
        plain = await call(session, "add_entry", key=key, type="decision", title="Свой выбор")
        lifted = await call(
            session, "add_entry", key=key, type="decision", title="Выбор", draft_for="TRK/mcp"
        )
        lift = await call(
            session,
            "add_project_entry",
            key="TRK/mcp",
            type="decision",
            title="Выбор",
            refs=[f"{key}#{lifted['no']}"],
        )
        from_mcp = await call(session, "read_entries", key=key, types=["decision", "finding"])

    package = await auth_client.get(f"/api/v1/tasks/{key}")
    listed = await auth_client.get("/api/v1/tasks", params={"open_drafts": 1})
    queried = await auth_client.get("/api/v1/tasks", params={"query": "open_drafts: 0"})
    entries = await auth_client.get(
        f"/api/v1/tasks/{key}/entries", params={"types": ["decision", "finding"]}
    )
    one = await auth_client.get(f"/api/v1/tasks/{key}/entries/{lifted['no']}")

    assert package.status_code == 200, package.text
    assert package.json()["data"]["features"]["open_drafts"] == 1
    assert listed.status_code == 200, listed.text
    assert [row["key"] for row in listed.json()["data"]] == [key]
    assert listed.json()["data"][0]["features"]["open_drafts"] == 1
    assert key not in [row["key"] for row in queried.json()["data"]]
    rows = {item["no"]: item for item in entries.json()["data"]}
    assert (rows[draft["no"]]["payload"]["draft_for"], rows[draft["no"]]["lifted_by"]) == (
        "TRK/mcp",
        [],
    )
    assert rows[lifted["no"]]["lifted_by"] == [f"TRK/mcp#{lift['no']}"]
    assert (rows[plain["no"]]["payload"]["draft_for"], rows[plain["no"]]["lifted_by"]) == (
        None,
        None,
    )
    assert one.json()["data"]["lifted_by"] == [f"TRK/mcp#{lift['no']}"]
    by_no = {item["no"]: item for item in from_mcp["items"]}
    assert "lifted_by" not in by_no[plain["no"]]
    assert by_no[draft["no"]]["lifted_by"] == rows[draft["no"]]["lifted_by"]


# --- Проверка 3: отказы адреса ------------------------------------------------------------


async def test_a_draft_address_of_another_project_is_refused(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    """Проверка 3: адрес чужого проекта и области чужого проекта — `entry_fields_invalid`,
    причина `not_the_task_project`, в `allowed` — проект задачи и его неархивные области."""
    key = task.key
    await projects_service.create_project(db_session, actor=main_actor, key="OPS", title="Ops")
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="OPS/core", title="Ядро OPS")
        project = await refuse(
            session, "add_entry", key=key, type="finding", title="Ф", draft_for="OPS"
        )
        area = await refuse(
            session, "add_entry", key=key, type="decision", title="Решение", draft_for="OPS/core"
        )
        index = await call(session, "get_task", key=key)

    for refusal, got in ((project, "OPS"), (area, "OPS/core")):
        problem = _draft_problem(refusal)
        assert (problem["reason"], problem["got"], problem["project"]) == (
            "not_the_task_project",
            got,
            "TRK",
        )
        assert problem["allowed"] == ["TRK", "TRK/core"]
    assert [line["type"] for line in index["index"]] == ["created"]


async def test_a_draft_address_of_a_missing_or_archived_area_is_refused(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Проверка 3: несуществующая область проекта — `unknown_area`, архивная —
    `area_archived`; архивной области нет и в `allowed`."""
    key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/old", title="Старое")
        await call(session, "archive_project", key="TRK/old", reason="Снята")
        missing = await refuse(
            session, "add_entry", key=key, type="finding", title="Ф", draft_for="TRK/nope"
        )
        archived = await refuse(
            session, "add_entry", key=key, type="finding", title="Ф", draft_for="TRK/old"
        )

    for refusal, reason, got in (
        (missing, "unknown_area", "TRK/nope"),
        (archived, "area_archived", "TRK/old"),
    ):
        problem = _draft_problem(refusal)
        assert (problem["reason"], problem["got"]) == (reason, got)
        assert problem["allowed"] == ["TRK", "TRK/core"]


@pytest.mark.parametrize("entry_type", ["note", "attempt", "artifact", "remark"])
async def test_a_draft_address_on_a_note_or_an_attempt_is_refused(
    mcp_session: Connect, task_secret: str, task: Task, entry_type: str
) -> None:
    """Проверка 3: адрес подъёма у записи не знания — `not_allowed` со списком типов,
    которые его принимают; в деле ничего не подшито."""
    key = task.key
    async with mcp_session(task_secret) as session:
        refusal = await refuse(
            session, "add_entry", key=key, type=entry_type, title="Запись", draft_for="TRK"
        )
        index = await call(session, "get_task", key=key)

    problem = _draft_problem(refusal)
    assert (problem["reason"], problem["allowed_for"]) == ("not_allowed", ["decision", "finding"])
    assert [line["type"] for line in index["index"]] == ["created"]


async def test_a_malformed_draft_address_is_refused_by_the_tool(
    mcp_session: Connect, task_secret: str, project: Project, task: Task
) -> None:
    """Адрес не той формы — `not_an_address` с ожидаемой формой."""
    key = task.key
    async with mcp_session(task_secret) as session:
        refusal = await refuse(
            session, "add_entry", key=key, type="finding", title="Ф", draft_for="docs/x.md"
        )

    problem = _draft_problem(refusal)
    assert (problem["reason"], problem["expected"]) == (
        "not_an_address",
        "<PROJECT> or <PROJECT>/<area key>",
    )
