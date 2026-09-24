"""Домен отбора без базы: разбор языка запросов, позиция ошибки, склейка фильтров.

База здесь не нужна и не должна быть нужна: разбор проверяет только форму, а знание о
том, какие бывают проекты и статусы, живёт в сценарии. Если тесту разбора понадобилась
сессия — значит, проверка уехала не в тот слой.
"""

import pytest

from app.domain.errors import InvalidSearchQueryError
from app.domain.query_language import (
    QUERY_EXAMPLES,
    QUERY_RIGHT_SHAPE,
    QUERY_WRONG_SHAPE,
    parse_query,
    parse_sort_terms,
    parse_value_expression,
)
from app.domain.search import (
    MAX_CONDITIONS,
    MAX_GROUP_DEPTH,
    MAX_QUERY_LENGTH,
    MAX_SORT_TERMS,
    Condition,
    EmptyValue,
    Group,
    Junction,
    Literal,
    Operator,
    SearchField,
    SearchFilter,
    SortKey,
    combine,
    count_conditions,
    depth_of,
    plural_operator,
    search_field_spec,
    searchable_names,
    sortable_names,
)


def only(query: str) -> Condition:
    """Единственное условие разобранного запроса: у большинства проверок оно одно."""
    parsed = parse_query(query)
    assert parsed.root is not None
    assert len(parsed.root.nodes) == 1
    node = parsed.root.nodes[0]
    assert isinstance(node, Condition)
    return node


# --- Условие ---------------------------------------------------------------------------


def test_a_bare_condition_is_equality() -> None:
    condition = only("status: open")

    assert condition.name == "status"
    assert condition.operator is Operator.EQ
    assert condition.values == (Literal(text="open", position=8),)


def test_several_values_turn_equality_into_membership() -> None:
    """`=` со списком — это `in`, и превращение делает разбор, а не компилятор."""
    condition = only("status: open, in_progress")

    assert condition.operator is Operator.IN
    assert [value.text for value in condition.values] == ["open", "in_progress"]  # type: ignore[union-attr]


def test_negation_with_several_values_turns_into_not_in() -> None:
    condition = only("status: != done, cancelled")

    assert condition.operator is Operator.NOT_IN


@pytest.mark.parametrize(
    ("text", "operator"),
    [
        ("priority: >= high", Operator.GTE),
        ("priority: > low", Operator.GT),
        ("open_questions: <= 2", Operator.LTE),
        ("open_questions: < 1", Operator.LT),
        ("assignee: != alice", Operator.NE),
        ("text: ~ ключ", Operator.CONTAINS),
        ("text: !~ ключ", Operator.NOT_CONTAINS),
        ("status: in open", Operator.IN),
        ("status: not in done", Operator.NOT_IN),
    ],
)
def test_every_operator_of_the_grammar_is_parsed(text: str, operator: Operator) -> None:
    assert only(text).operator is operator


def test_a_hyphen_stays_inside_a_value() -> None:
    """Имя `release-bot` — одно значение: дефис входит в тело слова, а не разделяет его."""
    condition = only("assignee: release-bot")

    assert condition.values == (Literal(text="release-bot", position=10),)


def test_a_quoted_value_keeps_spaces_and_is_marked_quoted() -> None:
    condition = only('text: "выдача ключей"')

    assert condition.values == (Literal(text="выдача ключей", position=6, quoted=True),)


def test_empty_is_a_marker_and_not_a_literal() -> None:
    """`empty()` — признак отсутствия значения; такое имя адресуется кавычками."""
    assert only("assignee: empty()").values == (EmptyValue(position=10),)
    assert only('assignee: "empty()"').values == (
        Literal(text="empty()", position=10, quoted=True),
    )


# --- Связки и группы -------------------------------------------------------------------


def test_and_binds_tighter_than_or() -> None:
    """`a and b or c` — это `(a and b) or c`, и это свойство грамматики, а не скобок."""
    parsed = parse_query("project: TRK and status: open or priority: critical")

    assert parsed.root is not None
    assert parsed.root.junction is Junction.OR
    first, second = parsed.root.nodes
    assert isinstance(first, Group)
    assert first.junction is Junction.AND
    assert isinstance(second, Condition)


def test_parentheses_override_precedence() -> None:
    parsed = parse_query("project: TRK and (status: open or priority: critical)")

    assert parsed.root is not None
    assert parsed.root.junction is Junction.AND
    assert depth_of(parsed.root) == 2
    assert count_conditions(parsed.root) == 3


def test_an_empty_query_is_a_filter_without_conditions() -> None:
    """Пустая строка — это «все задачи», а не ошибка: второго способа сказать это нет."""
    assert parse_query("   ").is_empty


# --- Отказы с позицией -----------------------------------------------------------------


def test_a_missing_colon_names_the_field_and_the_position() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query("status open")

    assert raised.value.details["reason"] == "expected_colon"
    assert raised.value.details["position"] == 7
    assert raised.value.details["field"] == "status"


def test_an_unbalanced_parenthesis_points_at_the_end_of_the_group() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query("(status: open")

    assert raised.value.details["reason"] == "unbalanced_parenthesis"
    assert raised.value.details["position"] == len("(status: open")


def test_an_unterminated_string_points_at_the_opening_quote() -> None:
    """Позиция — начало строки, а не её конец: искать надо там, где кавычка открылась."""
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query('text: "выдача')

    assert raised.value.details["reason"] == "unterminated_string"
    assert raised.value.details["position"] == 6


def test_a_language_word_as_a_field_name_is_refused_with_a_hint() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query("and: 1")

    assert raised.value.details["reason"] == "keyword_as_field_name"
    assert "quote" in raised.value.details["hint"]


def test_an_unknown_function_lists_the_only_one_there_is() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query("assignee: me()")

    assert raised.value.details["reason"] == "unknown_function"
    assert raised.value.details["expected"] == ["empty()"]


def test_a_stray_character_is_refused_with_its_position() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query("status: open & priority: high")

    assert raised.value.details["reason"] == "unexpected_character"
    assert raised.value.details["position"] == 13


def test_a_missing_field_name_lists_the_allowed_ones() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query(": open")

    assert raised.value.details["allowed"] == searchable_names()


# --- Потолки ---------------------------------------------------------------------------


def test_a_query_over_the_length_limit_is_refused_before_tokenizing() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query("x" * (MAX_QUERY_LENGTH + 1))

    assert raised.value.details["reason"] == "query_too_long"


def test_too_many_conditions_are_refused() -> None:
    query = " and ".join(["status: open"] * (MAX_CONDITIONS + 1))

    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query(query)

    assert raised.value.details["reason"] == "too_many_conditions"


def test_too_deep_nesting_is_refused() -> None:
    depth = MAX_GROUP_DEPTH + 1
    query = "(" * depth + "status: open" + ")" * depth

    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_query(query)

    assert raised.value.details["reason"] == "too_deep"


# --- Значение структурного фильтра -----------------------------------------------------


def test_a_structured_value_goes_through_the_same_grammar() -> None:
    """Одна функция разбора на оба входа — единственное, что удерживает их вместе."""
    assert parse_value_expression("empty()") == EmptyValue()
    assert parse_value_expression("TRK") == Literal(text="TRK")


def test_a_structured_value_with_a_tail_is_refused() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_value_expression("open and status: done")

    assert raised.value.details["reason"] == "unexpected_token"


# --- Сортировка ------------------------------------------------------------------------


def test_a_leading_minus_means_descending() -> None:
    terms = parse_sort_terms(["-updated_at", "priority"])

    assert [(term.name, term.descending) for term in terms] == [
        ("updated_at", True),
        ("priority", False),
    ]


def test_a_repeated_sort_key_is_refused() -> None:
    """Второе упоминание ключа не влияет ни на что, и клиент об этом не узнал бы."""
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_sort_terms(["key", "-key"])

    assert raised.value.details["reason"] == "duplicate_sort_term"


def test_too_many_sort_keys_are_refused() -> None:
    with pytest.raises(InvalidSearchQueryError) as raised:
        parse_sort_terms(["key", "updated_at", "priority", "-key"])

    assert raised.value.details["reason"] in {"too_many_sort_terms", "duplicate_sort_term"}
    # Потолок достижим: ключей сортировки не меньше, чем терминов разрешено просить.
    # Раньше здесь стояло равенство — но это было совпадением чисел, а не правилом:
    # потолок ограничивает стоимость запроса, а не пересказывает словарь ключей.
    assert len(sortable_names()) >= MAX_SORT_TERMS


# --- Наборы полей ----------------------------------------------------------------------


def test_every_concept_field_has_a_spec() -> None:
    """Поля отбора перечислены концепцией (4.4); описание должно быть у каждого."""
    for name in (
        "project",
        "parent",
        "status",
        "assignee",
        "priority",
        "blocked",
        "open_questions",
        "open_blocking_questions",
        "open_remarks",
        "remarks_in_work",
        "text",
    ):
        assert search_field_spec(name) is not None, name


def test_a_sort_key_is_not_automatically_a_filter_field() -> None:
    """`updated_at` сортирует, но не фильтрует — и это решение, а не пропуск.

    Функций дат в языке нет, и обещать отбор по времени обновления значило бы обещать
    их. Ключ задачи с TRK-76 стоит в обоих наборах, и это тоже решение: по нему и
    спрашивают про названные дела, и упорядочивают выдачу.
    """
    assert search_field_spec("updated_at") is None
    assert search_field_spec("key") is not None
    assert {SortKey.KEY.value, SortKey.UPDATED_AT.value} <= set(sortable_names())


def test_a_field_name_is_matched_case_insensitively() -> None:
    assert search_field_spec("Status") is search_field_spec("status")


def test_the_names_in_both_sets_are_those_you_both_filter_and_order_by() -> None:
    """Пересечение словарей отбора и порядка — не случайность, а список по существу.

    Приоритет и время последней записи это то, по чему одинаково осмысленно и отбирать
    («что горит», «что шевелилось за сутки»), и сортировать. Ключ задачи — то, чем
    сессия называет свои дела в отборе и чем задаётся естественный порядок списка.
    Остальные имена живут только в одном словаре, и держать их в обоих было бы
    обещанием, которого нет.
    """
    assert set(searchable_names()) & set(sortable_names()) == {
        SearchField.KEY.value,
        SearchField.PRIORITY.value,
        SearchField.LAST_ENTRY_AT.value,
    }


# --- Склейка ---------------------------------------------------------------------------


def test_two_filters_are_combined_by_and() -> None:
    merged = combine([parse_query("project: TRK"), parse_query("status: open")])

    assert merged.root is not None
    assert merged.root.junction is Junction.AND
    assert count_conditions(merged.root) == 2


def test_combining_nothing_gives_an_empty_filter() -> None:
    assert combine([SearchFilter(), SearchFilter()]).is_empty


def test_plural_operator_only_touches_equality() -> None:
    assert plural_operator(Operator.EQ, 2) is Operator.IN
    assert plural_operator(Operator.NE, 2) is Operator.NOT_IN
    assert plural_operator(Operator.GT, 2) is Operator.GT
    assert plural_operator(Operator.EQ, 1) is Operator.EQ


# --- Форма условия: чему учит отказ ---------------------------------------------------


def test_the_sql_shape_is_refused_with_the_right_shape_in_the_details() -> None:
    """Обзорная проверка 2: `status in (...)` отвечает не только «нет двоеточия».

    Форма из SQL — самая частая ошибка агента: в перечне операторов есть `in`, а где он
    пишется, перечень не говорит. Отказ обязан сказать это сам, иначе следующий ход
    уходит на угадывание.
    """
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query(QUERY_WRONG_SHAPE)

    details = error.value.details
    assert details["reason"] == "expected_colon"
    assert details["field"] == "status"
    # Подсказка показывает форму с тем же полем и тем же оператором, что написали.
    assert details["hint"] == (
        "the operator goes after the colon, values need no parentheses: status: in value, value"
    )


def test_the_hint_filled_with_the_values_parses_into_the_intended_condition() -> None:
    """Подсказка не просто читается — по ней чинится запрос, и это проверяется разбором.

    Подставляем в форму из подсказки те значения, которые стояли в скобках, и требуем,
    чтобы вышло ровно то условие, которое имелось в виду: вхождение статуса в набор.
    """
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query(QUERY_WRONG_SHAPE)

    shape = str(error.value.details["hint"]).split(": ", 1)[1]
    values = iter(["open", "in_progress"])
    repaired = " ".join(
        next(values) + word.removeprefix("value") if word.startswith("value") else word
        for word in shape.split(" ")
    )

    assert repaired == QUERY_RIGHT_SHAPE
    condition = only(repaired)
    assert condition.name == "status"
    assert condition.operator is Operator.IN
    assert [value.text for value in condition.values] == ["open", "in_progress"]  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("query", "hint_tail"),
    [
        ("project = UI", "project: value"),
        ("priority >= high", "priority: >= value"),
        ("status not in open, done", "status: not in value, value"),
        ("text ~ ключ", "text: ~ value"),
    ],
)
def test_the_hint_repeats_the_operator_that_was_written(query: str, hint_tail: str) -> None:
    """Подсказка идёт от написанного, а не от одного заученного примера.

    Равенство при этом показывается без оператора: `=` — умолчание языка, и писать его
    незачем. Остальные операторы повторяются как есть, включая двусложный `not in`.
    """
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query(query)

    assert str(error.value.details["hint"]).endswith(hint_tail)


def test_an_ordinary_typo_gets_no_invented_hint() -> None:
    """Подсказка появляется только там, где верная форма выводима из места ошибки.

    После имени поля стоит не оператор, а значение — что человек имел в виду, отсюда
    не видно, и выдумывать нечего. Подсказка «на всякий случай» хуже её отсутствия:
    её пробуют, она не помогает, и доверие к следующей теряется.
    """
    with pytest.raises(InvalidSearchQueryError) as error:
        parse_query("status open")

    details = error.value.details
    assert details["reason"] == "expected_colon"
    assert "hint" not in details


def test_every_example_of_the_description_parses() -> None:
    """Обзорная проверка 3: примеры из описания — рабочие запросы, а не иллюстрации.

    Пример, который не разбирается, хуже отсутствующего: по нему учатся, и ошибка
    расходится по всем задачам, где агент его скопировал.
    """
    for example in QUERY_EXAMPLES:
        assert parse_query(example).root is not None, example

    # Хотя бы один показывает оператор: из перечня «есть `in`» без примера и вырастает
    # форма из SQL, ради которой заведена подсказка выше.
    assert any(
        " in " in example or ": >" in example or ": ~" in example for example in QUERY_EXAMPLES
    )

    # А ошибочная форма остаётся ошибочной: она названа в описании именно такой.
    with pytest.raises(InvalidSearchQueryError):
        parse_query(QUERY_WRONG_SHAPE)
