"""Блок `state` и краткий ответ `get_task(brief=true)` (TRK-579).

Блок считается при чтении и ничего не хранит (`CONCEPT.md`, 4.2): тесты читают задачу
после каждого шага работы агента и сверяют, что он показывает то, что было сделано, и
что REST и MCP отдают одно и то же поле в поле. Чистые правила — обрезка, «после сводки»,
решения после карточки — проверены на описи без базы.
"""

from datetime import UTC, datetime
from typing import Any

import jsonschema
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import Connect, call

from app.db.models.task import Task
from app.domain.authors import Author, AuthorKind
from app.domain.case import EntryHeading, EntryType, NoFacts, SectionChangedFacts
from app.domain.state import (
    REASON_LIMIT,
    RECENT_LIMIT,
    SummaryParts,
    build_state,
    clip,
    status_change,
)
from app.domain.tasks import TaskField, TaskStatus
from app.services import tasks as tasks_service
from app.services.auth import Actor


@pytest.fixture
async def open_task(db_session: AsyncSession, task_actor: Actor, task: Task) -> Task:
    """Задача `TRK-1` в `open`, исполнитель — владелец: агент берёт её в работу."""
    await tasks_service.transition_task(db_session, task, actor=task_actor, to="open")
    return task


AGENT = Author(kind=AuthorKind.AGENT, signature="claude")
MOMENT = datetime(2026, 10, 6, 11, 59, 30, tzinfo=UTC)


def _heading(no: int, type: EntryType, title: str = "Заголовок") -> EntryHeading:
    facts = (
        SectionChangedFacts(field=TaskField.GOAL)
        if type is EntryType.SECTION_CHANGED
        else NoFacts(type=type)
    )
    return EntryHeading(
        no=no,
        type=type,
        author=AGENT,
        created_at=MOMENT,
        title=title,
        facts=facts,
        action_id=None,
    )


def _state(index: list[EntryHeading], **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "status": TaskStatus.OPEN,
        "index": index,
        "last_change": None,
        "summary": None,
        "questions": [],
        "remarks": [],
        "open_blockers": [],
        "children": [],
    }
    arguments.update(overrides)
    return build_state(**arguments)


# --- Чистые правила -------------------------------------------------------------------


def test_clip_cuts_at_a_word_with_an_ellipsis() -> None:
    assert clip("коротко", 20) == "коротко"
    cut = clip("слово " * 60, REASON_LIMIT)
    assert len(cut) <= REASON_LIMIT
    assert cut.endswith("…")
    assert clip("несколько\n  строк   и пробелов", 100) == "несколько строк и пробелов"


def test_recent_shows_the_last_entries_after_the_summary_only() -> None:
    index = [_heading(1, EntryType.CREATED)]
    index += [_heading(no, EntryType.FINDING, f"до сводки {no}") for no in range(2, 5)]
    index.append(_heading(5, EntryType.SUMMARY, "Сводка"))
    index.append(_heading(6, EntryType.STATUS_CHANGED, "служебная запись не в счёт"))
    index += [_heading(no, EntryType.NOTE, f"после {no}") for no in range(7, 7 + RECENT_LIMIT + 2)]

    state = _state(index, summary=None)
    assert state.recent.after_summary is None
    assert state.recent.total == 3 + 1 + RECENT_LIMIT + 2

    summary = SummaryParts(
        no=5, created_at=MOMENT, next_step="шаг", blockers="нет", unmeasured=None
    )
    state = _state(index, summary=summary)
    assert state.recent.after_summary == 5
    assert state.recent.total == RECENT_LIMIT + 2
    assert len(state.recent.lines) == RECENT_LIMIT
    assert state.recent.lines[-1].startswith(
        f"#{7 + RECENT_LIMIT + 1} note claude 2026-10-06T11:59Z:"
    )


def test_decisions_after_card_count_from_the_last_section_edit() -> None:
    index = [
        _heading(1, EntryType.CREATED),
        _heading(2, EntryType.DECISION),
        _heading(3, EntryType.SECTION_CHANGED),
        _heading(4, EntryType.DECISION),
        _heading(5, EntryType.FINDING),
        _heading(6, EntryType.DECISION),
    ]
    assert _state(index).decisions_after_card == [4, 6]


def test_a_move_without_a_reason_has_no_reason() -> None:
    change = status_change(
        no=3,
        author=AGENT,
        created_at=MOMENT,
        payload={"from": "open", "to": "in_progress", "reason": None},
    )
    state = _state([_heading(1, EntryType.CREATED)], last_change=change)
    assert state.last_transition is not None
    assert state.last_transition.reason is None
    assert state.last_transition.to_status is TaskStatus.IN_PROGRESS


# --- Чтение через MCP и REST ----------------------------------------------------------


async def test_state_reflects_the_wait_the_answer_and_the_open_question(
    mcp_session: Connect,
    auth_client: AsyncClient,
    task_secret: str,
    open_task: Task,
) -> None:
    """Проверка 2: статус, причина перехода, запись после сводки и вопрос с адресатом."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        await call(session, "transition", key=key, to="in_progress")
        await call(
            session,
            "add_summary",
            key=key,
            done="Прочитал дело",
            remaining="Всё",
            blockers="Нужен ответ владельца",
            next_step="Ждать ответа",
        )
        await call(
            session,
            "ask",
            key=key,
            addressees=["owner"],
            title="Брать вариант 3?",
            blocking=True,
        )
        await call(session, "transition", key=key, to="open", reason="Жду ответа на " + key + "#5")
        await call(session, "add_entry", key=key, type="finding", title="Свежая находка")
        package = await call(session, "get_task", key=key)

    assert next(iter(package)) == "state"
    state = package["state"]
    assert state["status"] == "open"
    assert state["last_transition"]["reason"] == f"Жду ответа на {key}#5"
    assert state["last_transition"]["from_status"] == "in_progress"
    assert state["last_summary"]["next_step"] == "Ждать ответа"
    assert state["last_summary"]["unmeasured"] is None
    assert state["recent"]["after_summary"] == state["last_summary"]["no"]
    assert state["recent"]["total"] == 2
    assert state["recent"]["lines"][-1].endswith(": Свежая находка")
    assert state["questions"] == [
        {"no": 5, "to": ["owner"], "blocking": True, "title": "Брать вариант 3?"}
    ]
    assert state["children"] == {"total": 0, "by_status": {}, "unclosed": []}
    assert state["blockers"] == []

    response = await auth_client.get(f"/api/v1/tasks/{key}")
    assert response.status_code == 200, response.text
    assert next(iter(response.json()["data"])) == "state"
    assert response.json()["data"]["state"] == state


async def test_state_names_blockers_children_and_the_closing_unmeasured(
    mcp_session: Connect,
    task_secret: str,
    open_task: Task,
) -> None:
    key = open_task.key
    async with mcp_session(task_secret) as session:
        child = await call(
            session,
            "create_task",
            project="TRK",
            title="Часть работы",
            description="Ребёнок",
            parent=key,
        )
        blocker = await call(
            session,
            "create_task",
            project="TRK",
            title="Блокер",
            description="Not ready",
        )
        await call(session, "link", key=key, kind="blocked_by", other=blocker["key"])
        package = await call(session, "get_task", key=key)

    state = package["state"]
    assert state["blockers"] == [blocker["key"]]
    assert state["children"] == {
        "total": 1,
        "by_status": {"backlog": 1},
        "unclosed": [child["key"]],
    }


async def test_brief_has_only_the_header_state_features_and_transitions(
    mcp_session: Connect,
    auth_client: AsyncClient,
    task_secret: str,
    open_task: Task,
) -> None:
    """Проверки 3 и 4: краткий ответ без разделов и описи, полный — со всеми полями."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        declared = {tool.name: tool.output_schema for tool in (await session.list_tools()).tools}
        full = await call(session, "get_task", key=key)
        brief = await call(session, "get_task", key=key, brief=True)
        explicit = await call(session, "get_task", key=key, brief=False)

    jsonschema.validate(brief, declared["get_task"])
    jsonschema.validate(full, declared["get_task"])
    assert explicit == full
    assert list(brief) == ["state", "task", "parent", "features", "transitions"]
    assert set(brief["task"]) == {
        "key",
        "title",
        "status",
        "assignee",
        "priority",
        "direction",
        "version",
        "updated_at",
    }
    assert brief["task"]["key"] == key
    assert brief["state"] == full["state"]
    assert brief["features"] == full["features"]
    assert brief["transitions"] == full["transitions"]
    for dropped in ("links", "index", "decisions", "summary", "questions", "remarks", "children"):
        assert dropped not in brief
    for section in ("goal", "context", "constraints", "output", "checks", "project"):
        assert section not in brief["task"]
    assert {"task", "parent", "children", "links", "decisions", "features", "summary"} <= set(full)
    assert {"goal", "checks", "project", "description"} <= set(full["task"])

    response = await auth_client.get(f"/api/v1/tasks/{key}", params={"brief": "true"})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == brief
    rest_full = await auth_client.get(f"/api/v1/tasks/{key}")
    assert rest_full.json()["data"] == full


async def test_brief_names_the_parent_without_its_goal(
    mcp_session: Connect,
    task_secret: str,
    open_task: Task,
) -> None:
    async with mcp_session(task_secret) as session:
        child = await call(
            session,
            "create_task",
            project="TRK",
            title="Часть",
            description="Ребёнок",
            parent=open_task.key,
        )
        brief = await call(session, "get_task", key=child["key"], brief=True)

    assert brief["parent"]["key"] == open_task.key
    assert "goal" not in brief["parent"]
