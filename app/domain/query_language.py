"""Язык запросов: разбор строки во внутреннее представление фильтра.

Чистый Python: ни ORM, ни базы. Разбор проверяет только форму — существуют ли поле,
статус и актор, знает `app/services/search.py`.

## Грамматика целиком

```
запрос      := выражение
выражение   := конъюнкция ( "or" конъюнкция )*
конъюнкция  := первичное ( "and" первичное )*
первичное   := "(" выражение ")" | условие
условие     := имя ":" [оператор] значения
оператор    := "=" | "!=" | ">" | ">=" | "<" | "<=" | "~" | "!~" | "in" | "not in"
значения    := значение ( "," значение )*
значение    := строка | слово | функция [ сдвиг ]
функция     := ("me" | "today" | "now" | "empty") "(" ")"
сдвиг       := ("+" | "-") ЧИСЛО ("d" | "w" | "h" | "m")
```

`and` связывает крепче, чем `or`: `a: 1 and b: 2 or c: 3` — это `(a and b) or c`.
Оператор по умолчанию — равенство; несколько значений через запятую превращают его во
вхождение в набор (`status: open, in_progress`).

## Чего в языке нет и не будет

Подзапросов, произвольных выражений, своих функций и сортировки. Набор операторов
фиксирован, всё остальное отклоняется с указанием позиции. Причина не в лени: язык
пишет агент, и чем меньше в нём способов ошибиться, тем меньше кругов «исправил —
вылезло другое». Сортировка задаётся отдельным параметром, потому что она не условие
отбора и в сохранённом фильтре живёт своей строкой.

## Слова языка нельзя использовать как имена полей без кавычек

`and`, `or`, `in`, `not` разбираются как слова языка везде, где их можно так понять.
Поле с таким ключом (шаблон ключей это допускает) адресуется в кавычках: `"and": 5`.
Кавычки — единственный способ написать и значение с пробелом, и значение со словом
языка внутри.

## Момент времени со временем пишется в кавычках

`deadline: >= 2026-08-28` разбирается без кавычек, а `deadline: >= "2026-08-28T10:00+00:00"`
— только в них: двоеточие внутри значения иначе неотличимо от двоеточия после имени
поля. Ограничение выбрано осознанно — альтернативой был бы лексер, догадывающийся о
смысле двоеточия по контексту, а догадка здесь означает молча разобранный не тот запрос.
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
    FunctionValue,
    Group,
    Junction,
    Literal,
    Node,
    Operator,
    SearchFilter,
    SearchFunction,
    SearchValue,
    SortTerm,
    plural_operator,
)

#: Слова языка. Список закрыт и совпадает с грамматикой: пополнять его — значит менять
#: язык, а не добавлять удобство.
KEYWORDS = frozenset({"and", "or", "in", "not"})

#: Единицы сдвига даты и их длительность в секундах. Минуты обозначены `m`, а не
#: месяцы: месяц — не фиксированная длительность, и «минус один месяц» от 31 марта не
#: имеет однозначного ответа. Понадобятся месяцы — они станут отдельной функцией.
DURATION_UNITS: dict[str, int] = {"m": 60, "h": 3600, "d": 86_400, "w": 604_800}

_DURATION_RE = re.compile(r"^(\d{1,6})([a-z])$")
_WORD_START_RE = re.compile(r"[A-Za-z0-9_]")
_WORD_BODY_RE = re.compile(r"[A-Za-z0-9_.\-]")

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
    PLUS = "plus"
    MINUS = "minus"
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
    parser = _Parser(text)
    root = parser.parse()
    return SearchFilter(root=root if isinstance(root, Group) else Group(Junction.AND, (root,)))


def parse_value_expression(text: str, *, position: int = 0) -> SearchValue:
    """Одно значение по правилам языка: литерал, `me()`, `today() - 7d`.

    Нужна структурному фильтру: `{"assignee": ["me()"]}` и `assignee: me()` обязаны
    значить одно и то же, а два разбора одного и того же синтаксиса неизбежно
    разошлись бы. Поэтому структурный фильтр разбирает свои значения этой же функцией,
    а не «просто строкой».
    """
    parser = _Parser(text, offset=position)
    value = parser.parse_single_value()
    return value


def parse_sort_terms(values: Sequence[str]) -> tuple[SortTerm, ...]:
    """`["-deadline", "priority"]` → ключи сортировки. Минус впереди — по убыванию.

    Разбор здесь, а не в схеме HTTP: сортировку задают и MCP, и сохранённый фильтр, и
    правило автоматики, а они идут мимо FastAPI.
    """
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
                details={"position": 0, "reason": "empty_sort_term", "term": raw},
            )
        if candidate.lower() in seen:
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
        self._offset = offset
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
            raise self._error(token, "expected_field_name")
        if token.type is TokenType.WORD and token.text.lower() in KEYWORDS:
            raise self._error(
                token,
                "keyword_as_field_name",
                hint='quote the name to use a language word as a field: "and": 1',
            )
        self._advance()

        colon = self._peek()
        if colon.type is not TokenType.COLON:
            raise self._error(colon, "expected_colon", expected=[":"], field=token.text)
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
        if token.type is TokenType.MINUS:
            # Отрицательное число: минус — отдельная лексема, потому что тот же символ
            # разделяет части ключа задачи (`TRK-1`) и даты (`2026-08-28`).
            self._advance()
            number = self._peek()
            if number.type is not TokenType.WORD or not number.text[:1].isdigit():
                raise self._error(number, "expected_value")
            self._advance()
            return Literal(text=f"-{number.text}", position=token.position)
        if token.type is TokenType.STRING:
            self._advance()
            return Literal(text=token.text, position=token.position, quoted=True)
        if token.type is not TokenType.WORD:
            raise self._error(token, "expected_value")

        self._advance()
        if self._peek().type is not TokenType.LPAREN:
            return Literal(text=token.text, position=token.position)
        return self._parse_function(token)

    def _parse_function(self, name: Token) -> FunctionValue:
        try:
            function = SearchFunction(name.text.lower())
        except ValueError as exc:
            raise self._error(
                name,
                "unknown_function",
                expected=sorted(f"{item.value}()" for item in SearchFunction),
            ) from exc
        self._advance()
        closing = self._peek()
        if closing.type is not TokenType.RPAREN:
            raise self._error(closing, "expected_closing_parenthesis", expected=[")"])
        self._advance()

        offset = self._parse_offset(function, name)
        return FunctionValue(function=function, offset_seconds=offset, position=name.position)

    def _parse_offset(self, function: SearchFunction, name: Token) -> int:
        total = 0
        while self._peek().type in {TokenType.PLUS, TokenType.MINUS}:
            sign_token = self._peek()
            if function not in {SearchFunction.TODAY, SearchFunction.NOW}:
                raise self._error(
                    sign_token,
                    "offset_not_allowed",
                    function=f"{function.value}()",
                    hint="only today() and now() accept an offset",
                )
            sign = 1 if sign_token.type is TokenType.PLUS else -1
            self._advance()
            duration = self._peek()
            if duration.type is not TokenType.WORD:
                raise self._error(
                    duration, "expected_duration", expected=["7d", "2w", "12h", "30m"]
                )
            self._advance()
            total += sign * self._duration_seconds(duration)
        return total

    def _duration_seconds(self, token: Token) -> int:
        match = _DURATION_RE.match(token.text.lower())
        if match is None or match.group(2) not in DURATION_UNITS:
            raise self._error(
                token,
                "invalid_duration",
                expected=sorted(f"<number>{unit}" for unit in DURATION_UNITS),
            )
        return int(match.group(1)) * DURATION_UNITS[match.group(2)]

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
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
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
