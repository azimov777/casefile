"""Дело проекта (TRK-156): записи с владельцем «проект», номер внутри проекта, ссылка
`TRK#7`, лента и оба интерфейса.

Механика та же, что у дела задачи (`CONCEPT.md`, 3.4), поэтому здесь проверяется только
то, чем дело проекта отличается или где оно встречается с делом задачи: номер считается
внутри проекта и не пересекается с задачами, `seq` общий, набор типов уже, ссылки
проверяются в обе стороны, лента отдаёт записи проекта под отбором `project`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.case import (
    EntryRef,
    EntryType,
    ProjectEntryRef,
    build_project_entry,
    parse_ref,
)
from app.domain.errors import EntryFieldsInvalidError, EntryNotFoundError
from app.domain.fields import FieldProblem
from app.domain.journal import JournalFilter
from app.services import case as service
from app.services import journal as journal_service
from app.services import projects as projects_service
from app.services.auth import Actor
from conftest import Connect, call, refuse
from mcp import ClientSession

ENTRIES = "/api/v1/projects/{key}/entries"


def _problems(error: pytest.ExceptionInfo[Any]) -> list[tuple[str, str]]:
    """Замечания отказа парами «поле — причина», в порядке ответа."""
    return [(item["field"], item["reason"]) for item in error.value.details["fields"]]


async def _note(
    session: AsyncSession, project: Project, actor: Actor, title: str, **extra: Any
) -> Any:
    return await service.append_project_entry(
        session, project, actor=actor, type=EntryType.NOTE, title=title, **extra
    )


@pytest.fixture
async def other_project(db_session: AsyncSession, main_actor: Actor) -> Project:
    """Второй проект: номера записей в нём считаются отдельно от `TRK`."""
    return await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация"
    )


# --- Домен: ссылка `TRK#7` и набор типов --------------------------------------------


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("TRK#7", ProjectEntryRef(key="TRK", no=7)),
        ("trk#7", ProjectEntryRef(key="TRK", no=7)),
        ("TRK-42#3", EntryRef(key="TRK-42", no=3)),
        # Слово с якорем было адресом до дела проекта и им остаётся: хвост не номер.
        ("README#usage", None),
        ("https://example.com/a#1", None),
    ],
)
def test_a_project_entry_reference_is_a_key_without_a_task_number(
    ref: str, expected: ProjectEntryRef | EntryRef | None
) -> None:
    assert parse_ref(ref) == expected


@pytest.mark.parametrize("ref", ["TRK#0", "TRK#007"])
def test_a_near_miss_project_entry_reference_is_refused(ref: str) -> None:
    with pytest.raises(FieldProblem) as problem:
        parse_ref(ref)

    assert problem.value.details["reason"] == "malformed_entry_ref"


def test_a_project_entry_reference_is_stored_canonically() -> None:
    draft = build_project_entry("TRK", type="note", title="Заметка", refs=["trk#3", "TRK#3"])

    assert draft.refs == ["TRK#3"]
    assert draft.tracker_refs == (ProjectEntryRef(key="TRK", no=3),)


# --- Номер, `seq`, служебные записи --------------------------------------------------


async def test_a_new_project_opens_its_case_with_created(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    index = await service.project_case_index(db_session, project, actor=task_actor)

    assert [(line.no, line.type, line.title) for line in index] == [
        (1, EntryType.CREATED, "Project created")
    ]
    assert index[0].author.signature == "owner"


async def test_project_entry_numbers_count_inside_the_project(
    db_session: AsyncSession,
    project: Project,
    other_project: Project,
    task: Task,
    task_actor: Actor,
) -> None:
    """Обзорная проверка 1: `no` с 1 внутри проекта и не пересекается с задачами."""
    first = await _note(db_session, project, task_actor, "Первая заметка TRK")
    other = await _note(db_session, other_project, task_actor, "Первая заметка OPS")
    second = await _note(db_session, project, task_actor, "Вторая заметка TRK")
    task_entry = await service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка задачи"
    )

    # `created` у обоих проектов — №1, заметки идут следом, у каждого своим счётом.
    assert (first.no, second.no, other.no) == (2, 3, 2)
    assert (first.project_id, first.task_id) == (project.id, None)
    # Дело задачи считает своё: `created` задачи — №1, заметка — №2.
    assert (task_entry.no, task_entry.task_id, task_entry.project_id) == (2, task.id, None)


async def test_project_and_task_entries_share_one_seq(
    db_session: AsyncSession, project: Project, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 1: сквозной номер общий — второго журнала нет."""
    one = await _note(db_session, project, task_actor, "Проект")
    two = await service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Задача"
    )
    three = await _note(db_session, project, task_actor, "Снова проект")

    assert one.seq < two.seq < three.seq


@pytest.mark.parametrize(
    ("entry_type", "reason"),
    [
        (EntryType.SUMMARY, "not_allowed"),
        (EntryType.ATTEMPT, "not_allowed"),
        (EntryType.QUESTION, "not_allowed"),
        (EntryType.ANSWER, "not_allowed"),
        (EntryType.VERDICT, "not_allowed"),
        (EntryType.REMARK, "not_allowed"),
        (EntryType.RESOLUTION, "not_allowed"),
        (EntryType.CREATED, "service_type"),
        (EntryType.FIELD_CHANGED, "service_type"),
        (EntryType.STATUS_CHANGED, "service_type"),
    ],
)
async def test_task_types_are_refused_in_a_project_case(
    db_session: AsyncSession,
    project: Project,
    task_actor: Actor,
    entry_type: EntryType,
    reason: str,
) -> None:
    """Обзорная проверка 1: типы задачи и служебные — `entry_fields_invalid`."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        await service.append_project_entry(
            db_session, project, actor=task_actor, type=entry_type, title="Чужой тип"
        )

    assert _problems(error) == [("type", reason)]
    assert error.value.details["fields"][0]["allowed"] == [
        "artifact",
        "decision",
        "finding",
        "note",
    ]
    assert error.value.details["key"] == "TRK"


async def test_every_project_type_is_filed(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    for entry_type in ("note", "decision", "finding", "artifact"):
        entry = await service.append_project_entry(
            db_session, project, actor=task_actor, type=entry_type, title=f"Запись {entry_type}"
        )
        assert entry.type == EntryType(entry_type)
        assert entry.payload == {}


async def test_a_card_edit_files_field_changed_per_changed_field(
    db_session: AsyncSession, project: Project, main_actor: Actor, task_actor: Actor
) -> None:
    await projects_service.update_project(
        db_session, project, actor=main_actor, title="Трекер задач", description="Бэкенд трекера"
    )
    # То же значение второй раз — правки не было, записи нет.
    await projects_service.update_project(
        db_session, project, actor=main_actor, title="Трекер задач"
    )

    page = await service.list_project_entries(
        db_session, project, actor=task_actor, types=[EntryType.FIELD_CHANGED]
    )
    assert [(entry.title, entry.payload) for entry in page.items] == [
        (
            "Field changed: title",
            {"field": "title", "before": "Трекер", "after": "Трекер задач"},
        )
    ]


async def test_one_card_edit_shares_one_action_id(
    db_session: AsyncSession, project: Project, main_actor: Actor, task_actor: Actor
) -> None:
    await projects_service.update_project(
        db_session, project, actor=main_actor, title="Новое", description="Новое описание"
    )

    page = await service.list_project_entries(
        db_session, project, actor=task_actor, types=[EntryType.FIELD_CHANGED]
    )
    assert [entry.payload["field"] for entry in page.items] == ["title", "description"]
    assert len({entry.action_id for entry in page.items}) == 1


async def test_a_missing_project_entry_is_not_found(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    with pytest.raises(EntryNotFoundError) as error:
        await service.read_project_entry(db_session, project, 99, actor=task_actor)

    assert error.value.details == {"key": "TRK", "no": 99}


# --- Ссылки ---------------------------------------------------------------------------


async def test_a_reference_to_a_missing_project_entry_is_refused(
    db_session: AsyncSession, project: Project, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 2: `TRK#7` на несуществующую запись — отказ из обоих дел."""
    with pytest.raises(EntryFieldsInvalidError) as from_task:
        await service.add_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.FINDING,
            title="Нашёл",
            refs=["TRK#7"],
        )
    with pytest.raises(EntryFieldsInvalidError) as from_project:
        await _note(db_session, project, task_actor, "Заметка", refs=["TRK#7", "NOPE#1"])

    assert from_task.value.details["fields"] == [
        {"field": "refs", "reason": "unknown_entry", "ref": "TRK#7"}
    ]
    assert from_project.value.details["fields"] == [
        {"field": "refs", "reason": "unknown_entry", "ref": "TRK#7"},
        {"field": "refs", "reason": "unknown_project", "ref": "NOPE#1"},
    ]


async def test_a_project_entry_reference_is_accepted_from_both_cases(
    db_session: AsyncSession, project: Project, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 2: существующая `TRK#1` принимается из задачи и из проекта,
    а `TRK-1#1` из дела проекта работает как раньше."""
    from_task = await service.add_entry(
        db_session,
        task,
        actor=task_actor,
        type=EntryType.FINDING,
        title="Смотри заведение проекта",
        refs=["trk#1", "README#usage"],
    )
    from_project = await _note(
        db_session, project, task_actor, "Смотри задачу", refs=["TRK#1", "TRK-1#1", "TRK-1"]
    )

    assert from_task.refs == ["TRK#1", "README#usage"]
    assert from_project.refs == ["TRK#1", "TRK-1#1", "TRK-1"]


async def test_a_task_entry_reference_keeps_working_as_before(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 2: `TRK-42#3` — прежняя форма и прежний отказ."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        await service.add_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.NOTE,
            title="Заметка",
            refs=["TRK-1#99"],
        )

    assert error.value.details["fields"] == [
        {"field": "refs", "reason": "unknown_entry", "ref": "TRK-1#99"}
    ]


# --- Лента ----------------------------------------------------------------------------


async def test_the_journal_gives_project_entries_under_the_project_filter(
    db_session: AsyncSession,
    project: Project,
    other_project: Project,
    task: Task,
    task_actor: Actor,
) -> None:
    """Обзорная проверка 3: отбор `project` берёт дело проекта и дела его задач."""
    start = await EntryRepository(db_session).latest_seq()
    mine = await _note(db_session, project, task_actor, "Заметка TRK")
    alien = await _note(db_session, other_project, task_actor, "Заметка OPS")
    task_note = await service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка задачи"
    )

    by_project = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, project="trk"),
        after=start,
    )
    by_task = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, task=task.key),
        after=start,
    )
    everything = await journal_service.read_journal(
        db_session, actor=task_actor, journal_filter=JournalFilter(), after=start
    )

    assert [(i.entry.seq, i.task_key, i.project_key) for i in by_project.items] == [
        (mine.seq, None, "TRK"),
        (task_note.seq, "TRK-1", None),
    ]
    assert [i.entry.seq for i in by_task.items] == [task_note.seq]
    assert [i.entry.seq for i in everything.items] == [mine.seq, alien.seq, task_note.seq]


async def test_the_wait_returns_a_project_entry_at_once(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Ожидание с отбором `project` отдаёт запись проекта; пробуждение оповещением на
    настоящих коммитах — `tests/test_journal_wait.py`."""
    note = await _note(db_session, project, task_actor, "Ждали")

    page = await journal_service.wait_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, project="TRK"),
        after=note.seq - 1,
        wait=5,
    )

    assert [(i.entry.seq, i.project_key) for i in page.items] == [(note.seq, "TRK")]


# --- REST -----------------------------------------------------------------------------


async def test_rest_files_and_reads_a_project_entry(
    auth_client: AsyncClient, project: Project
) -> None:
    created = await auth_client.post(
        ENTRIES.format(key="trk"),
        json={"type": "decision", "title": "Главная ветка — main", "refs": ["TRK#1"]},
        headers={"Idempotency-Key": "c0ffee00-0000-4000-8000-000000000001"},
    )
    assert created.status_code == 201, created.text
    entry = created.json()["data"]
    assert (entry["no"], entry["type"], entry["task_key"], entry["project_key"]) == (
        2,
        "decision",
        None,
        "TRK",
    )
    assert entry["refs"] == ["TRK#1"]

    listed = await auth_client.get(ENTRIES.format(key="TRK"), params={"types": ["decision"]})
    assert listed.status_code == 200
    assert [item["no"] for item in listed.json()["data"]] == [2]

    one = await auth_client.get(ENTRIES.format(key="TRK") + "/1")
    assert one.status_code == 200
    assert one.json()["data"]["type"] == "created"

    missing = await auth_client.get(ENTRIES.format(key="TRK") + "/99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "entry_not_found"


async def test_rest_repeats_a_filing_by_its_idempotency_key(
    auth_client: AsyncClient, project: Project
) -> None:
    body = {"type": "note", "title": "Заметка"}
    headers = {"Idempotency-Key": "c0ffee00-0000-4000-8000-000000000002"}
    first = await auth_client.post(ENTRIES.format(key="TRK"), json=body, headers=headers)
    second = await auth_client.post(ENTRIES.format(key="TRK"), json=body, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


async def test_rest_refuses_a_task_type_and_a_missing_reference(
    auth_client: AsyncClient, project: Project
) -> None:
    """Тип задачи отсекает схема (набор объявлен в ней), ссылку — сценарий."""
    task_type = await auth_client.post(
        ENTRIES.format(key="TRK"),
        json={"type": "summary", "title": "Сводка"},
        headers={"Idempotency-Key": "c0ffee00-0000-4000-8000-000000000003"},
    )
    missing_ref = await auth_client.post(
        ENTRIES.format(key="TRK"),
        json={"type": "note", "title": "Заметка", "refs": ["TRK#9"]},
        headers={"Idempotency-Key": "c0ffee00-0000-4000-8000-000000000004"},
    )

    assert task_type.status_code == 422
    assert task_type.json()["error"]["code"] == "validation_error"
    assert missing_ref.status_code == 422
    assert missing_ref.json()["error"]["code"] == "entry_fields_invalid"


async def test_rest_journal_carries_the_owner_of_each_entry(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    task: Task,
    task_actor: Actor,
) -> None:
    note = await _note(db_session, project, task_actor, "Заметка проекта")

    response = await auth_client.get(
        "/api/v1/journal", params={"after": note.seq - 1, "project": "TRK"}
    )

    assert response.status_code == 200
    assert [
        (item["seq"], item["task_key"], item["project_key"]) for item in response.json()["data"]
    ] == [(note.seq, None, "TRK")]


# --- MCP ------------------------------------------------------------------------------


async def test_a_task_token_files_and_reads_a_project_case(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Обзорная проверка 4: набор `task` подшивает, `get_project` отдаёт опись,
    `read_project_entries` — тела."""
    async with mcp_session(task_secret) as session:
        filed = await call(
            session,
            "add_project_entry",
            key="trk",
            type="finding",
            title="Репозиторий — github.com/azimov777/casefile",
            body="Проверено по `git remote -v`",
            refs=["TRK#1"],
        )
        card = await call(session, "get_project", key="TRK")
        bodies = await call(session, "read_project_entries", key="TRK", nos=[filed["no"]])

    assert set(filed) == {"no", "seq", "project_key", "author", "created_at"}
    assert (filed["no"], filed["project_key"]) == (2, "TRK")
    assert [(line["no"], line["type"]) for line in card["index"]] == [
        (1, "created"),
        (2, "finding"),
    ]
    [entry] = bodies["items"]
    assert (entry["body"], entry["task_key"], entry["project_key"]) == (
        "Проверено по `git remote -v`",
        None,
        "TRK",
    )


async def test_the_mcp_tool_refuses_a_task_type(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session, "add_project_entry", key="TRK", type="summary", title="Сводка"
        )

    assert "summary" in failure


async def test_the_mcp_filing_repeats_by_its_idempotency_key(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        arguments = {
            "key": "TRK",
            "type": "note",
            "title": "Заметка",
            "idempotency_key": "c0ffee00-0000-4000-8000-000000000005",
        }
        first = await call(session, "add_project_entry", **arguments)
        second = await call(session, "add_project_entry", **arguments)
        listed = await call(session, "read_project_entries", key="TRK", types=["note"])

    assert first == second
    assert len(listed["items"]) == 1


async def test_wait_journal_gives_the_project_entry_with_its_owner(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        filed = await call(session, "add_project_entry", key="TRK", type="note", title="Нота")
        page = await call(session, "wait_journal", after=filed["seq"] - 1, project="TRK")

    assert [(item["seq"], item["task_key"], item["project_key"]) for item in page["items"]] == [
        (filed["seq"], None, "TRK")
    ]


async def _tool_names(session: ClientSession) -> set[str]:
    return {tool.name for tool in (await session.list_tools()).tools}


async def test_both_project_case_tools_are_in_the_task_set(
    mcp_session: Connect, task_secret: str
) -> None:
    """Обзорная проверка 4: `tools/list` набора `task` показывает оба инструмента."""
    async with mcp_session(task_secret) as session:
        names = await _tool_names(session)

    assert {"add_project_entry", "read_project_entries"} <= names
