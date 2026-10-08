"""Записи знания дела проекта (TRK-656, решение TRK#48, раздел 2): замена у заметки
(`finding` с `supersedes`), статус «действует / заменена» с прямым преемником при любом
чтении дела проекта и отбор `in_force`.

Обзорные проверки задачи, которые здесь измеряются:

- 2: заметка B заменяет заметку A — чтение по номеру отдаёт A заменённой с преемником B,
  B действующей, отбор `in_force` убирает A; то же в REST;
- 3: `supersedes` у заметки на решение и у решения на заметку — `entry_fields_invalid`,
  повторная замена заменённой заметки — `finding_not_in_force` с преемником;
- 4: у записи дела задачи статуса нет.

TRK-657 (решение TRK#48, раздел 3), в конце файла:

- 2: опись `get_project` проекта без решений и заметок, действующие — списками ссылкой и
  заголовком, число всех по типам — `index_omitted`;
- 3: отбор `text` у `read_project_entries` и REST чтения дела проекта и области.

Решения проекта, их ссылки из задач и чтение проекта — `tests/test_project_decisions.py`;
та же механика у дела области (TRK-658) — `tests/test_area_knowledge.py`.
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
from app.services.auth import Actor
from conftest import Connect, call, refuse, without_empty_standing

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
    return item["no"], item.get("status"), item.get("superseded_by")


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
    assert {(item["type"], item.get("status")) for item in everything["items"]} == {
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
    assert from_mcp["items"] == without_empty_standing(from_rest.json()["data"])


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


# --- Проверка 4: дело задачи без статуса ----------------------------------------------


async def test_a_task_finding_reads_without_a_status(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """У записи дела задачи статуса нет: решения и находки задач не заменяются."""
    async with mcp_session(task_secret) as session:
        await call(session, "add_entry", key=task.key, type="finding", title="Факт")
        listed = await call(session, "read_entries", key=task.key, types=["finding"])

    [fact] = listed["items"]
    assert (fact.get("status"), fact.get("superseded_by"), fact["payload"]) == (
        None,
        None,
        {"supersedes": []},
    )


async def test_an_entry_without_a_status_carries_neither_status_key_in_mcp(
    mcp_session: Connect, task_secret: str, task: Task, project: Project
) -> None:
    """TRK-665, проверка 2: у записи дела задачи в `read_entries`, `get_task` и
    `wait_journal` нет ключей `status` и `superseded_by`; решение дела проекта в
    `read_project_entries` их несёт, и у действующего `superseded_by` — `null`."""
    async with mcp_session(task_secret) as session:
        await call(session, "add_entry", key=task.key, type="finding", title="Факт")
        await call(
            session,
            "add_summary",
            key=task.key,
            done="Сделано",
            remaining="Остальное",
            blockers="нет",
            next_step="Дальше",
        )
        read = await call(session, "read_entries", key=task.key)
        got = await call(session, "get_task", key=task.key)
        tail = await call(session, "wait_journal", after=0, task=task.key)
        await call(session, "add_project_entry", key=project.key, type="decision", title="Решение")
        kept = await call(session, "read_project_entries", key=project.key, types=["decision"])

    got_entries = [got["summary"]]
    for items in (read["items"], got_entries, tail["items"]):
        assert items
        for item in items:
            assert "status" not in item
            assert "superseded_by" not in item
    [decision] = kept["items"]
    assert (decision["status"], decision["superseded_by"]) == ("in_force", None)


# --- TRK-657: чтение проекта без записей знания в описи и отбор `text` -----------------------


async def test_get_project_lists_knowledge_in_force_and_leaves_it_out_of_the_index(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """TRK-657, проверка 2: в проекте `note`, `decision`, заметка A и заметка B с
    `supersedes=[A]`. Опись `get_project` несёт `note` и ни одного решения и заметки,
    список заметок — B без A, список решений — действующее решение; `index_omitted`
    считает все записи знания вне описи, заменённую тоже."""
    async with mcp_session(task_secret) as session:
        note = await call(session, "add_project_entry", key="TRK", type="note", title="Нота")
        decision = await call(
            session, "add_project_entry", key="TRK", type="decision", title="Решение"
        )
        a = await call(session, "add_project_entry", key="TRK", type="finding", title="A")
        b = await call(
            session, "add_project_entry", key="TRK", type="finding", title="B", supersedes=[a["no"]]
        )
        card = await call(session, "get_project", key="TRK")

    assert [(line["no"], line["type"]) for line in card["index"]] == [
        (1, "created"),
        (note["no"], "note"),
    ]
    assert not {"decision", "finding"} & {line["type"] for line in card["index"]}
    assert card["findings"] == [{"ref": f"TRK#{b['no']}", "title": "B"}]
    assert card["decisions"] == [{"ref": f"TRK#{decision['no']}", "title": "Решение"}]
    assert card["index_omitted"] == {"decision": 1, "finding": 2}


async def _numbers(client: AsyncClient, path: str, **params: Any) -> list[int]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return [item["no"] for item in response.json()["data"]]


async def test_text_finds_a_substring_of_the_title_or_the_body_ignoring_case(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, project: Project
) -> None:
    """TRK-657, проверка 3: `read_project_entries(text=…)` находит запись по слову тела и по
    слову заголовка в другом регистре, складывается с `types` и работает по адресу
    области; то же в REST `GET …/entries?text=…` проекта и области."""
    async with mcp_session(task_secret) as session:
        titled = await call(
            session,
            "add_project_entry",
            key="TRK",
            type="finding",
            title="Триграммный индекс",
            body="Короткие запросы",
        )
        bodied = await call(
            session,
            "add_project_entry",
            key="TRK",
            type="note",
            title="Нота",
            body="План вырождается в последовательное чтение",
        )
        ruled = await call(
            session,
            "add_project_entry",
            key="TRK",
            type="decision",
            title="Решение",
            body="Отбор обходится без индекса",
        )
        await call(session, "create_project", key="TRK/x", title="Популяризация")
        catalogued = await call(
            session,
            "add_project_entry",
            key="TRK/x",
            type="note",
            title="Каталоги",
            body="Подача в Glama",
        )
        await call(session, "add_project_entry", key="TRK/x", type="note", title="Reddit")

        async def found(key: str, **filters: Any) -> list[int]:
            page = await call(session, "read_project_entries", key=key, **filters)
            return [item["no"] for item in page["items"]]

        by_title = await found("TRK", text="ТРИГРАММН")
        by_body = await found("TRK", text="ПОСЛЕДОВАТЕЛЬНОЕ")
        everywhere = await found("TRK", text="Индекс")
        narrowed = await found("TRK", text="индекс", types=["decision"])
        nowhere = await found("TRK", text="100%")
        in_area = await found("TRK/x", text="glama")
        from_mcp = await call(session, "read_project_entries", key="TRK", text="индекс")
        empty = await refuse(session, "read_project_entries", key="TRK", text="")

    assert by_title == [titled["no"]]
    assert by_body == [bodied["no"]]
    assert everywhere == [titled["no"], ruled["no"]]
    assert narrowed == [ruled["no"]]
    # `%` и `_` — буквы подстроки, а не шаблон `LIKE`: «100%» не находит всего подряд.
    assert nowhere == []
    assert in_area == [catalogued["no"]]
    assert "text" in empty

    entries = "/api/v1/projects/TRK/entries"
    assert await _numbers(auth_client, entries, text="ТРИГРАММН") == by_title
    assert await _numbers(auth_client, entries, text="ПОСЛЕДОВАТЕЛЬНОЕ") == by_body
    assert await _numbers(auth_client, entries, text="индекс", types="decision") == narrowed
    assert await _numbers(auth_client, entries, text="100%") == []
    directed = "/api/v1/projects/TRK/areas/x/entries"
    assert await _numbers(auth_client, directed, text="GLAMA") == in_area
    rest = await auth_client.get(entries, params={"text": "индекс"})
    assert from_mcp["items"] == without_empty_standing(rest.json()["data"])
    refused = await auth_client.get(entries, params={"text": ""})
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "validation_error"
