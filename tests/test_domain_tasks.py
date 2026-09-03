"""Домен задачи без базы: ключ, таблица переходов, проверки перехода, правила полей.

Всё, что здесь проверяется, одинаково для REST, MCP и командной строки.
"""

import pytest

from app.domain.errors import (
    InvalidTaskKeyError,
    TaskFieldsInvalidError,
    TaskSectionsIncompleteError,
    TransitionNotAllowedError,
    TransitionReasonRequiredError,
)
from app.domain.tasks import (
    BACKLOG_ONLY_FIELDS,
    OPEN_FIELDS,
    TRANSITION_CHECKS,
    TRANSITIONS,
    TaskField,
    TaskPriority,
    TaskStatus,
    TransitionFacts,
    allowed_transitions,
    editable_fields,
    ensure_transition_allowed,
    format_task_key,
    is_step_back,
    normalize_fields,
    normalize_reason,
    normalize_task_key,
    parse_task_key,
)

FILLED = {
    TaskField.GOAL: "цель",
    TaskField.CONTEXT: "контекст",
    TaskField.CONSTRAINTS: "ограничения",
    TaskField.OUTPUT: "выход",
}


def facts(
    from_status: TaskStatus,
    to_status: TaskStatus,
    *,
    reason: str | None = None,
    sections: dict[TaskField, str] | None = None,
    checks: tuple[str, ...] = ("проверка",),
) -> TransitionFacts:
    return TransitionFacts(
        key="TRK-1",
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        sections=FILLED if sections is None else sections,
        checks=checks,
    )


# --- Ключ задачи -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("TRK-42", ("TRK", 42)), ("trk-42", ("TRK", 42)), (" Ops2-7 ", ("OPS2", 7))],
)
def test_a_task_key_is_parsed_softly_by_case(raw: str, expected: tuple[str, int]) -> None:
    assert parse_task_key(raw) == expected
    assert normalize_task_key(raw) == format_task_key(*expected)


@pytest.mark.parametrize(
    "raw", ["TRK", "TRK-", "-1", "TRK-0", "TRK-007", "TRK-1-2", "TRK-١٢", "T-1"]
)
def test_a_malformed_task_key_is_rejected(raw: str) -> None:
    """`TRK-007` и `TRK-7` не должны указывать на одну задачу двумя способами."""
    with pytest.raises(InvalidTaskKeyError) as error:
        parse_task_key(raw)

    assert error.value.code == "invalid_task_key"


# --- Таблица переходов --------------------------------------------------------------


def test_the_transition_table_matches_the_concept() -> None:
    """Таблица зашита; тест повторяет её из `CONCEPT.md`, чтобы правка была осознанной."""
    assert TRANSITIONS == {
        TaskStatus.BACKLOG: (TaskStatus.OPEN, TaskStatus.CANCELLED),
        TaskStatus.OPEN: (TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG, TaskStatus.CANCELLED),
        TaskStatus.IN_PROGRESS: (
            TaskStatus.REVIEW,
            TaskStatus.OPEN,
            TaskStatus.BACKLOG,
            TaskStatus.CANCELLED,
        ),
        TaskStatus.REVIEW: (TaskStatus.DONE, TaskStatus.OPEN, TaskStatus.CANCELLED),
        TaskStatus.DONE: (),
        TaskStatus.CANCELLED: (),
    }
    assert allowed_transitions(TaskStatus.DONE) == ()


@pytest.mark.parametrize(
    ("from_status", "to_status", "expected"),
    [
        (TaskStatus.IN_PROGRESS, TaskStatus.OPEN, True),
        (TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG, True),
        (TaskStatus.REVIEW, TaskStatus.OPEN, True),
        (TaskStatus.OPEN, TaskStatus.BACKLOG, True),
        (TaskStatus.OPEN, TaskStatus.IN_PROGRESS, False),
        (TaskStatus.REVIEW, TaskStatus.CANCELLED, False),
    ],
)
def test_a_step_back_is_a_move_to_a_lower_status_of_the_chain(
    from_status: TaskStatus, to_status: TaskStatus, expected: bool
) -> None:
    assert is_step_back(from_status, to_status) is expected


def test_a_transition_outside_the_table_lists_the_allowed_ones() -> None:
    """Обзорная проверка 3 на уровне домена."""
    with pytest.raises(TransitionNotAllowedError) as error:
        ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.DONE))

    assert error.value.code == "transition_not_allowed"
    assert error.value.details["allowed"] == ["in_progress", "backlog", "cancelled"]


# --- Проверки перехода --------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "to_status", "rule"),
    [
        (TaskStatus.IN_PROGRESS, TaskStatus.OPEN, "step_back"),
        (TaskStatus.OPEN, TaskStatus.BACKLOG, "step_back"),
        (TaskStatus.BACKLOG, TaskStatus.CANCELLED, "cancel"),
        (TaskStatus.REVIEW, TaskStatus.CANCELLED, "cancel"),
    ],
)
def test_a_step_back_and_a_cancellation_require_a_reason(
    from_status: TaskStatus, to_status: TaskStatus, rule: str
) -> None:
    with pytest.raises(TransitionReasonRequiredError) as error:
        ensure_transition_allowed(facts(from_status, to_status))
    assert error.value.details["rule"] == rule

    ensure_transition_allowed(facts(from_status, to_status, reason="потому что"))


def test_a_blank_reason_counts_as_no_reason() -> None:
    assert normalize_reason("   ") is None
    assert normalize_reason(" потому ") == "потому"

    with pytest.raises(TransitionReasonRequiredError):
        ensure_transition_allowed(facts(TaskStatus.REVIEW, TaskStatus.OPEN, reason=None))


def test_a_forward_move_does_not_need_a_reason() -> None:
    ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS))
    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.REVIEW))


def test_opening_lists_every_unfilled_section_at_once() -> None:
    """Обзорная проверка 2 на уровне домена: все незаполненные разделы сразу."""
    with pytest.raises(TaskSectionsIncompleteError) as error:
        ensure_transition_allowed(
            facts(
                TaskStatus.BACKLOG,
                TaskStatus.OPEN,
                sections={TaskField.GOAL: "цель", TaskField.CONTEXT: ""},
                checks=(),
            )
        )

    assert error.value.code == "task_sections_incomplete"
    assert error.value.details["fields"] == ["context", "constraints", "output", "checks"]


def test_opening_passes_with_sections_and_at_least_one_check() -> None:
    ensure_transition_allowed(facts(TaskStatus.BACKLOG, TaskStatus.OPEN))


def test_the_section_check_only_guards_the_move_into_open() -> None:
    """Отмена из `backlog` не требует разделов: проверка привязана к паре статусов."""
    ensure_transition_allowed(
        facts(TaskStatus.BACKLOG, TaskStatus.CANCELLED, reason="не нужна", sections={}, checks=())
    )


def test_the_check_list_is_the_extension_point() -> None:
    """Следующие задачи добавляют проверки в список, а не в таблицу."""
    assert len(TRANSITION_CHECKS) == 2
    assert all(callable(check) for check in TRANSITION_CHECKS)


# --- Правила полей --------------------------------------------------------------------


def test_everything_is_editable_in_backlog_and_nothing_when_closed() -> None:
    assert editable_fields(TaskStatus.BACKLOG) == BACKLOG_ONLY_FIELDS | OPEN_FIELDS
    assert editable_fields(TaskStatus.OPEN) == OPEN_FIELDS
    assert editable_fields(TaskStatus.REVIEW) == OPEN_FIELDS
    assert editable_fields(TaskStatus.DONE) == frozenset()
    assert editable_fields(TaskStatus.CANCELLED) == frozenset()
    assert TaskField.STATUS not in editable_fields(TaskStatus.BACKLOG)


def test_normalisation_collects_every_problem_at_once() -> None:
    """Агент исправляет запрос за одну попытку, а не за пять кругов."""
    with pytest.raises(TaskFieldsInvalidError) as error:
        normalize_fields(
            {
                TaskField.TITLE: "  ",
                TaskField.DESCRIPTION: "есть",
                TaskField.CHECKS: ["ок", "  "],
                TaskField.PRIORITY: "urgent",
                TaskField.ASSIGNEE: "",
            }
        )

    problems = {item["field"]: item for item in error.value.details["fields"]}
    assert set(problems) == {"title", "checks", "priority", "assignee"}
    assert problems["title"]["reason"] == "required"
    assert problems["checks"] == {"field": "checks", "reason": "empty_item", "check_no": 2}
    assert problems["priority"]["allowed"] == ["low", "normal", "high", "critical"]


def test_normalisation_strips_and_keeps_order() -> None:
    normalized = normalize_fields(
        {
            TaskField.TITLE: "  Починить  ",
            TaskField.CHECKS: [" первая ", "вторая"],
            TaskField.TAGS: ["Релиз", "релиз", "", "backend"],
            TaskField.PRIORITY: "high",
            TaskField.ASSIGNEE: None,
        }
    )

    assert normalized == {
        TaskField.TITLE: "Починить",
        TaskField.CHECKS: ["первая", "вторая"],
        TaskField.TAGS: ["Релиз", "backend"],
        TaskField.PRIORITY: TaskPriority.HIGH,
        TaskField.ASSIGNEE: None,
    }
