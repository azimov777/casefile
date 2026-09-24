"""Язык запросов: разбор строки во внутреннее представление фильтра.

Чистый Python: ни ORM, ни базы. Разбор проверяет только форму — существуют ли поле,
проект и статус, знает `app/services/search.py`.

## Грамматика целиком

```
запрос      := выражение
выражение   := конъюнкция ( "or" конъюнкция )*
конъюнкция  := первичное ( "and" первичное )*
первичное   := "(" выражение ")" | условие
условие     := имя ":" [оператор] значения
оператор    := "=" | "!=" | ">" | ">=" | "<" | "<=" | "~" | "!~" | "in" | "not in"
значения    := значение ( "," значение )*
значение    := строка | слово | "empty" "(" ")"
```

`and` связывает крепче, чем `or`: `a: 1 and b: 2 or c: 3` — это `(a and b) or c`.
Оператор по умолчанию — равенство; несколько значений через запятую превращают его во
вхождение в набор (`status: open, in_progress`).

## Чего в языке нет и не будет

Подзапросов, произвольных выражений, функций дат, `me()` и сортировки. Набор операторов
фиксирован, всё остальное отклоняется с указанием позиции. Причина не в лени: язык пишет
агент, и чем меньше в нём способов ошибиться, тем меньше кругов «исправил — вылезло
другое». Сортировка задаётся отдельным параметром, потому что она не условие отбора.

Единственная функция — `empty()`, и она не вычисляет ничего: это признак отсутствия
значения. Без неё «задачи без исполнителя» не выражались бы вовсе — пустая строка
исполнителем быть не может, а `assignee: ""` молча не нашло бы ничего.

## Оператор стоит после двоеточия, и это самая частая ошибка

`status in (open, in_progress)` — форма из SQL и из чужих трекеров, и агенты приносят её
раз за разом: в перечне операторов есть `in`, а где он пишется, перечень не говорит.
Верно `status: in open, in_progress` либо просто `status: open, in_progress` — несколько
значений через запятую и без оператора уже означают вхождение в набор.

Лечится это подсказкой в отказе (`QUERY_SHAPE_HINT` и `_condition_shape_hint`), а не
второй формой записи. Вторая форма — это второй разбор: проверяться будет один, а
расходиться они начнут на краевых случаях, которые никто не пишет нарочно. Скобки в
языке есть, но группируют они **условия**, а не значения: `(a: 1 or b: 2) and c: 3`.

## Слова языка нельзя использовать как имена полей без кавычек

`and`, `or`, `in`, `not` разбираются как слова языка везде, где их можно так понять.
Поля с такими именами в трекере нет, но правило названо здесь, а не выведено из списка
полей: список закрыт не языком, а концепцией, и грамматика обязана оставаться понятной
сама по себе. Кавычки — единственный способ написать и значение с пробелом, и значение,
похожее на вызов функции (`assignee: "empty()"`).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.errors import InvalidSearchQueryError
from app.domain.search import (
    MAX_CONDITIONS,
    MAX_GROUP_DEPTH,
    MAX_QUERY_LENGTH,
    MAX_SORT_TERMS,
    MAX_VALUES_PER_CONDITION,
    Condition,
    EmptyValue,
    Group,
    Junction,
    Literal,
    Node,
    Operator,
    SearchFilter,
    SearchValue,
    SortTerm,
    plural_operator,
    searchable_names,
    sortable_names,
    split_names,
)

#: Слова языка. Список закрыт и совпадает с грамматикой: пополнять его — значит менять
#: язык, а не добавлять удобство.
KEYWORDS = frozenset({"and", "or", "in", "not"})

#: Единственная функция языка. Именем, а не перечислением из одного члена: перечисление
#: обещало бы, что функций будет больше, а их не будет (см. докстринг модуля).
EMPTY_FUNCTION = "empty"

#: Примеры запросов, которые видит агент и человек: из них собраны описания поля `query`
#: в MCP и в REST, и они же прогоняются разбором в тесте. Список, а не текст в двух
#: описаниях: пример, который не разбирается, хуже отсутствующего — по нему учатся.
#:
#: Первый показывает связку условий, второй — оператор после двоеточия, третий —
#: сравнение и вхождение подстроки, четвёртый — `empty()` и `or`. Оператор обязан быть
#: хотя бы в одном: из перечня «есть `in`» без примера вырастает `status in (...)`.
QUERY_EXAMPLES: tuple[str, ...] = (
    "project: TRK and status: open and blocked: false",
    "status: in open, in_progress",
    "priority: >= high and text: ~ login",
    "assignee: empty() or open_questions: > 0",
)

#: Форма из SQL и чужих трекеров, которую агенты приносят чаще всего. Названа в описаниях
#: ошибкой прямо: перечислить операторы и не сказать, где они пишутся, — и есть ловушка.
QUERY_WRONG_SHAPE = "status in (open, in_progress)"

#: Как то же самое пишется на этом языке. Стоит рядом с ошибочной формой везде, где та
#: упомянута: «так нельзя» без «а как можно» стоит агенту ещё одного хода.
QUERY_RIGHT_SHAPE = "status: in open, in_progress"

#: Тело слова — `\w` в юникодном смысле плюс точка и дефис. Не латиница: значениями
#: здесь бывают пользовательские данные — метки и куски названий, — и они по-русски.
#: С латинским классом `text: ключ` требовал бы кавычек, а без них отвечал бы
#: «неожиданный символ» на самый частый запрос агента.
_WORD_START_RE = re.compile(r"\w")
_WORD_BODY_RE = re.compile(r"[\w.\-]")

_TWO_CHAR_OPERATORS = {
    ">=": Operator.GTE,
    "<=": Operator.LTE,
    "!=": Operator.NE,
    "!~": Operator.NOT_CONTAINS,
}
_ONE_CHAR_OPERATORS = {"=": Operator.EQ, ">": Operator.GT, "<": Operator.LT, "~": Operator.CONTAINS}

_QUOTES = "\"'"


class TokenType(StrEnum):
    WORD = "word"
    STRING = "string"
    OPERATOR = "operator"
    COLON = "colon"
    COMMA = "comma"
    LPAREN = "lparen"
    RPAREN = "rparen"
    END = "end"


@dataclass(frozen=True, slots=True)
class Token:
    """Разобранная лексема. Позиция — индекс первого символа в исходной строке, с нуля.

    Позиция тащится через весь разбор именно ради сообщения об ошибке: агент исправляет
    запрос по нему, и «ошибка где-то в строке» отправляет его в перебор.
    """

    type: TokenType
    text: str
    position: int


def parse_query(text: str) -> SearchFilter:
    """Строка запроса → внутреннее представление фильтра.

    Пустая строка — законный фильтр без условий, а не ошибка: это «все задачи», и
    отдельный способ сказать то же самое заводить незачем.
    """
    if len(text) > MAX_QUERY_LENGTH:
        raise InvalidSearchQueryError(
            details={
                "position": MAX_QUERY_LENGTH,
                "reason": "query_too_long",
                "max": MAX_QUERY_LENGTH,
                "got": len(text),
            },
        )
    if not text.strip():
        return SearchFilter()
    root = _Parser(text).parse()
    return SearchFilter(root=root if isinstance(root, Group) else Group(Junction.AND, (root,)))


def parse_value_expression(text: str, *, position: int = 0) -> SearchValue:
    """Одно значение по правилам языка: литерал или `empty()`.

    Здесь значение — кусок строки запроса, и границы ему задаёт синтаксис: пробел
    кончает слово, кавычки его продолжают. Значению структурного параметра границы
    задал протокол, и разбирается оно иначе — `parse_structured_value`.
    """
    return _Parser(text, offset=position).parse_single_value()


def parse_structured_value(text: str) -> SearchValue:
    """Одно значение структурного параметра: литерал целиком или `empty()`.

    Текст **не разбирается**, и это главное отличие от `parse_value_expression`. У
    структурного параметра границы значения задал протокол: `?text=выдача ключей` — это
    одно значение с пробелом внутри, а не два слова и отказ разбора. Разбирать его
    правилами языка значило бы требовать кавычек там, где кавычки уже не нужны, — и
    ровно этим поле «Текст» в интерфейсе отказывало человеку на втором слове (TRK-21).

    Кавычки поэтому тоже часть значения: `?text=он сказал "нет"` ищет подстроку вместе
    с кавычками. Цена названа прямо: подстроку `empty()` структурным параметром не
    найти — она всегда прочтётся маркером. Язык для этого остаётся: `text: "empty()"`.

    Единственное, что разбирается, — сам маркер, и разбирается он парсером языка, а не
    сравнением строк: `?assignee=empty()` и `assignee: empty()` обязаны значить одно и
    то же, а два толкования одного синтаксиса однажды разойдутся.
    """
    if _is_empty_marker(text):
        return EmptyValue()
    return Literal(text=text)


def _is_empty_marker(text: str) -> bool:
    """Написан ли здесь `empty()` — по мерке языка, а не по совпадению строк."""
    try:
        return isinstance(_Parser(text).parse_single_value(), EmptyValue)
    except InvalidSearchQueryError:
        return False


def parse_sort_terms(values: Sequence[str]) -> tuple[SortTerm, ...]:
    """`["-updated_at", "priority"]` → ключи сортировки. Минус впереди — по убыванию.

    Разбор здесь, а не в схеме HTTP: сортировку задают и REST, и MCP, а второй идёт
    мимо FastAPI. Имена не проверяются — это делает сценарий, у которого есть список
    допустимых ключей; здесь проверяется только форма записи.

    Ключи принимаются и повтором параметра, и перечислением через запятую — тем же
    правилом, что и выбор полей (`split_names`).
    """
    values = split_names(values)
    if len(values) > MAX_SORT_TERMS:
        raise InvalidSearchQueryError(
            details={
                "position": 0,
                "reason": "too_many_sort_terms",
                "max": MAX_SORT_TERMS,
                "got": len(values),
            },
        )
    terms: list[SortTerm] = []
    seen: set[str] = set()
    for raw in values:
        candidate = raw.strip()
        descending = candidate.startswith("-")
        if candidate[:1] in {"-", "+"}:
            candidate = candidate[1:].strip()
        if not candidate:
            raise InvalidSearchQueryError(
                details={
                    "position": 0,
                    "reason": "empty_sort_term",
                    "term": raw,
                    "allowed": sortable_names(),
                },
            )
        if candidate.lower() in seen:
            # Повтор ключа — не «уточнение порядка», а ошибка: второе упоминание не
            # влияет ни на что, и клиент об этом не узнал бы.
            raise InvalidSearchQueryError(
                details={"position": 0, "reason": "duplicate_sort_term", "term": candidate},
            )
        seen.add(candidate.lower())
        terms.append(SortTerm(name=candidate, descending=descending))
    return tuple(terms)


class _Parser:
    """Рекурсивный спуск по грамматике. Состояние — позиция в списке лексем.

    Отдельный класс, а не набор функций: позиция и счётчик условий нужны каждому шагу
    разбора, и протаскивать их аргументами через шесть уровней значило бы писать
    сигнатуры длиннее самих правил.
    """

    def __init__(self, text: str, *, offset: int = 0) -> None:
        self._text = text
        self._tokens = _tokenize(text, offset=offset)
        self._index = 0
        self._conditions = 0

    # --- Точки входа -------------------------------------------------------------

    def parse(self) -> Node:
        node = self._parse_or(depth=0)
        token = self._peek()
        if token.type is not TokenType.END:
            raise self._error(token, "unexpected_token", expected=["and", "or", "end of query"])
        return node

    def parse_single_value(self) -> SearchValue:
        value = self._parse_value()
        token = self._peek()
        if token.type is not TokenType.END:
            raise self._error(token, "unexpected_token", expected=["end of value"])
        return value

    # --- Правила -----------------------------------------------------------------

    def _parse_or(self, *, depth: int) -> Node:
        nodes = [self._parse_and(depth=depth)]
        while self._keyword("or"):
            self._advance()
            nodes.append(self._parse_and(depth=depth))
        if len(nodes) == 1:
            return nodes[0]
        return Group(Junction.OR, tuple(nodes))

    def _parse_and(self, *, depth: int) -> Node:
        nodes = [self._parse_primary(depth=depth)]
        while self._keyword("and"):
            self._advance()
            nodes.append(self._parse_primary(depth=depth))
        if len(nodes) == 1:
            return nodes[0]
        return Group(Junction.AND, tuple(nodes))

    def _parse_primary(self, *, depth: int) -> Node:
        token = self._peek()
        if token.type is TokenType.LPAREN:
            if depth + 1 > MAX_GROUP_DEPTH:
                raise self._error(token, "too_deep", max=MAX_GROUP_DEPTH)
            self._advance()
            node = self._parse_or(depth=depth + 1)
            closing = self._peek()
            if closing.type is not TokenType.RPAREN:
                raise self._error(closing, "unbalanced_parenthesis", expected=[")"])
            self._advance()
            return node
        return self._parse_condition()

    def _parse_condition(self) -> Condition:
        token = self._peek()
        if token.type not in {TokenType.WORD, TokenType.STRING}:
            raise self._error(token, "expected_field_name", allowed=searchable_names())
        if token.type is TokenType.WORD and token.text.lower() in KEYWORDS:
            raise self._error(
                token,
                "keyword_as_field_name",
                hint='quote the name to use a language word as a field: "and": 1',
            )
        self._advance()

        colon = self._peek()
        if colon.type is not TokenType.COLON:
            raise self._error(
                colon,
                "expected_colon",
                expected=[":"],
                field=token.text,
                **self._condition_shape_hint(token),
            )
        self._advance()

        operator = self._parse_operator()
        values = self._parse_values()

        self._conditions += 1
        if self._conditions > MAX_CONDITIONS:
            raise self._error(token, "too_many_conditions", max=MAX_CONDITIONS)

        return Condition(
            name=token.text,
            operator=plural_operator(operator, len(values)),
            values=values,
            position=token.position,
        )

    def _condition_shape_hint(self, field: Token) -> dict[str, str]:
        """Подсказка «как надо» там, где вместо двоеточия стоит оператор.

        Двоеточия нет, а следом идёт оператор — значит написана форма из другого языка
        (`status in (...)`, `project = UI`), и мы знаем и поле, и оператор, которые человек
        или агент имел в виду. Ошибка без такой подсказки стоит хода: `expected_colon`
        говорит, чего не хватает, но не говорит, куда это поставить.

        Подсказка показывает **форму**, а не восстановленное условие целиком: значения
        пришлось бы собирать обратно из лексем, разбирая заодно скобки, а форма и есть
        то, чего не хватает — значения писавший помнит.

        Пусто, когда следом не оператор: тогда это просто опечатка, и выдумывать по ней
        нечего.
        """
        operator = self._operator_ahead()
        if operator is None:
            return {}
        if operator is Operator.EQ:
            # Равенство — оператор по умолчанию, и писать его незачем.
            shape = f"{field.text}: value"
        elif operator in {Operator.IN, Operator.NOT_IN}:
            shape = f"{field.text}: {operator.value} value, value"
        else:
            shape = f"{field.text}: {operator.value} value"
        return {"hint": f"the operator goes after the colon, values need no parentheses: {shape}"}

    def _operator_ahead(self) -> Operator | None:
        """Оператор на текущем месте, не сдвигая разбор. `not in` — две лексемы."""
        token = self._peek()
        if token.type is TokenType.OPERATOR:
            return Operator(token.text)
        if token.type is not TokenType.WORD:
            return None
        if token.text.lower() == "in":
            return Operator.IN
        if token.text.lower() == "not":
            following = self._tokens[min(self._index + 1, len(self._tokens) - 1)]
            if following.type is TokenType.WORD and following.text.lower() == "in":
                return Operator.NOT_IN
        return None

    def _parse_operator(self) -> Operator:
        token = self._peek()
        if token.type is TokenType.OPERATOR:
            self._advance()
            return Operator(token.text)
        if token.type is TokenType.WORD and token.text.lower() == "in":
            self._advance()
            return Operator.IN
        if token.type is TokenType.WORD and token.text.lower() == "not":
            self._advance()
            following = self._peek()
            if following.type is not TokenType.WORD or following.text.lower() != "in":
                raise self._error(following, "expected_operator", expected=["in"])
            self._advance()
            return Operator.NOT_IN
        # Оператор не обязателен: `status: open` — это равенство. Отсутствие оператора
        # не ошибка, поэтому здесь нет проверки — ошибку даст разбор значения.
        return Operator.EQ

    def _parse_values(self) -> tuple[SearchValue, ...]:
        values = [self._parse_value()]
        while self._peek().type is TokenType.COMMA:
            self._advance()
            values.append(self._parse_value())
            if len(values) > MAX_VALUES_PER_CONDITION:
                raise self._error(self._peek(), "too_many_values", max=MAX_VALUES_PER_CONDITION)
        return tuple(values)

    def _parse_value(self) -> SearchValue:
        token = self._peek()
        if token.type is TokenType.STRING:
            self._advance()
            return Literal(text=token.text, position=token.position, quoted=True)
        if token.type is not TokenType.WORD:
            raise self._error(token, "expected_value")

        self._advance()
        if self._peek().type is not TokenType.LPAREN:
            return Literal(text=token.text, position=token.position)
        return self._parse_function(token)

    def _parse_function(self, name: Token) -> EmptyValue:
        if name.text.lower() != EMPTY_FUNCTION:
            raise self._error(name, "unknown_function", expected=[f"{EMPTY_FUNCTION}()"])
        self._advance()
        closing = self._peek()
        if closing.type is not TokenType.RPAREN:
            raise self._error(closing, "expected_closing_parenthesis", expected=[")"])
        self._advance()
        return EmptyValue(position=name.position)

    # --- Внутреннее --------------------------------------------------------------

    def _peek(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> None:
        if self._tokens[self._index].type is not TokenType.END:
            self._index += 1

    def _keyword(self, word: str) -> bool:
        token = self._peek()
        return token.type is TokenType.WORD and token.text.lower() == word

    def _error(self, token: Token, reason: str, **context: Any) -> InvalidSearchQueryError:
        details: dict[str, Any] = {
            "query": self._text,
            "position": token.position,
            "reason": reason,
        }
        if token.type is not TokenType.END:
            details["token"] = token.text
        details.update(context)
        return InvalidSearchQueryError(details=details)


def _tokenize(text: str, *, offset: int = 0) -> list[Token]:
    """Строка → список лексем. Последняя всегда `END`, поэтому разбор не проверяет конец.

    Лексер намеренно ничего не знает о смысле: слово `and` он отдаёт как слово, а
    решает парсер по месту. Иначе поле с именем `and` в кавычках пришлось бы объяснять
    лексеру, у которого контекста нет.
    """
    tokens: list[Token] = []
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        position = index + offset

        if char in _QUOTES:
            value, index = _read_string(text, index, offset=offset)
            tokens.append(Token(TokenType.STRING, value, position))
            continue

        pair = text[index : index + 2]
        if pair in _TWO_CHAR_OPERATORS:
            tokens.append(Token(TokenType.OPERATOR, _TWO_CHAR_OPERATORS[pair].value, position))
            index += 2
            continue
        if char in _ONE_CHAR_OPERATORS:
            tokens.append(Token(TokenType.OPERATOR, _ONE_CHAR_OPERATORS[char].value, position))
            index += 1
            continue

        simple = _SIMPLE_TOKENS.get(char)
        if simple is not None:
            tokens.append(Token(simple, char, position))
            index += 1
            continue

        if _WORD_START_RE.match(char):
            # Дефис входит в тело слова, а не разделяет его: ключ задачи (`TRK-42`) и
            # метка (`ui-kit`) — одно значение, и разбор их на три лексемы пришлось бы
            # склеивать обратно, гадая, где был пробел.
            end = index + 1
            while end < size and _WORD_BODY_RE.match(text[end]):
                end += 1
            tokens.append(Token(TokenType.WORD, text[index:end], position))
            index = end
            continue

        raise InvalidSearchQueryError(
            details={
                "query": text,
                "position": position,
                "reason": "unexpected_character",
                "token": char,
            },
        )

    tokens.append(Token(TokenType.END, "", size + offset))
    return tokens


_SIMPLE_TOKENS: dict[str, TokenType] = {
    ":": TokenType.COLON,
    ",": TokenType.COMMA,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
}


def _read_string(text: str, start: int, *, offset: int) -> tuple[str, int]:
    """Читает значение в кавычках. `\\` экранирует кавычку и сам себя.

    Незакрытая кавычка — ошибка с позицией самой кавычки, а не конца строки: искать
    надо там, где строка началась, а не там, где кончился запрос.
    """
    quote = text[start]
    parts: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            parts.append(text[index + 1])
            index += 2
            continue
        if char == quote:
            return "".join(parts), index + 1
        parts.append(char)
        index += 1
    raise InvalidSearchQueryError(
        details={
            "query": text,
            "position": start + offset,
            "reason": "unterminated_string",
            "token": quote,
        },
    )
