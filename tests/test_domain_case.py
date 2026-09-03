"""Домен дела без базы: форма записи по типам, ссылки, выведенные заголовки.

Проверки, которым нужна база (существует ли адресат, есть ли такая запись), живут в
`tests/test_case_service.py`: домен в базу не ходит, и его правила должны быть
проверяемы без неё — иначе они незаметно переезжают в сценарий.
"""

from typing import Any

import pytest

from app.domain.case import (
    MAX_ENTRY_TITLE_LENGTH,
    EntryContext,
    EntryRef,
    EntryType,
    TaskRef,
    build_entry,
    parse_ref,
    summary_title,
)
from app.domain.errors import EntryFieldsInvalidError
from app.domain.fields import FieldProblem

CONTEXT = EntryContext(task_key="TRK-1", checks=("первая", "вторая", "третья"))

#: Первая строка `next_step` — то, чем сводка подписывается в описи дела.
FIRST_LINE = "Перенести вызов в конец create_task"

SUMMARY = {
    "done": "Разобрался, где сгорает номер",
    "remaining": "Перенести выдачу номера",
    "blockers": "нет",
    "next_step": FIRST_LINE,
}


def problems(error: pytest.ExceptionInfo[Any]) -> dict[str, str]:
    """Замечания в виде «поле — причина»: тесты смотрят на состав, а не на порядок."""
    return {problem["field"]: problem["reason"] for problem in error.value.details["fields"]}


# --- Тип записи ---------------------------------------------------------------------


def test_a_service_type_cannot_be_filed_by_hand() -> None:
    """Служебную запись подшивает сценарий: принять её тип снаружи — подделать историю."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.STATUS_CHANGED, title="Сам перевёл")

    assert error.value.code == "entry_fields_invalid"
    assert problems(error) == {"type": "service_type"}
    assert "status_changed" not in error.value.details["fields"][0]["allowed"]


def test_an_unknown_type_lists_the_allowed_ones() -> None:
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type="postscript", title="Что-то")

    assert problems(error) == {"type": "not_allowed"}
    assert "summary" in error.value.details["fields"][0]["allowed"]


# --- Сводка -------------------------------------------------------------------------


def test_a_summary_needs_all_four_parts_and_names_every_missing_one() -> None:
    """Обзорная проверка 1 на уровне домена: пустые части названы все сразу."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(
            CONTEXT, type=EntryType.SUMMARY, payload={**SUMMARY, "next_step": "", "done": ""}
        )

    assert problems(error) == {"done": "required", "next_step": "required"}


def test_a_summary_takes_its_title_from_the_first_line_of_the_next_step() -> None:
    draft = build_entry(
        CONTEXT,
        type=EntryType.SUMMARY,
        payload={**SUMMARY, "next_step": f"\n{FIRST_LINE}\nи дописать тест"},
    )

    assert draft.title == FIRST_LINE
    assert draft.payload["next_step"] == f"{FIRST_LINE}\nи дописать тест"


def test_a_long_first_line_is_shortened_rather_than_refused() -> None:
    """Отклонять справку из-за длинной первой строки значило бы терять её содержимое."""
    draft = build_entry(
        CONTEXT, type=EntryType.SUMMARY, payload={**SUMMARY, "next_step": "ш" * 500}
    )

    assert len(draft.title) == MAX_ENTRY_TITLE_LENGTH
    assert draft.title.endswith("…")


def test_a_summary_does_not_accept_a_title() -> None:
    """Второй способ задать опись развёл бы её с содержанием записи."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.SUMMARY, title="Своя строка", payload=SUMMARY)

    assert problems(error) == {"title": "not_allowed"}
    assert error.value.details["fields"][0]["derived_from"] == "next_step"


# --- Вопрос, ответ, вердикт ---------------------------------------------------------


def test_a_question_needs_at_least_one_addressee_and_an_explicit_blocking() -> None:
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(
            CONTEXT, type=EntryType.QUESTION, title="Что делать?", payload={"addressees": []}
        )

    assert problems(error) == {"addressees": "required", "blocking": "required"}


def test_addressees_are_canonicalised_and_deduplicated() -> None:
    draft = build_entry(
        CONTEXT,
        type=EntryType.QUESTION,
        title="Что делать?",
        payload={"addressees": ["Owner", "owner", " OWNER "], "blocking": True},
    )

    assert draft.payload == {"addressees": ["owner"], "blocking": True}


def test_a_verdict_names_the_allowed_range_of_check_numbers() -> None:
    """Обзорная проверка 6 на уровне домена: агент не обязан помнить длину списка."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.VERDICT, payload={"check_no": 5, "outcome": "passed"})

    problem = error.value.details["fields"][0]
    assert problem == {"field": "check_no", "reason": "out_of_range", "min": 1, "max": 3, "got": 5}


def test_a_verdict_takes_its_title_from_the_payload() -> None:
    draft = build_entry(
        CONTEXT,
        type=EntryType.VERDICT,
        body="Прогон зелёный",
        payload={"check_no": 2, "outcome": "failed"},
    )

    assert draft.title == "Verdict on check 2: failed"
    assert draft.payload == {"check_no": 2, "outcome": "failed"}


def test_an_answer_titles_itself_with_the_reference_to_the_question() -> None:
    draft = build_entry(CONTEXT, type=EntryType.ANSWER, body="Да", payload={"question_no": 7})

    assert draft.title == "Answer to TRK-1#7"


def test_an_outcome_outside_the_two_values_is_refused() -> None:
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.VERDICT, payload={"check_no": 1, "outcome": "maybe"})

    assert problems(error) == {"outcome": "not_allowed"}
    assert error.value.details["fields"][0]["allowed"] == ["passed", "failed"]


def test_a_payload_field_of_another_type_is_refused_rather_than_dropped() -> None:
    """Молча выброшенное поле означало бы, что агент считает записанным то, чего нет."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.NOTE, title="Заметка", payload={"check_no": 1})

    assert problems(error) == {"check_no": "not_allowed"}


# --- Ссылки -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("TRK-42", TaskRef(key="TRK-42")),
        ("trk-42", TaskRef(key="TRK-42")),
        ("TRK-42#12", EntryRef(key="TRK-42", no=12)),
        ("https://example.com/a#b", None),
        ("docs/CONCEPT.md", None),
        ("commit 4f2553c", None),
    ],
)
def test_a_reference_is_either_a_tracker_address_or_an_outside_one(
    ref: str, expected: TaskRef | EntryRef | None
) -> None:
    assert parse_ref(ref) == expected


@pytest.mark.parametrize("ref", ["TRK-42#0", "TRK-42#абв", "TRK-42#007"])
def test_a_near_miss_reference_is_refused_rather_than_taken_for_an_address(ref: str) -> None:
    """Иначе опечатка в ссылке молча становится непроверяемым адресом."""
    with pytest.raises(FieldProblem) as problem:
        parse_ref(ref)

    assert problem.value.details["reason"] == "malformed_entry_ref"


def test_tracker_references_are_stored_canonically_and_deduplicated() -> None:
    draft = build_entry(
        CONTEXT,
        type=EntryType.NOTE,
        title="Заметка",
        refs=["trk-42#7", "TRK-42#7", "https://example.com"],
    )

    assert draft.refs == ["TRK-42#7", "https://example.com"]
    assert draft.tracker_refs == (EntryRef(key="TRK-42", no=7),)


# --- Заголовок ----------------------------------------------------------------------


def test_a_titled_type_requires_a_title() -> None:
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.NOTE, title="   ")

    assert problems(error) == {"title": "required"}


def test_a_title_is_one_line() -> None:
    with pytest.raises(EntryFieldsInvalidError) as error:
        build_entry(CONTEXT, type=EntryType.FINDING, title="Первая строка\nи вторая")

    assert problems(error) == {"title": "multiline_not_allowed"}


def test_a_summary_title_falls_back_to_the_whole_text_when_it_has_no_line() -> None:
    """Текст из одних переводов строки формально непуст, а заголовку нужно хоть что-то."""
    assert summary_title("\n\n") == ""
