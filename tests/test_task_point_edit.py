"""Точечная правка задачи: один фрагмент текста и одна ссылка на решение (TRK-708).

Поправить одну фразу раздела или одну ссылку агент мог, лишь переслав раздел или список
целиком: десятки килобайт повторного текста, и опечатка в неизменённой части проходила
молча. `changes.replace`, `changes.decisions_add` и `changes.decisions_remove` пересылают
только изменяемое; правила — те же, что у поля целиком.

Проверяется через настоящий клиент MCP: разбор аргумента, сценарий, служебная запись и
пакет `get_task` — части одного пути.
"""

from typing import Any

import pytest

from app.db.models.project import Project
from conftest import Connect, call, refuse

OLD_PHRASE = "команда запуска: docker compose up"
NEW_PHRASE = "команда запуска: docker compose up --build"
#: Раздел длиннее двух тысяч знаков, с одним нужным местом посередине.
CONTEXT = ("Описание окружения. " * 60) + OLD_PHRASE + (" Подробности ниже." * 60)


async def _new_task(session: Any, *, decisions: list[str] | None = None) -> str:
    created = await call(
        session,
        "create_task",
        project="TRK",
        area="TRK/core",
        title="Правка фразы",
        description="Опечатка в одной фразе раздела",
        assignee="owner",
        decisions=decisions or [],
        sections={
            "goal": "цель",
            "context": CONTEXT,
            "constraints": "ограничения",
            "output": "выход",
            "checks": ["проверка"],
        },
    )
    return str(created["key"])


async def _decision(session: Any, title: str) -> int:
    filed = await call(session, "add_project_entry", key="TRK", type="decision", title=title)
    return int(filed["no"])


@pytest.fixture
async def backlog_key(mcp_session: Connect, task_secret: str, project: Project) -> str:
    del project
    async with mcp_session(task_secret) as session:
        return await _new_task(session)


# --- replace ------------------------------------------------------------------------


async def test_replace_changes_only_the_fragment(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        changed = await call(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "context", "old": OLD_PHRASE, "new": NEW_PHRASE}},
        )
        package = await call(session, "get_task", key=backlog_key)
        entry = await call(session, "read_entries", key=backlog_key, nos=changed["entries"])

    assert len(CONTEXT) > 2000
    assert package["task"]["context"] == CONTEXT.replace(OLD_PHRASE, NEW_PHRASE)
    assert package["task"]["goal"] == "цель"
    assert len(changed["entries"]) == 1
    payload = entry["items"][0]["payload"]
    assert entry["items"][0]["type"] == "section_changed"
    assert (payload["field"], payload["before"], payload["after"]) == (
        "context",
        CONTEXT,
        CONTEXT.replace(OLD_PHRASE, NEW_PHRASE),
    )


async def test_replace_with_an_empty_text_removes_the_fragment(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        await call(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "context", "old": OLD_PHRASE, "new": ""}},
        )
        package = await call(session, "get_task", key=backlog_key)

    assert package["task"]["context"] == CONTEXT.replace(OLD_PHRASE, "")


async def test_replace_works_on_the_title_and_checks_the_result(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        await call(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "title", "old": "фразы", "new": "двух фраз"}},
        )
        emptied = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "title", "old": "Правка двух фраз", "new": ""}},
        )
        package = await call(session, "get_task", key=backlog_key)

    assert "task_fields_invalid" in emptied, emptied
    assert "required" in emptied, emptied
    assert package["task"]["title"] == "Правка двух фраз"


async def test_no_occurrence_is_refused_and_the_task_stays(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        before = await call(session, "get_task", key=backlog_key)
        failure = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "context", "old": "этого нет", "new": "x"}},
        )
        after = await call(session, "get_task", key=backlog_key)

    assert "task_fields_invalid" in failure, failure
    assert "old_not_found" in failure, failure
    assert '"occurrences": 0' in failure, failure
    assert after["task"]["version"] == before["task"]["version"]
    assert after["task"]["context"] == CONTEXT


async def test_two_occurrences_are_refused_with_their_number(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        before = await call(session, "get_task", key=backlog_key)
        failure = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "context", "old": "Описание окружения.", "new": "x"}},
        )
        after = await call(session, "get_task", key=backlog_key)

    assert "task_fields_invalid" in failure, failure
    assert "old_not_unique" in failure, failure
    assert '"occurrences": 60' in failure, failure
    assert '"target": "context"' in failure, failure
    assert after["task"]["version"] == before["task"]["version"]


async def test_replace_together_with_the_same_field_is_refused(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={
                "context": "новый текст",
                "replace": {"field": "context", "old": OLD_PHRASE, "new": NEW_PHRASE},
            },
        )
        other = await call(
            session,
            "update_task",
            key=backlog_key,
            changes={
                "goal": "новая цель",
                "replace": {"field": "context", "old": OLD_PHRASE, "new": NEW_PHRASE},
            },
        )

    assert "task_fields_invalid" in failure, failure
    assert "conflicts_with" in failure, failure
    assert len(other["entries"]) == 2, "второе поле замене не мешает"


async def test_replace_outside_backlog_is_locked(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        await call(session, "transition", key=backlog_key, to="open")
        failure = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "context", "old": OLD_PHRASE, "new": NEW_PHRASE}},
        )
        # Право проверяется раньше фрагмента: «поле закрыто», а не «фрагмента нет».
        unknown = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "context", "old": "этого нет", "new": "x"}},
        )

    assert "task_field_locked" in failure, failure
    assert "task_field_locked" in unknown, unknown


async def test_the_checks_are_not_a_target_of_replace(
    mcp_session: Connect, task_secret: str, backlog_key: str
) -> None:
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "update_task",
            key=backlog_key,
            changes={"replace": {"field": "checks", "old": "проверка", "new": "x"}},
        )

    assert "checks" in failure, failure


# --- decisions_add / decisions_remove --------------------------------------------------


async def test_decisions_add_adds_one_and_keeps_the_rest(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        first = await _decision(session, "Первое решение")
        second = await _decision(session, "Второе решение")
        key = await _new_task(session, decisions=[f"TRK#{first}"])
        changed = await call(
            session, "update_task", key=key, changes={"decisions_add": [f"trk#{second}"]}
        )
        package = await call(session, "get_task", key=key)
        entry = await call(session, "read_entries", key=key, nos=changed["entries"])

    assert [item["ref"] for item in package["decisions"]] == [f"TRK#{first}", f"TRK#{second}"]
    assert entry["items"][0]["type"] == "field_changed"
    assert entry["items"][0]["payload"]["before"] == [f"TRK#{first}"]
    assert entry["items"][0]["payload"]["after"] == [f"TRK#{first}", f"TRK#{second}"]


async def test_adding_a_reference_that_stands_files_nothing(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        first = await _decision(session, "Первое решение")
        key = await _new_task(session, decisions=[f"TRK#{first}"])
        before = await call(session, "get_task", key=key)
        changed = await call(
            session, "update_task", key=key, changes={"decisions_add": [f"TRK#{first}"]}
        )
        after = await call(session, "get_task", key=key)

    assert changed["entries"] == []
    assert after["task"]["version"] == before["task"]["version"]


async def test_decisions_add_refuses_a_superseded_decision(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        old = await _decision(session, "Старое решение")
        await call(
            session,
            "add_project_entry",
            key="TRK",
            type="decision",
            title="Новое решение",
            supersedes=[old],
        )
        key = await _new_task(session)
        failure = await refuse(
            session, "update_task", key=key, changes={"decisions_add": [f"TRK#{old}"]}
        )

    assert "decision_not_in_force" in failure, failure


async def test_decisions_remove_takes_off_one_reference(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        first = await _decision(session, "Первое решение")
        second = await _decision(session, "Второе решение")
        key = await _new_task(session, decisions=[f"TRK#{first}", f"TRK#{second}"])
        await call(session, "update_task", key=key, changes={"decisions_remove": [f"TRK#{first}"]})
        package = await call(session, "get_task", key=key)

    assert [item["ref"] for item in package["decisions"]] == [f"TRK#{second}"]


async def test_removing_a_reference_that_is_not_there_is_refused(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        first = await _decision(session, "Первое решение")
        key = await _new_task(session, decisions=[f"TRK#{first}"])
        failure = await refuse(
            session, "update_task", key=key, changes={"decisions_remove": ["TRK#999"]}
        )
        package = await call(session, "get_task", key=key)

    assert "task_fields_invalid" in failure, failure
    assert "not_in_field" in failure, failure
    assert "TRK#999" in failure, failure
    assert [item["ref"] for item in package["decisions"]] == [f"TRK#{first}"]


async def test_either_list_edit_together_with_the_whole_list_is_refused(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        first = await _decision(session, "Первое решение")
        key = await _new_task(session, decisions=[f"TRK#{first}"])
        added = await refuse(
            session,
            "update_task",
            key=key,
            changes={"decisions": [], "decisions_add": [f"TRK#{first}"]},
        )
        removed = await refuse(
            session,
            "update_task",
            key=key,
            changes={"decisions": [], "decisions_remove": [f"TRK#{first}"]},
        )

    for failure in (added, removed):
        assert "task_fields_invalid" in failure, failure
        assert "conflicts_with" in failure, failure


async def test_decisions_are_edited_by_point_in_open_but_not_when_closed(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    del project
    async with mcp_session(task_secret) as session:
        first = await _decision(session, "Первое решение")
        key = await _new_task(session)
        await call(session, "transition", key=key, to="open")
        await call(session, "update_task", key=key, changes={"decisions_add": [f"TRK#{first}"]})
        await call(session, "transition", key=key, to="in_progress")
        await call(
            session,
            "close_task",
            key=key,
            verdicts=[{"check_no": 1, "outcome": "passed", "evidence": "ок"}],
            summary={
                "done": "Готово",
                "remaining": "nothing",
                "blockers": "nothing",
                "next_step": "no steps",
                "unmeasured": "nothing",
            },
        )
        closed = await refuse(
            session, "update_task", key=key, changes={"decisions_remove": [f"TRK#{first}"]}
        )

    assert "task_closed" in closed, closed
