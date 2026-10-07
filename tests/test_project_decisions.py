"""Решения проекта (TRK-554): замена через `supersedes`, статус при чтении, поле `decisions`
у задачи, обратный путь отбором `decision:` и правило против «слухов».

Концепция — `CONCEPT.md`, 3.2 и 3.3; решение владельца — `TRK-554#6`, разбор — `TRK-554#12`.
Обзорные проверки задачи, которые здесь измеряются:

- 2(а): после замены `get_task` у задачи со ссылкой на старое решение, в том числе
  закрытой, показывает «заменено» с преемником;
- 2(б): новая ссылка на заменённое решение отклоняется `decision_not_in_force`;
- 6 (история): отбор `decision: TRK#N` находит задачи, ссылавшиеся на заменённое решение,
  включая закрытую; неизвестное решение — отказ, а не пустая выдача;
- 7 («слухи»): ссылка на запись задачи — `task_entry`, на заметку проекта — `not_a_decision`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType, build_project_entry
from app.domain.decisions import DecisionStatus, successors
from app.domain.errors import (
    DecisionNotInForceError,
    EntryFieldsInvalidError,
    SearchValueInvalidError,
    TaskClosedError,
    TaskFieldsInvalidError,
)
from app.domain.fields import FieldProblem
from app.domain.tasks import TaskStatus, normalize_decision_ref
from app.services import case as case_service
from app.services import decisions as decisions_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges
from conftest import Connect, call, refuse

# --- Помощники ---------------------------------------------------------------------------


async def _decision(
    session: AsyncSession,
    project: Project,
    actor: Actor,
    title: str,
    *,
    supersedes: list[int] | None = None,
) -> int:
    """Подшивает решение проекта и возвращает его номер."""
    entry = await case_service.append_project_entry(
        session,
        project,
        actor=actor,
        type=EntryType.DECISION,
        title=title,
        body="Почему так",
        supersedes=supersedes,
    )
    return entry.no


async def _task(
    session: AsyncSession, project: Project, actor: Actor, title: str, decisions: list[str]
) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        project=project,
        title=title,
        description="Задача по решению",
        decisions=decisions,
    )


async def _cancel(session: AsyncSession, task: Task, actor: Actor) -> None:
    """Закрывает задачу без результата: из `backlog` отмена идёт с причиной и без сводки."""
    await tasks_service.transition_task(
        session, task, actor=actor, to=TaskStatus.CANCELLED, reason="Больше не нужна"
    )


def _reasons(error: pytest.ExceptionInfo[Any]) -> list[tuple[str, str]]:
    return [(item["field"], item["reason"]) for item in error.value.details["fields"]]


# --- Домен -------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [("TRK#15", "TRK#15"), (" trk#7 ", "TRK#7")])
def test_a_decision_ref_is_a_project_key_and_an_entry_number(raw: str, expected: str) -> None:
    assert normalize_decision_ref(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("TRK-42#7", "task_entry"),
        ("trk-1#2", "task_entry"),
        ("TRK-42", "not_a_decision_ref"),
        ("TRK", "not_a_decision_ref"),
        ("TRK#0", "not_a_decision_ref"),
        ("TRK#007", "not_a_decision_ref"),
        ("https://example.com/#1", "not_a_decision_ref"),
        ("", "empty_item"),
    ],
)
def test_anything_but_a_project_entry_is_not_a_decision_ref(raw: str, reason: str) -> None:
    """«Слухи»: запись задачи отвергается своей причиной, а не общей «не та форма»."""
    with pytest.raises(FieldProblem) as problem:
        normalize_decision_ref(raw)
    assert problem.value.details["reason"] == reason


def test_a_successor_is_the_decision_that_named_the_earlier_one() -> None:
    d = EntryType.DECISION
    assert successors([(1, d, []), (2, d, [1]), (3, d, [2]), (4, d, [])]) == {1: 2, 2: 3}
    # Обход проверки (два преемника) не делает статус случайным: побеждает более раннее.
    assert successors([(1, d, []), (5, d, [1]), (4, d, [1])]) == {1: 4}
    # Ссылка вперёд — не замена: заменить можно только более раннее решение.
    assert successors([(1, d, [2]), (2, d, [])]) == {}


def test_supersedes_lives_only_on_a_decision_and_is_kept_even_empty() -> None:
    decision = build_project_entry("TRK", type="decision", title="Решение", supersedes=[3, 1, 3])
    plain = build_project_entry("TRK", type="decision", title="Решение")
    assert decision.payload == {"supersedes": [1, 3]}
    assert plain.payload == {"supersedes": []}

    with pytest.raises(EntryFieldsInvalidError) as refused:
        build_project_entry("TRK", type="note", title="Заметка", supersedes=[1])
    assert _reasons(refused) == [("supersedes", "not_allowed")]
    assert refused.value.details["fields"][0]["allowed_for"] == ["decision", "finding"]


# --- Замена решения ----------------------------------------------------------------------


async def test_a_later_decision_supersedes_and_the_status_is_computed_on_read(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    first = await _decision(db_session, project, main_actor, "Берём PostgreSQL")
    second = await _decision(
        db_session, project, main_actor, "Берём PostgreSQL 18", supersedes=[first]
    )

    decisions = await decisions_service.project_decisions(db_session, project, actor=main_actor)

    assert [(item.entry.no, item.status) for item in decisions] == [
        (first, DecisionStatus.SUPERSEDED),
        (second, DecisionStatus.IN_FORCE),
    ]
    assert decisions[0].superseded_by is not None
    assert decisions[0].superseded_by.no == second
    assert decisions[1].supersedes == (first,)
    knowledge = await decisions_service.case_knowledge(db_session, project, actor=main_actor)
    assert [item.ref for item in knowledge.decisions] == [f"TRK#{second}"]
    assert knowledge.totals == {EntryType.DECISION: 2, EntryType.FINDING: 0}


async def test_a_superseded_decision_is_not_superseded_twice(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    first = await _decision(db_session, project, main_actor, "Первое")
    second = await _decision(db_session, project, main_actor, "Второе", supersedes=[first])

    with pytest.raises(DecisionNotInForceError) as refused:
        await _decision(db_session, project, main_actor, "Третье", supersedes=[first])

    assert refused.value.code == "decision_not_in_force"
    assert refused.value.details["decisions"] == [
        {"ref": f"TRK#{first}", "superseded_by": f"TRK#{second}"}
    ]


async def test_supersedes_names_only_decisions_of_the_same_project_case(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    note = await case_service.append_project_entry(
        db_session, project, actor=main_actor, type=EntryType.NOTE, title="Заметка"
    )

    with pytest.raises(EntryFieldsInvalidError) as refused:
        await _decision(db_session, project, main_actor, "Решение", supersedes=[note.no, 99])

    assert _reasons(refused) == [("supersedes", "not_a_decision"), ("supersedes", "unknown_entry")]


# --- Ссылки задачи: проверка 2 ------------------------------------------------------------


async def test_a_task_citing_a_superseded_decision_shows_it_with_its_successor(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Проверка 2(а): открытая и закрытая задача видят «заменено» с преемником без правки."""
    old = await _decision(db_session, project, main_actor, "Сервис не строим")
    still_open = await _task(db_session, project, main_actor, "Открытая", [f"TRK#{old}"])
    closed = await _task(db_session, project, main_actor, "Закрытая", [f"TRK#{old}"])
    await _cancel(db_session, closed, main_actor)
    new = await _decision(db_session, project, main_actor, "Сервис строим", supersedes=[old])

    for task in (still_open, closed):
        package = await tasks_service.read_task_package(db_session, task.key, actor=main_actor)
        (cited,) = package.decisions
        assert (cited.ref, cited.status) == (f"TRK#{old}", DecisionStatus.SUPERSEDED)
        assert cited.superseded_by is not None
        assert (cited.superseded_by.ref, cited.superseded_by.status) == (
            f"TRK#{new}",
            DecisionStatus.IN_FORCE,
        )
        assert cited.superseded_by.title == "Сервис строим"
    assert closed.status is TaskStatus.CANCELLED


async def test_a_new_reference_to_a_superseded_decision_is_refused_with_the_successor(
    db_session: AsyncSession, project: Project, main_actor: Actor, task: Task
) -> None:
    """Проверка 2(б): и при создании, и при правке — `decision_not_in_force`."""
    old = await _decision(db_session, project, main_actor, "Старое")
    new = await _decision(db_session, project, main_actor, "Новое", supersedes=[old])

    with pytest.raises(DecisionNotInForceError) as on_create:
        await _task(db_session, project, main_actor, "Новая задача", [f"TRK#{old}"])
    with pytest.raises(DecisionNotInForceError) as on_update:
        await tasks_service.update_task(
            db_session, task, actor=main_actor, changes=TaskChanges(decisions=[f"TRK#{old}"])
        )

    expected = [{"ref": f"TRK#{old}", "superseded_by": f"TRK#{new}"}]
    assert on_create.value.details["decisions"] == expected
    assert on_update.value.details == {"key": task.key, "decisions": expected}


async def test_a_reference_already_in_the_field_stays_after_its_decision_is_superseded(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Ссылка — история задачи: правка поля не требует снимать стоявшую ссылку."""
    old = await _decision(db_session, project, main_actor, "Старое")
    task = await _task(db_session, project, main_actor, "Задача", [f"TRK#{old}"])
    new = await _decision(db_session, project, main_actor, "Новое", supersedes=[old])

    changed = await tasks_service.update_task(
        db_session,
        task,
        actor=main_actor,
        changes=TaskChanges(decisions=[f"TRK#{old}", f"trk#{new}"]),
    )

    assert changed.task.decisions == [f"TRK#{old}", f"TRK#{new}"]
    (entry,) = (
        await case_service.list_entries(
            db_session, task, actor=main_actor, types=[EntryType.FIELD_CHANGED]
        )
    ).items
    assert entry.payload == {
        "field": "decisions",
        "before": [f"TRK#{old}"],
        "after": [f"TRK#{old}", f"TRK#{new}"],
    }


async def test_a_closed_task_keeps_its_decisions(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    first = await _decision(db_session, project, main_actor, "Решение")
    task = await _task(db_session, project, main_actor, "Задача", [f"TRK#{first}"])
    await _cancel(db_session, task, main_actor)

    with pytest.raises(TaskClosedError):
        await tasks_service.update_task(
            db_session, task, actor=main_actor, changes=TaskChanges(decisions=[])
        )


# --- «Слухи»: проверка 7 ------------------------------------------------------------------


async def test_only_a_decision_of_a_project_case_is_a_decision_of_a_task(
    db_session: AsyncSession, project: Project, main_actor: Actor, task: Task
) -> None:
    """Проверка 7: решение другой задачи и заметка проекта решениями не становятся."""
    task_decision = await case_service.add_entry(
        db_session, task, actor=main_actor, type=EntryType.DECISION, title="Решение задачи"
    )
    note = await case_service.append_project_entry(
        db_session, project, actor=main_actor, type=EntryType.NOTE, title="Практика"
    )

    with pytest.raises(TaskFieldsInvalidError) as rumour:
        await _task(db_session, project, main_actor, "Слух", [f"{task.key}#{task_decision.no}"])
    with pytest.raises(TaskFieldsInvalidError) as practice:
        await _task(db_session, project, main_actor, "Практика", [f"TRK#{note.no}"])
    with pytest.raises(TaskFieldsInvalidError) as missing:
        await _task(db_session, project, main_actor, "Опечатка", ["TRK#99", "NOPE#1"])

    assert _reasons(rumour) == [("decisions", "task_entry")]
    assert _reasons(practice) == [("decisions", "not_a_decision")]
    assert _reasons(missing) == [("decisions", "unknown_entry"), ("decisions", "unknown_project")]


async def test_a_refused_reference_does_not_burn_a_task_number(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    with pytest.raises(TaskFieldsInvalidError):
        await _task(db_session, project, main_actor, "Опечатка", ["TRK#99"])

    created = await _task(db_session, project, main_actor, "Следующая", [])

    assert created.key == "TRK-1"


async def test_a_decision_of_another_project_is_cited_like_its_own(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация"
    )
    foreign = await _decision(db_session, other, main_actor, "Деплой только по тегу")

    task = await _task(db_session, project, main_actor, "Задача", [f"ops#{foreign}"])

    package = await tasks_service.read_task_package(db_session, task.key, actor=main_actor)
    assert [(item.ref, item.title) for item in package.decisions] == [
        (f"OPS#{foreign}", "Деплой только по тегу")
    ]


# --- История: проверка 6 -----------------------------------------------------------------


async def test_the_tasks_done_under_a_superseded_decision_are_found_by_it(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Проверка 6: обратный путь от решения к задачам — язык запросов и структурный отбор."""
    old = await _decision(db_session, project, main_actor, "Старое")
    done_under_old = await _task(db_session, project, main_actor, "Сделано", [f"TRK#{old}"])
    await _cancel(db_session, done_under_old, main_actor)
    open_under_old = await _task(db_session, project, main_actor, "Идёт", [f"TRK#{old}"])
    new = await _decision(db_session, project, main_actor, "Новое", supersedes=[old])
    under_new = await _task(db_session, project, main_actor, "По новому", [f"TRK#{new}"])
    without = await _task(db_session, project, main_actor, "Без решений", [])

    async def keys(**search: Any) -> list[str]:
        outcome = await search_service.search_tasks(db_session, actor=main_actor, **search)
        return [found.task.key for found in outcome.page.items]

    by_query = await keys(query=f"decision: TRK#{old}")
    by_term = await keys(
        structured=[search_service.StructuredTerm(name="decision", values=[f"trk#{old}"])]
    )

    assert by_query == by_term == [done_under_old.key, open_under_old.key]
    assert await keys(query=f"decision: TRK#{old}, TRK#{new}") == [
        done_under_old.key,
        open_under_old.key,
        under_new.key,
    ]
    assert await keys(query="decision: empty()") == [without.key]
    assert await keys(query=f"decision: != TRK#{old}") == [under_new.key, without.key]


@pytest.mark.parametrize(
    ("value", "reason"),
    [("TRK#99", "decision_not_found"), ("TRK-1#1", "task_entry"), ("TRK", "not_a_decision_ref")],
)
async def test_an_unknown_decision_in_a_search_is_refused_rather_than_found_empty(
    db_session: AsyncSession,
    project: Project,
    main_actor: Actor,
    task: Task,
    value: str,
    reason: str,
) -> None:
    await _decision(db_session, project, main_actor, "Решение")

    with pytest.raises(SearchValueInvalidError) as refused:
        await search_service.search_tasks(
            db_session, actor=main_actor, query=f'decision: "{value}"'
        )

    assert refused.value.details["reason"] == reason
    assert refused.value.details["field"] == "decision"


async def test_the_project_read_counts_the_tasks_citing_each_decision(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    old = await _decision(db_session, project, main_actor, "Старое")
    lonely = await _decision(db_session, project, main_actor, "Без задач")
    await _task(db_session, project, main_actor, "Первая", [f"TRK#{old}"])
    closed = await _task(db_session, project, main_actor, "Вторая", [f"TRK#{old}"])
    await _cancel(db_session, closed, main_actor)

    decisions = await decisions_service.project_decisions(db_session, project, actor=main_actor)
    counts = await decisions_service.citing_task_counts(db_session, decisions, actor=main_actor)

    assert counts == {f"TRK#{old}": 2}
    assert f"TRK#{lonely}" not in counts


# --- REST --------------------------------------------------------------------------------


async def test_rest_supersedes_reads_statuses_and_cites_decisions(
    auth_client: AsyncClient, project: Project
) -> None:
    entries = f"/api/v1/projects/{project.key}/entries"
    first = await auth_client.post(entries, json={"type": "decision", "title": "Первое"})
    assert first.status_code == 201, first.text
    assert first.json()["data"]["payload"] == {"supersedes": []}
    first_no = first.json()["data"]["no"]

    created = await auth_client.post(
        "/api/v1/tasks",
        json={
            "project": "TRK",
            "title": "Задача",
            "description": "d",
            "decisions": [f"TRK#{first_no}"],
        },
    )
    assert created.status_code == 201, created.text
    key = created.json()["data"]["key"]

    second = await auth_client.post(
        entries, json={"type": "decision", "title": "Второе", "supersedes": [first_no]}
    )
    assert second.status_code == 201, second.text
    second_no = second.json()["data"]["no"]
    assert second.json()["data"]["payload"] == {"supersedes": [first_no]}

    detail = (await auth_client.get(f"/api/v1/projects/{project.key}")).json()["data"]
    assert [
        (item["ref"], item["status"], item["superseded_by"], item["supersedes"], item["tasks"])
        for item in detail["decisions"]
    ] == [
        (f"TRK#{first_no}", "superseded", second_no, [], 1),
        (f"TRK#{second_no}", "in_force", None, [first_no], 0),
    ]

    package = (await auth_client.get(f"/api/v1/tasks/{key}")).json()["data"]
    assert package["decisions"] == [
        {
            "ref": f"TRK#{first_no}",
            "title": "Первое",
            "status": "superseded",
            "superseded_by": {"ref": f"TRK#{second_no}", "title": "Второе", "status": "in_force"},
        }
    ]

    refused = await auth_client.patch(
        f"/api/v1/tasks/{key}", json={"decisions": [f"TRK#{first_no}", "TRK-1#1"]}
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "task_fields_invalid"
    superseded = await auth_client.post(
        "/api/v1/tasks",
        json={
            "project": "TRK",
            "title": "Вторая",
            "description": "d",
            "decisions": [f"TRK#{first_no}"],
        },
    )
    assert superseded.status_code == 409, superseded.text
    assert superseded.json()["error"]["code"] == "decision_not_in_force"

    found = await auth_client.get("/api/v1/tasks", params={"decision": f"TRK#{first_no}"})
    assert found.status_code == 200, found.text
    assert [row["key"] for row in found.json()["data"]] == [key]


async def test_rest_reads_a_decisions_edit_in_the_case(
    auth_client: AsyncClient, project: Project
) -> None:
    decision = await auth_client.post(
        f"/api/v1/projects/{project.key}/entries", json={"type": "decision", "title": "Решение"}
    )
    ref = f"TRK#{decision.json()['data']['no']}"
    created = await auth_client.post(
        "/api/v1/tasks", json={"project": "TRK", "title": "Задача", "description": "d"}
    )
    key = created.json()["data"]["key"]

    edited = await auth_client.patch(f"/api/v1/tasks/{key}", json={"decisions": [ref]})
    assert edited.status_code == 200, edited.text
    case = await auth_client.get(
        f"/api/v1/tasks/{key}/entries", params={"types": ["field_changed"]}
    )

    assert case.status_code == 200, case.text
    assert [item["payload"] for item in case.json()["data"]] == [
        {"field": "decisions", "before": [], "after": [ref]}
    ]


# --- MCP ---------------------------------------------------------------------------------


async def test_mcp_decisions_from_filing_to_history(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, project: Project
) -> None:
    """Весь путь агента: решение, задача по нему, закрытие, замена, статус и история."""
    async with mcp_session(task_secret) as session:
        old = await call(
            session, "add_project_entry", key="TRK", type="decision", title="Сервис не строим"
        )
        created = await call(
            session,
            "create_task",
            project="TRK",
            title="Страница цены",
            description="Проверка спроса",
            sections={
                "goal": "g",
                "context": "c",
                "constraints": "x",
                "output": "o",
                "checks": ["страница открывается"],
            },
            assignee="owner",
            decisions=[f"TRK#{old['no']}"],
        )
        key = created["key"]
        await call(session, "transition", key=key, to="open")
        await call(session, "transition", key=key, to="in_progress")
        await call(
            session,
            "close_task",
            key=key,
            verdicts=[{"check_no": 1, "outcome": "passed", "evidence": "открылась"}],
            summary={
                "done": "Страница готова",
                "remaining": "nothing",
                "blockers": "nothing",
                "next_step": "no steps",
                "unmeasured": "nothing",
            },
        )
        new = await call(
            session,
            "add_project_entry",
            key="TRK",
            type="decision",
            title="Сервис строим",
            supersedes=[old["no"]],
        )
        again = await refuse(
            session,
            "add_project_entry",
            key="TRK",
            type="decision",
            title="Третье",
            supersedes=[old["no"]],
        )
        rumour = await refuse(
            session,
            "create_task",
            project="TRK",
            title="Слух",
            description="d",
            decisions=[f"{key}#1"],
        )
        package = await call(session, "get_task", key=key)
        project_view = await call(session, "get_project", key="TRK")
        history = await call(session, "search_tasks", decision=[f"TRK#{old['no']}"])

    assert "decision_not_in_force" in again
    assert "task_entry" in rumour
    assert package["task"]["status"] == "done"
    assert package["decisions"] == [
        {
            "ref": f"TRK#{old['no']}",
            "title": "Сервис не строим",
            "status": "superseded",
            "superseded_by": {
                "ref": f"TRK#{new['no']}",
                "title": "Сервис строим",
                "status": "in_force",
            },
        }
    ]
    assert project_view["decisions"] == [{"ref": f"TRK#{new['no']}", "title": "Сервис строим"}]
    assert [row["key"] for row in history["items"]] == [key]

    rest = await auth_client.get(f"/api/v1/tasks/{key}")
    assert rest.json()["data"]["decisions"] == package["decisions"]
