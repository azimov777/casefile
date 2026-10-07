"""Домен задачи без базы: ключ, таблица переходов, проверки перехода, правила полей.

Всё, что здесь проверяется, одинаково для REST, MCP и командной строки.
"""

import pytest

from app.domain.errors import (
    AssigneeMismatchError,
    AssigneeRequiredError,
    ChecksNotPassedError,
    ClosingNotATransitionError,
    InvalidTaskKeyError,
    SummaryRequiredError,
    TaskBlockedError,
    TaskDeferredError,
    TaskFieldsInvalidError,
    TaskHasOpenBlockingQuestionsError,
    TaskHasOpenDiscussionsError,
    TaskHasUnclosedChildrenError,
    TaskSectionsIncompleteError,
    TransitionNotAllowedError,
    TransitionReasonRequiredError,
)
from app.domain.tasks import (
    BACKLOG_ONLY_FIELDS,
    OPEN_FIELDS,
    STATUS_CHAIN,
    TRANSITION_CHECKS,
    TRANSITIONS,
    CheckGap,
    CheckGapReason,
    TaskField,
    TaskPriority,
    TaskStatus,
    TransitionFacts,
    allowed_transitions,
    editable_fields,
    ensure_transition_allowed,
    format_task_key,
    is_closed,
    is_step_back,
    normalize_fields,
    normalize_reason,
    normalize_task_key,
    parse_status,
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
    has_summary: bool = True,
    pending_checks: tuple[CheckGap, ...] | None = (),
    blockers: tuple[str, ...] | None = (),
    blocking_questions: tuple[str, ...] | None = (),
    children: tuple[str, ...] | None = (),
    discussions: tuple[str, ...] | None = (),
    closing: bool = True,
    assignee: str | None = "claude",
    requester: str | None = "claude",
    deferred: bool | None = False,
) -> TransitionFacts:
    """Факты перехода, у которых по умолчанию сошлось всё, кроме проверяемого.

    Значения по умолчанию здесь **обратны** значениям в самой структуре: там
    незаполненный факт запрещает переход, здесь заполненный не мешает проверять
    соседей. Что незаполненный факт запрещает переход, проверяется отдельно —
    `test_an_unfilled_fact_forbids_the_move`.
    """
    return TransitionFacts(
        key="TRK-1",
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        sections=FILLED if sections is None else sections,
        checks=checks,
        has_summary_since_in_progress=has_summary,
        checks_without_passed_verdict=pending_checks,
        open_blockers=blockers,
        open_blocking_questions=blocking_questions,
        unclosed_children=children,
        open_discussions=discussions,
        closing=closing,
        assignee=assignee,
        requester=requester,
        deferred=deferred,
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
        TaskStatus.OPEN: (
            TaskStatus.IN_PROGRESS,
            TaskStatus.BACKLOG,
            TaskStatus.CANCELLED,
        ),
        TaskStatus.IN_PROGRESS: (
            TaskStatus.DONE,
            TaskStatus.OPEN,
            TaskStatus.BACKLOG,
            TaskStatus.CANCELLED,
        ),
        TaskStatus.DONE: (),
        TaskStatus.CANCELLED: (),
    }
    assert allowed_transitions(TaskStatus.DONE) == ()


def test_there_is_no_waiting_status_and_no_alias_for_it() -> None:
    """Статус ожидания снят (TRK-573, решение владельца TRK-569#9): ждёт носитель в деле.

    Псевдонима нет: строка `waiting` не разбирается в статус, а отказ перечисляет
    допустимые статусы без неё. Вне цепочки стоит только `cancelled`.
    """
    assert "waiting" not in {status.value for status in TaskStatus}
    assert set(TaskStatus) - set(STATUS_CHAIN) == {TaskStatus.CANCELLED}

    with pytest.raises(TaskFieldsInvalidError) as error:
        parse_status("waiting")

    (problem,) = error.value.details["fields"]
    assert problem["field"] == "status"
    assert problem["allowed"] == ["backlog", "open", "in_progress", "done", "cancelled"]
    # Ждущая задача стоит в `open`: поля в нём правятся так же, как у любой задачи там.
    assert editable_fields(TaskStatus.OPEN) == OPEN_FIELDS
    assert not is_closed(TaskStatus.OPEN)


@pytest.mark.parametrize(
    ("from_status", "to_status", "expected"),
    [
        (TaskStatus.IN_PROGRESS, TaskStatus.OPEN, True),
        (TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG, True),
        (TaskStatus.DONE, TaskStatus.OPEN, True),
        (TaskStatus.OPEN, TaskStatus.BACKLOG, True),
        (TaskStatus.OPEN, TaskStatus.IN_PROGRESS, False),
        (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, False),
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
        (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, "cancel"),
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
        ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.OPEN, reason=None))


def test_a_forward_move_does_not_need_a_reason() -> None:
    ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS))
    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE))


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
    assert len(TRANSITION_CHECKS) == 11
    assert all(callable(check) for check in TRANSITION_CHECKS)


# --- Правила полей --------------------------------------------------------------------


def test_everything_is_editable_in_backlog_and_nothing_when_closed() -> None:
    assert editable_fields(TaskStatus.BACKLOG) == BACKLOG_ONLY_FIELDS | OPEN_FIELDS
    assert editable_fields(TaskStatus.OPEN) == OPEN_FIELDS
    assert editable_fields(TaskStatus.IN_PROGRESS) == OPEN_FIELDS
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
            TaskField.PRIORITY: "high",
            TaskField.ASSIGNEE: None,
        }
    )

    assert normalized == {
        TaskField.TITLE: "Починить",
        TaskField.CHECKS: ["первая", "вторая"],
        TaskField.PRIORITY: TaskPriority.HIGH,
        TaskField.ASSIGNEE: None,
    }


# --- Проверки перехода задачи 23 ------------------------------------------------------


def test_leaving_in_progress_without_a_summary_is_a_conflict() -> None:
    """Обзорная проверка 2 на уровне домена. Правило действует на **все** выходы."""
    for to_status in (TaskStatus.DONE, TaskStatus.OPEN, TaskStatus.BACKLOG, TaskStatus.CANCELLED):
        with pytest.raises(SummaryRequiredError) as error:
            ensure_transition_allowed(
                facts(
                    TaskStatus.IN_PROGRESS,
                    to_status,
                    reason="есть причина",
                    has_summary=False,
                )
            )
        assert error.value.code == "summary_required"
        assert error.value.details["to"] == to_status.value

    ensure_transition_allowed(
        facts(TaskStatus.IN_PROGRESS, TaskStatus.OPEN, reason="есть причина", has_summary=True)
    )


def test_closing_lists_the_checks_without_a_passing_verdict() -> None:
    """В подробностях — номер каждой незасчитанной проверки и причина.

    Причина обязательна: «вердикта в этом заходе нет» и «последний вердикт провальный» —
    разные состояния, и по одному номеру их не различить.
    """
    with pytest.raises(ChecksNotPassedError) as error:
        ensure_transition_allowed(
            facts(
                TaskStatus.IN_PROGRESS,
                TaskStatus.DONE,
                pending_checks=(
                    CheckGap(check_no=2, reason=CheckGapReason.NO_VERDICT),
                    CheckGap(check_no=3, reason=CheckGapReason.FAILED),
                ),
            )
        )

    assert error.value.code == "checks_not_passed"
    assert error.value.details["checks"] == [
        {"check_no": 2, "reason": "no_verdict"},
        {"check_no": 3, "reason": "failed"},
    ]

    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, pending_checks=()))


def test_done_is_reached_by_closing_and_not_by_a_status_move() -> None:
    """Единственная дверь в `done` — сценарий закрытия, и отказ говорит именно это.

    Проверка стоит **первой** в списке: у задачи без сводки и без вердиктов перевод
    статуса обязан услышать «не той дверью», а не список того, чего не хватает в деле.
    """
    with pytest.raises(ClosingNotATransitionError) as error:
        ensure_transition_allowed(
            facts(
                TaskStatus.IN_PROGRESS,
                TaskStatus.DONE,
                has_summary=False,
                pending_checks=None,
                closing=False,
            )
        )

    assert error.value.code == "closing_not_a_transition"
    assert error.value.details["to"] == TaskStatus.DONE.value

    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, closing=True))


def test_closing_does_not_excuse_the_other_checks() -> None:
    """Признак закрытия открывает дверь, но ничего не отменяет за ней."""
    with pytest.raises(SummaryRequiredError):
        ensure_transition_allowed(
            facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, has_summary=False, closing=True)
        )

    with pytest.raises(ChecksNotPassedError):
        ensure_transition_allowed(
            facts(
                TaskStatus.IN_PROGRESS,
                TaskStatus.DONE,
                pending_checks=(CheckGap(check_no=1, reason=CheckGapReason.NO_VERDICT),),
                closing=True,
            )
        )

    with pytest.raises(TaskHasUnclosedChildrenError):
        ensure_transition_allowed(
            facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, children=("TRK-4",), closing=True)
        )


def test_the_verdict_check_only_guards_the_way_into_done() -> None:
    """Шаг назад и отмена вердиктов не требуют: правило привязано к паре статусов."""
    ensure_transition_allowed(
        facts(TaskStatus.IN_PROGRESS, TaskStatus.OPEN, reason="нужен второй взгляд")
    )
    ensure_transition_allowed(
        facts(TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, reason="не нужна")
    )


# --- Проверки перехода задачи 24 ------------------------------------------------------


def test_an_open_blocker_keeps_the_task_out_of_work() -> None:
    """Обзорная проверка 1 на уровне домена: отказ называет открытые блокеры."""
    with pytest.raises(TaskBlockedError) as error:
        ensure_transition_allowed(
            facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, blockers=("TRK-2", "TRK-3"))
        )

    assert error.value.code == "task_blocked"
    assert error.value.status_code == 409
    assert error.value.details["blockers"] == ["TRK-2", "TRK-3"]

    ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, blockers=()))


def test_blockers_are_checked_only_on_the_way_into_work() -> None:
    """Закрытие и откат блокером не запрещены: связь мешает взять задачу, а не вести её."""
    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, blockers=("TRK-2",)))
    ensure_transition_allowed(
        facts(TaskStatus.OPEN, TaskStatus.CANCELLED, reason="передумали", blockers=("TRK-2",))
    )


def test_an_open_blocking_question_keeps_the_task_out_of_work() -> None:
    """Развилка 3 TRK-569#9 на уровне домена: отказ `409` называет вопросы адресами — и
    вопрос дела задачи, и вопрос её обсуждения (решение `TRK#51`, п. 4)."""
    with pytest.raises(TaskHasOpenBlockingQuestionsError) as error:
        ensure_transition_allowed(
            facts(
                TaskStatus.OPEN,
                TaskStatus.IN_PROGRESS,
                blocking_questions=("TRK-1#4", "TRK~2#3"),
            )
        )

    assert error.value.code == "task_has_open_blocking_questions"
    assert error.value.status_code == 409
    assert error.value.details == {
        "key": "TRK-1",
        "from": "open",
        "to": "in_progress",
        "questions": ["TRK-1#4", "TRK~2#3"],
    }

    ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, blocking_questions=()))


def test_blocking_questions_are_checked_only_on_the_way_into_work() -> None:
    """Вопрос держит вход в работу, а не её ход: задача в работе закрывается и уходит в
    `open` с открытым блокирующим вопросом — так и ждут ответа (`CONCEPT.md`, 4.6)."""
    ensure_transition_allowed(
        facts(
            TaskStatus.IN_PROGRESS, TaskStatus.OPEN, reason="жду TRK-1#4", blocking_questions=(4,)
        )
    )
    ensure_transition_allowed(
        facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, blocking_questions=(4,))
    )
    ensure_transition_allowed(
        facts(TaskStatus.OPEN, TaskStatus.CANCELLED, reason="не нужна", blocking_questions=(4,))
    )


def test_the_blockers_are_named_before_the_blocking_questions() -> None:
    """Порядок из таблицы валидаций `CONCEPT.md`, 3.3: блокер — строкой выше вопроса."""
    with pytest.raises(TaskBlockedError):
        ensure_transition_allowed(
            facts(
                TaskStatus.OPEN,
                TaskStatus.IN_PROGRESS,
                blockers=("TRK-2",),
                blocking_questions=(4,),
            )
        )


def test_unclosed_children_keep_the_parent_open() -> None:
    """Обзорная проверка 2 на уровне домена: отказ называет незакрытых детей."""
    with pytest.raises(TaskHasUnclosedChildrenError) as error:
        ensure_transition_allowed(
            facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, children=("TRK-4",))
        )

    assert error.value.code == "task_has_unclosed_children"
    assert error.value.status_code == 409
    assert error.value.details["children"] == ["TRK-4"]

    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, children=()))


def test_children_block_cancelling_the_parent_just_as_they_block_done() -> None:
    """Правило говорит о закрытии, а не о `done`: отмена ждёт тех же детей.

    До TRK-28 оно было названо для `done`, и отменить родителя с живыми детьми было
    можно. Это был разрыв в самом определении: закрытая задача — это `done` **или**
    `cancelled`, и отменённый родитель оставлял за собой работу, чья причина
    существовать только что исчезла.
    """
    with pytest.raises(TaskHasUnclosedChildrenError) as error:
        ensure_transition_allowed(
            facts(
                TaskStatus.IN_PROGRESS,
                TaskStatus.CANCELLED,
                reason="отказались",
                children=("TRK-4",),
            )
        )

    assert error.value.details["children"] == ["TRK-4"]

    ensure_transition_allowed(
        facts(TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, reason="отказались", children=())
    )


def test_an_unfilled_fact_forbids_the_move() -> None:
    """Значение по умолчанию запрещает переход: забытый факт не должен выглядеть успехом.

    Проверяется на **самой** структуре, а не через помощник тестов: у помощника
    значения по умолчанию обратные, и без этой проверки правило держалось бы только на
    комментарии.
    """
    unfilled = TransitionFacts(
        key="TRK-1",
        from_status=TaskStatus.IN_PROGRESS,
        to_status=TaskStatus.DONE,
        reason=None,
        sections=FILLED,
        checks=("первая", "вторая"),
    )

    with pytest.raises(ClosingNotATransitionError):
        ensure_transition_allowed(unfilled)

    with pytest.raises(SummaryRequiredError):
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.DONE,
                reason=None,
                sections=FILLED,
                checks=("первая", "вторая"),
                closing=True,
            )
        )

    with pytest.raises(ChecksNotPassedError) as error:
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.DONE,
                reason=None,
                sections=FILLED,
                checks=("первая", "вторая"),
                has_summary_since_in_progress=True,
                closing=True,
            )
        )

    assert error.value.details["checks"] == [
        {"check_no": 1, "reason": "no_verdict"},
        {"check_no": 2, "reason": "no_verdict"},
    ]

    with pytest.raises(TaskBlockedError) as blocked:
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.OPEN,
                to_status=TaskStatus.IN_PROGRESS,
                reason=None,
                sections=FILLED,
                checks=("первая",),
                has_summary_since_in_progress=True,
                assignee="claude",
                requester="claude",
            )
        )

    # Назвать блокеры нечем, поэтому отказ говорит причину прямо, а не пустым списком.
    assert blocked.value.details["reason"] == "blockers_not_collected"
    assert "blockers" not in blocked.value.details

    with pytest.raises(TaskHasOpenBlockingQuestionsError) as questions:
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.OPEN,
                to_status=TaskStatus.IN_PROGRESS,
                reason=None,
                sections=FILLED,
                checks=("первая",),
                open_blockers=(),
                assignee="claude",
                requester="claude",
            )
        )

    assert questions.value.details["reason"] == "questions_not_collected"
    assert "questions" not in questions.value.details

    with pytest.raises(TaskDeferredError) as deferred:
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.OPEN,
                to_status=TaskStatus.IN_PROGRESS,
                reason=None,
                sections=FILLED,
                checks=("первая",),
                open_blockers=(),
                open_blocking_questions=(),
                assignee="claude",
                requester="claude",
            )
        )

    assert deferred.value.details["reason"] == "deferral_not_collected"

    with pytest.raises(TaskHasUnclosedChildrenError) as children:
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.IN_PROGRESS,
                to_status=TaskStatus.DONE,
                reason=None,
                sections=FILLED,
                checks=(),
                has_summary_since_in_progress=True,
                checks_without_passed_verdict=(),
                closing=True,
            )
        )

    assert children.value.details["reason"] == "children_not_collected"

    with pytest.raises(TaskHasOpenDiscussionsError) as discussions:
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.OPEN,
                to_status=TaskStatus.CANCELLED,
                reason="передумали",
                sections=FILLED,
                checks=(),
                unclosed_children=(),
            )
        )

    assert discussions.value.details["reason"] == "discussions_not_collected"


def test_an_open_discussion_keeps_the_task_from_closing_and_cancelling() -> None:
    """Решение `TRK#51`, п. 4: пока привязанное обсуждение не закрыто, задачу не закрыть и
    не отменить; отказ называет обсуждения адресами. Вход в работу обсуждение без вопроса
    не держит — его держат только вопросы."""
    for to_status, reason in ((TaskStatus.DONE, None), (TaskStatus.CANCELLED, "передумали")):
        with pytest.raises(TaskHasOpenDiscussionsError) as error:
            ensure_transition_allowed(
                facts(TaskStatus.IN_PROGRESS, to_status, reason=reason, discussions=("TRK~2",))
            )
        assert error.value.code == "task_has_open_discussions"
        assert error.value.status_code == 409
        assert error.value.details == {
            "key": "TRK-1",
            "from": "in_progress",
            "to": to_status.value,
            "discussions": ["TRK~2"],
        }

    ensure_transition_allowed(
        facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, discussions=("TRK~2",))
    )
    ensure_transition_allowed(facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, discussions=()))


# --- Вход в работу только исполнителю (TRK-123) -----------------------------------------


def test_a_task_without_an_assignee_does_not_go_into_work() -> None:
    """Без исполнителя задача в работу не идёт — в том числе дождавшаяся в `open`."""
    with pytest.raises(AssigneeRequiredError) as error:
        ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, assignee=None))

    assert error.value.code == "assignee_required"
    assert error.value.status_code == 409
    assert error.value.details == {
        "key": "TRK-1",
        "from": "open",
        "to": "in_progress",
    }


def test_someone_other_than_the_assignee_cannot_take_the_task() -> None:
    """Отказ называет обоих: кому задача поручена и кто просит."""
    with pytest.raises(AssigneeMismatchError) as error:
        ensure_transition_allowed(
            facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, assignee="alice", requester="claude")
        )

    assert error.value.code == "assignee_mismatch"
    assert error.value.status_code == 409
    assert error.value.details["assignee"] == "alice"
    assert error.value.details["requester"] == "claude"


def test_the_assignee_is_compared_with_the_signature_regardless_of_case() -> None:
    """Подпись канонична (нижний регистр), `assignee` — свободная строка: `Claude` тот же."""
    ensure_transition_allowed(
        facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, assignee=" Claude ", requester="claude")
    )


def test_a_requester_without_a_signature_is_not_the_assignee() -> None:
    """Сам трекер подписи не имеет и в работу задачу не берёт."""
    with pytest.raises(AssigneeMismatchError) as error:
        ensure_transition_allowed(facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, requester=None))

    assert error.value.details["requester"] is None


def test_the_assignee_is_checked_only_on_the_way_into_work() -> None:
    """Задачи, уже стоящие в работе, правило не трогает: чужой ведёт, откатывает, отменяет."""
    ensure_transition_allowed(
        facts(TaskStatus.IN_PROGRESS, TaskStatus.DONE, assignee=None, requester="alice")
    )
    ensure_transition_allowed(
        facts(
            TaskStatus.IN_PROGRESS,
            TaskStatus.OPEN,
            reason="второй взгляд",
            assignee="claude",
            requester="alice",
        )
    )
    ensure_transition_allowed(facts(TaskStatus.BACKLOG, TaskStatus.OPEN, assignee=None))


def test_the_assignee_is_asked_before_the_blockers() -> None:
    """Сначала «кто», потом «когда»: не исполнителю не называют чужие блокеры."""
    with pytest.raises(AssigneeMismatchError):
        ensure_transition_allowed(
            facts(
                TaskStatus.OPEN,
                TaskStatus.IN_PROGRESS,
                assignee="alice",
                blockers=("TRK-2",),
            )
        )


def test_unfilled_assignee_facts_forbid_the_way_into_work() -> None:
    """Незаполненные факты исполнителя запрещают вход, а не пропускают его."""
    with pytest.raises(AssigneeRequiredError):
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.OPEN,
                to_status=TaskStatus.IN_PROGRESS,
                reason=None,
                sections=FILLED,
                checks=("первая",),
                open_blockers=(),
            )
        )
    with pytest.raises(AssigneeMismatchError):
        ensure_transition_allowed(
            TransitionFacts(
                key="TRK-1",
                from_status=TaskStatus.OPEN,
                to_status=TaskStatus.IN_PROGRESS,
                reason=None,
                sections=FILLED,
                checks=("первая",),
                open_blockers=(),
                assignee="claude",
            )
        )
