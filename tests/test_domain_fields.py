"""Валидатор значений и формат хранения в JSONB — без базы.

Главное здесь не «принимает правильное», а две вещи, за которые задача бралась:
формат записи в JSONB и то, что валидатор отдаёт **все** замечания сразу. Каждый тип
значения проверяется отдельно: разночтения в формате дадут молчаливые баги во всех
последующих задачах, которые этот JSONB читают.
"""

import pytest

from app.domain.errors import InvalidFieldKeyError, InvalidFieldRefError
from app.domain.fields import (
    MAX_MULTIPLE_VALUES,
    MAX_STRING_LENGTH,
    FieldOption,
    FieldSpec,
    FieldValueType,
    apply_value_changes,
    build_field_ref,
    format_field_ref,
    parse_field_ref,
    validate_field_key,
    validate_values,
)


def spec(
    value_type: FieldValueType,
    *,
    ref: str = "custom",
    is_multiple: bool = False,
    is_required: bool = False,
    options: tuple[FieldOption, ...] = (),
    default: object = None,
) -> FieldSpec:
    return FieldSpec(
        ref=ref,
        value_type=value_type,
        is_multiple=is_multiple,
        is_required=is_required,
        options=options,
        default=default,
    )


def reasons(raw: dict[str, object], specs: list[FieldSpec]) -> list[tuple[str, str]]:
    outcome = validate_values(raw, specs)
    return [(issue.field, issue.reason) for issue in outcome.issues]


# --- Адресация -------------------------------------------------------------------


def test_global_and_local_refs_are_parsed_the_same_way_as_catalog_refs() -> None:
    """Один формат на весь проект: `TRK.severity` разбирается как `TRK.open`."""
    assert parse_field_ref("severity") == build_field_ref("severity", queue_key=None)
    local = parse_field_ref("TRK.severity")
    assert (local.key, local.queue_key) == ("severity", "TRK")
    assert str(local) == "TRK.severity"


def test_ref_is_normalized_because_addressing_is_soft() -> None:
    assert str(parse_field_ref(" trk.SEVERITY ")) == "TRK.severity"


def test_broken_ref_is_rejected_with_the_expected_format() -> None:
    with pytest.raises(InvalidFieldRefError) as info:
        parse_field_ref("TRK.a.b")

    assert info.value.details["reason"] == "too_many_separators"
    assert "expected" in info.value.details


def test_system_field_names_cannot_be_taken_by_a_custom_field() -> None:
    """`status` и `assignee` — колонки задачи; кастомное поле с таким ключом
    оказалось бы недостижимым для языка запросов из задачи 12."""
    with pytest.raises(InvalidFieldKeyError) as info:
        validate_field_key("status")

    assert info.value.details["reason"] == "reserved"


def test_global_field_is_addressed_by_a_bare_key() -> None:
    assert format_field_ref("severity", queue_key=None) == "severity"
    assert format_field_ref("severity", queue_key="TRK") == "TRK.severity"


# --- Формат хранения по каждому типу ---------------------------------------------


@pytest.mark.parametrize(
    ("value_type", "given", "stored"),
    [
        (FieldValueType.STRING, "  Ускорить отчёт  ", "Ускорить отчёт"),
        (FieldValueType.TEXT, "line one\nline two", "line one\nline two"),
        (FieldValueType.NUMBER, 5, 5),
        (FieldValueType.NUMBER, 2.5, 2.5),
        (FieldValueType.BOOLEAN, True, True),
        (FieldValueType.DATE, "2026-08-27", "2026-08-27"),
        (FieldValueType.DATETIME, "2026-08-27T13:00:00+03:00", "2026-08-27T10:00:00+00:00"),
        (FieldValueType.ACTOR, "  Alice ", "alice"),
        (FieldValueType.ISSUE, "trk-123", "TRK-123"),
    ],
)
def test_each_value_type_is_stored_in_its_declared_shape(
    value_type: FieldValueType, given: object, stored: object
) -> None:
    """Формат хранения — контракт для всех последующих задач, поэтому он под тестом."""
    outcome = validate_values({"custom": given}, [spec(value_type)])

    assert outcome.is_valid, outcome.issues
    assert outcome.values == {"custom": stored}


def test_enum_stores_the_option_key_not_its_display_name() -> None:
    options = (FieldOption(key="critical", name="Критическая"),)
    outcome = validate_values({"custom": "critical"}, [spec(FieldValueType.ENUM, options=options)])

    assert outcome.values == {"custom": "critical"}


def test_datetime_without_a_timezone_is_rejected_rather_than_guessed() -> None:
    """Домыслить зону за клиента — значит выдать сдвиг, который заметят через месяц."""
    assert reasons({"custom": "2026-08-27T10:00:00"}, [spec(FieldValueType.DATETIME)]) == [
        ("custom", "timezone_required")
    ]


def test_date_does_not_accept_a_datetime_string() -> None:
    assert reasons({"custom": "2026-08-27T10:00:00+00:00"}, [spec(FieldValueType.DATE)]) == [
        ("custom", "invalid_date")
    ]


def test_boolean_is_not_a_number() -> None:
    """`bool` — подкласс `int`: без явной проверки `true` тихо стал бы единицей."""
    assert reasons({"custom": True}, [spec(FieldValueType.NUMBER)]) == [("custom", "type_mismatch")]


def test_number_does_not_accept_a_numeric_string() -> None:
    """JSON умеет числа сам: строка «5» — признак ошибки клиента, а не повод угадывать."""
    assert reasons({"custom": "5"}, [spec(FieldValueType.NUMBER)]) == [("custom", "type_mismatch")]


def test_single_line_field_rejects_a_line_break() -> None:
    """Иначе `string` и `text` отличались бы только названием."""
    assert reasons({"custom": "line one\nline two"}, [spec(FieldValueType.STRING)]) == [
        ("custom", "multiline_not_allowed")
    ]


def test_too_long_string_is_rejected_with_the_limit_in_details() -> None:
    outcome = validate_values(
        {"custom": "я" * (MAX_STRING_LENGTH + 1)}, [spec(FieldValueType.STRING)]
    )

    assert outcome.issues[0].reason == "too_long"
    assert outcome.issues[0].context["max"] == MAX_STRING_LENGTH


def test_issue_key_with_a_leading_zero_is_not_a_key() -> None:
    """`TRK-007` и `TRK-7` не должны указывать на одну задачу двумя способами."""
    assert reasons({"custom": "TRK-007"}, [spec(FieldValueType.ISSUE)]) == [
        ("custom", "invalid_issue_key")
    ]


# --- Множественность -------------------------------------------------------------


def test_multiple_field_stores_an_array() -> None:
    options = (FieldOption(key="api", name="API"), FieldOption(key="ui", name="UI"))
    outcome = validate_values(
        {"custom": ["api", "ui"]},
        [spec(FieldValueType.ENUM, is_multiple=True, options=options)],
    )

    assert outcome.values == {"custom": ["api", "ui"]}


def test_multiple_field_rejects_a_scalar_and_single_field_rejects_an_array() -> None:
    assert reasons({"custom": "api"}, [spec(FieldValueType.STRING, is_multiple=True)]) == [
        ("custom", "expected_array")
    ]
    assert reasons({"custom": ["api"]}, [spec(FieldValueType.STRING)]) == [
        ("custom", "unexpected_array")
    ]


def test_repeated_value_in_an_array_is_rejected_rather_than_deduplicated() -> None:
    """Тихая дедупликация вернула бы клиенту не то, что он прислал, и без единого слова."""
    assert reasons({"custom": ["api", "api"]}, [spec(FieldValueType.STRING, is_multiple=True)]) == [
        ("custom", "duplicate_values")
    ]


def test_empty_array_means_no_value_and_trips_a_required_field() -> None:
    single = spec(FieldValueType.STRING, is_multiple=True)
    assert validate_values({"custom": []}, [single]).values == {}

    required = spec(FieldValueType.STRING, is_multiple=True, is_required=True)
    assert reasons({"custom": []}, [required]) == [("custom", "required")]


def test_array_longer_than_the_ceiling_is_rejected() -> None:
    values = [str(index) for index in range(MAX_MULTIPLE_VALUES + 1)]
    outcome = validate_values({"custom": values}, [spec(FieldValueType.STRING, is_multiple=True)])

    assert outcome.issues[0].reason == "too_many_values"
    assert outcome.issues[0].context["max"] == MAX_MULTIPLE_VALUES


def test_every_broken_item_of_an_array_is_reported_with_its_index() -> None:
    outcome = validate_values(
        {"custom": ["2026-08-27", "вчера", "позавчера"]},
        [spec(FieldValueType.DATE, is_multiple=True)],
    )

    assert [issue.context["index"] for issue in outcome.issues] == [1, 2]


# --- Обязательность и значение по умолчанию --------------------------------------


def test_required_field_without_a_value_is_reported() -> None:
    assert reasons({}, [spec(FieldValueType.STRING, is_required=True)]) == [("custom", "required")]


def test_required_enum_reports_the_allowed_values() -> None:
    """Агент должен исправить запрос по ответу, не читая исходники."""
    options = (FieldOption(key="minor", name="Мелкая"),)
    outcome = validate_values({}, [spec(FieldValueType.ENUM, is_required=True, options=options)])

    assert outcome.issues[0].context["allowed"] == ["minor"]


def test_default_fills_an_absent_key_but_not_an_explicit_null() -> None:
    """Разница «не передано» против «передано как null» — сквозное правило проекта."""
    described = spec(FieldValueType.STRING, default="minor")

    assert validate_values({}, [described]).values == {"custom": "minor"}
    assert validate_values({"custom": None}, [described]).values == {}


def test_explicit_null_on_a_required_field_is_an_error() -> None:
    described = spec(FieldValueType.STRING, is_required=True, default="minor")

    assert reasons({"custom": None}, [described]) == [("custom", "required")]


def test_empty_string_counts_as_no_value() -> None:
    assert validate_values({"custom": "   "}, [spec(FieldValueType.STRING)]).values == {}
    assert reasons({"custom": "   "}, [spec(FieldValueType.STRING, is_required=True)]) == [
        ("custom", "required")
    ]


# --- Все ошибки сразу ------------------------------------------------------------


def test_validator_reports_every_problem_at_once() -> None:
    """Ради этого пункта задача и заведена: фронт подсвечивает всю форму за один ответ."""
    specs = [
        spec(FieldValueType.STRING, ref="summary_note", is_required=True),
        spec(FieldValueType.NUMBER, ref="estimate"),
        spec(FieldValueType.DATE, ref="release_date"),
    ]
    raw = {"estimate": "много", "release_date": "скоро", "нет_такого": 1}

    collected = reasons(raw, specs)

    assert sorted(collected) == [
        ("estimate", "type_mismatch"),
        ("release_date", "invalid_date"),
        ("summary_note", "required"),
        ("нет_такого", "invalid_ref"),
    ]


def test_unknown_field_is_reported_and_not_silently_dropped() -> None:
    assert reasons({"severity": "critical"}, []) == [("severity", "unknown_field")]


def test_two_keys_pointing_at_one_field_are_reported() -> None:
    """Иначе один тихо затёр бы другой, и какой именно — зависело бы от порядка ключей."""
    collected = reasons(
        {"TRK.severity": "a", "trk.SEVERITY": "b"},
        [spec(FieldValueType.STRING, ref="TRK.severity")],
    )

    assert ("TRK.severity", "duplicate_field") in collected


def test_issue_details_carry_the_field_and_its_own_reason() -> None:
    """`details` собирается из замечания целиком, и чужая причина её не перебивает."""
    outcome = validate_values({"TRK.a.b": 1}, [])

    assert outcome.issues[0].as_details()["reason"] == "invalid_ref"
    assert outcome.issues[0].as_details()["field"] == "TRK.a.b"


# --- Частичное обновление --------------------------------------------------------


def test_null_clears_a_value_and_an_absent_key_leaves_it_alone() -> None:
    current = {"severity": "critical", "TRK.component": ["api"]}

    merged = apply_value_changes(current, {"severity": None})

    assert merged == {"TRK.component": ["api"]}


def test_changes_are_addressed_softly_like_everything_else() -> None:
    current = {"TRK.severity": "critical"}

    merged = apply_value_changes(current, {"trk.SEVERITY": "minor"})

    assert merged == {"TRK.severity": "minor"}
