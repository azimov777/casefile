"""Домен без базы: разбор языка запросов и внутреннее представление фильтра.

Разбор проверяется здесь, а не через HTTP, ровно потому, что он не зависит от базы:
грамматика, приоритет связок, потолки и — главное — позиция символа в каждой ошибке.
Позиция и есть то, по чему агент исправляет запрос, и тест на неё стережёт обещание
внятной ошибки.
"""

import pytest

from app.domain.errors import InvalidSearchQueryError
from app.domain.fields import SYSTEM_FIELD_KEYS
from app.domain.query_language import parse_query, parse_sort_terms, parse_value_expression
from app.domain.search import (
    MAX_CONDITIONS,
    MAX_GROUP_DEPTH,
    SEARCHABLE_SYSTEM_FIELDS,
    SYSTEM_FIELD_ALIASES,
    Condition,
    FunctionValue,
    Group,
    Junction,
    Literal,
    Operator,
    SearchFunction,
    combine,
    count_conditions,
    depth_of,
    is_reserved_name,
    system_field_spec,
)


def _conditions(query: str) -> list[Condition]:
    parsed = parse_query(query)
    assert parsed.root is not None
    return [node for node in parsed.root.nodes if isinstance(node, Condition)]


def test_the_example_from_the_specification_parses() -> None:
    """Строка из ТЗ разбирается целиком: имена, функции и оператор сравнения."""
    conditions = _conditions(
        "queue: TRK and status: open and assignee: me() and deadline: <= today()"
    )

    assert [condition.name for condition in conditions] == [
        "queue",
        "status",
        "assignee",
        "deadline",
    ]
    assert conditions[2].values == (FunctionValue(SearchFunction.ME, position=42),)
    assert conditions[3].operator is Operator.LTE


def test_several_values_turn_equality_into_membership() -> None:
    """`status: open, in_progress` — это вхождение в набор, а не равенство списку."""
    condition = _conditions("status: open, in_progress")[0]

    assert condition.operator is Operator.IN
    assert [value.text for value in condition.values] == ["open", "in_progress"]


def test_and_binds_tighter_than_or() -> None:
    """`a and b or c` — это `(a and b) or c`, как в любом языке с обоими связками."""
    parsed = parse_query("queue: TRK and status: open or priority: blocker")

    assert parsed.root is not None
    assert parsed.root.junction is Junction.OR
    assert isinstance(parsed.root.nodes[0], Group)
    assert parsed.root.nodes[0].junction is Junction.AND


def test_parentheses_group_conditions() -> None:
    parsed = parse_query("queue: TRK and (status: open or priority: blocker)")

    assert parsed.root is not None
    assert parsed.root.junction is Junction.AND
    assert depth_of(parsed.root) == 2


def test_a_relative_date_becomes_an_offset_in_seconds() -> None:
    """`today() - 7d` разбирается один раз: сценарию сдвиг достаётся числом."""
    value = parse_value_expression("today() - 7d")

    assert value == FunctionValue(SearchFunction.TODAY, offset_seconds=-604_800)


def test_offsets_add_up() -> None:
    assert parse_value_expression("now() + 1d + 12h").offset_seconds == 86_400 + 43_200


def test_only_date_functions_accept_an_offset() -> None:
    """`me() - 1d` бессмысленно, и молча отбросить сдвиг нельзя."""
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query("assignee: me() - 1d")

    assert error.value.details["reason"] == "offset_not_allowed"


def test_quotes_carry_spaces_and_language_words() -> None:
    """Кавычки — единственный способ написать значение с пробелом и поле-слово языка."""
    condition = _conditions('text: "выдача ключей"')[0]
    assert condition.values == (Literal("выдача ключей", position=6, quoted=True),)

    assert _conditions('"and": 1')[0].name == "and"


def test_an_empty_query_is_a_filter_without_conditions() -> None:
    """Пустая строка означает «все задачи», а не ошибку: второго способа сказать это нет."""
    assert parse_query("   ").is_empty


@pytest.mark.parametrize(
    ("query", "reason", "position"),
    [
        ("queue TRK", "expected_colon", 6),
        ("queue: ", "expected_value", 7),
        ('text: "unterminated', "unterminated_string", 6),
        ("queue: TRK and", "expected_field_name", 14),
        ("(queue: TRK", "unbalanced_parenthesis", 11),
        ("queue: TRK)", "unexpected_token", 10),
        ("assignee: nobody()", "unknown_function", 10),
        ("deadline: >= today() - 7x", "invalid_duration", 23),
        ("queue: TRK#", "unexpected_character", 10),
        ("and: 1", "keyword_as_field_name", 0),
    ],
)
def test_a_parse_error_names_the_reason_and_the_position(
    query: str,
    reason: str,
    position: int,
) -> None:
    """«invalid query» без позиции отправляет агента в слепой перебор — этого быть не должно."""
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query(query)

    assert error.value.details["reason"] == reason
    assert error.value.details["position"] == position
    assert error.value.details["query"] == query


def test_nesting_deeper_than_allowed_is_rejected() -> None:
    query = "(" * (MAX_GROUP_DEPTH + 1) + "queue: TRK" + ")" * (MAX_GROUP_DEPTH + 1)

    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query(query)

    assert error.value.details["reason"] == "too_deep"


def test_too_many_conditions_are_rejected() -> None:
    """Потолок назван прямо: запрос на сотню условий строится дольше, чем выполняется."""
    query = " and ".join(f"queue: Q{index}" for index in range(MAX_CONDITIONS + 1))

    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query(query)

    assert error.value.details["reason"] == "too_many_conditions"


def test_sort_terms_read_the_leading_minus_as_descending() -> None:
    terms = parse_sort_terms(["-deadline", "priority"])

    assert [(term.name, term.descending) for term in terms] == [
        ("deadline", True),
        ("priority", False),
    ]


def test_a_repeated_sort_key_is_rejected() -> None:
    """Второй раз тот же ключ ничего не упорядочивает и означает опечатку в запросе."""
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_sort_terms(["deadline", "-deadline"])

    assert error.value.details["reason"] == "duplicate_sort_term"


def test_combining_filters_keeps_every_condition() -> None:
    """Склейка источников — это `and`, и она не теряет условий ни одного из них."""
    merged = combine([parse_query("queue: TRK"), parse_query("status: open or status: closed")])

    assert count_conditions(merged.root) == 3
    assert merged.root is not None
    assert merged.root.junction is Junction.AND


def test_combining_nothing_gives_a_filter_without_conditions() -> None:
    assert combine([]).is_empty


def test_every_searchable_name_is_reserved_by_the_field_registry() -> None:
    """Иначе одноимённое кастомное поле стало бы недостижимым для поиска — молча.

    Это и есть договор между реестром полей и языком запросов: имя, которое поиск
    понимает сам, реестр обязан запрещать в ключах кастомных полей.
    """
    searchable = {spec.field.value for spec in SEARCHABLE_SYSTEM_FIELDS.values()}

    assert searchable <= SYSTEM_FIELD_KEYS
    assert set(SYSTEM_FIELD_ALIASES) <= SYSTEM_FIELD_KEYS


def test_a_reserved_name_without_a_filter_is_not_a_custom_field() -> None:
    """`sprint` появится в задаче 11; до тех пор запрос по нему — отказ, а не JSONB.

    Провалиться в реестр такое имя не должно: поиск по несуществующему кастомному полю
    отдал бы пустую выдачу, и это выглядело бы как «ничего не нашлось».
    """
    assert system_field_spec("sprint") is None
    assert is_reserved_name("sprint")
    assert is_reserved_name("links")
    assert not is_reserved_name("severity")


def test_a_name_that_got_its_filter_leaves_the_reserved_set() -> None:
    """`project` перестал быть недоступным в задаче 10 — вычитанием, а не правкой списка.

    Набор недоступных имён считается как «зарезервировано системой минус то, у чего есть
    описание фильтра». Тест стережёт именно этот механизм: если следующая задача добавит
    поле, забыв убрать имя из отдельного списка, ошибка вылезет здесь, а не пустой
    выдачей у клиента.
    """
    assert system_field_spec("project") is not None
    assert not is_reserved_name("project")


def test_a_queue_prefixed_name_is_never_a_system_field() -> None:
    """У системных полей области действия нет: `TRK.status` — это кастомное поле очереди."""
    assert system_field_spec("TRK.status") is None


def test_the_type_alias_resolves_to_the_issue_type() -> None:
    spec = system_field_spec("type")

    assert spec is not None
    assert spec.field.value == "issue_type"
