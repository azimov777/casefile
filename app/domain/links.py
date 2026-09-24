"""Связи между задачами: виды, обратные стороны, канонический вид хранения.

Чистый Python: ни ORM, ни HTTP. Здесь то, что обязано быть одинаковым у таблицы связей,
у сценариев и у ответов API, — иначе одна и та же связь начнёт называться по-разному в
трёх местах.

## Вид связи называет роль **своей** задачи

`A blocks B` читается «A блокирует B», `A child B` — «A ребёнок B». Вид всегда говорит,
кем приходится задача, у которой связь запрашивают или в чьём деле лежит запись, — а не
кем приходится вторая сторона. Обратное соглашение выглядит так же и означает
противоположное, поэтому оно названо здесь, а не подразумевается.

## Связь хранится один раз, а показывается с двух сторон

У каждого вида есть обратный (`blocks` ↔ `blocked_by`). Хранить обе строки нельзя: рано
или поздно одна удалится, а вторая останется, и задача окажется заблокирована задачей,
которая её не блокирует. Поэтому направление приводится к каноническому
(`canonical_form`), в таблицу ложится одна строка, а имя связи для конкретной задачи
вычисляется при чтении (`visible_kind`).

Следствие, ради которого это и сделано: уникальное ограничение на тройку
`(source, target, kind)` ловит дубликат само.

`relates` симметричен — обратная сторона равна прямой, — и уникальное ограничение его
дубликат не поймает: `A relates B` и `B relates A` отличаются только порядком колонок.
Поэтому у симметричных видов пара дополнительно упорядочивается по ключу задачи.

## Иерархия и блокировки — два независимых графа

Цикл запрещён в каждом из них по отдельности и **не** проверяется между ними: концепция
прямо разрешает родителю быть `blocked_by` своих детей — так выражается «жду завершения
декомпозиции» (`CONCEPT.md`, 3.5). Общий граф объявил бы это кольцом и запретил
единственный законный способ подождать декомпозицию.

Родитель у задачи один, детей сколько угодно — отдельное решение владельца
(2026-09-24, TRK-135), третья валидация иерархии рядом с отсутствием циклов и
незакрытыми детьми перед закрытием. Второй родитель — отказ `task_has_parent`
(`app/services/links.py`, `add_link`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.errors import InvalidLinkKindError, LinkSelfError


class LinkKind(StrEnum):
    """Вид связи. Перечислены обе стороны каждой пары: клиент адресует любую из них."""

    PARENT = "parent"
    CHILD = "child"
    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"
    RELATES = "relates"


#: Вид → обратный. Таблица полная и симметричная: `inverse(inverse(x)) == x` для любого
#: вида, и это стережёт тест. Неполная таблица означала бы связь, которую видно только с
#: одной стороны, — то есть ровно то, ради чего связь и заводят.
INVERSE_KINDS: Mapping[LinkKind, LinkKind] = {
    LinkKind.PARENT: LinkKind.CHILD,
    LinkKind.CHILD: LinkKind.PARENT,
    LinkKind.BLOCKS: LinkKind.BLOCKED_BY,
    LinkKind.BLOCKED_BY: LinkKind.BLOCKS,
    LinkKind.RELATES: LinkKind.RELATES,
}

#: Виды, в которых связь попадает в таблицу. Всё остальное — та же связь, записанная с
#: другой стороны. Набор продублирован ограничением CHECK в модели: инвариант «в базе
#: только канонические виды» слишком дорог, чтобы держаться на одном коде.
#:
#: Читается строка так: `source` **является** этим для `target`. У `parent` источник —
#: родитель, у `blocks` источник блокирует цель.
STORED_LINK_KINDS: frozenset[LinkKind] = frozenset(
    {LinkKind.PARENT, LinkKind.BLOCKS, LinkKind.RELATES}
)

#: Симметричные виды: обратная сторона совпадает с прямой.
SYMMETRIC_LINK_KINDS: frozenset[LinkKind] = frozenset(
    kind for kind, opposite in INVERSE_KINDS.items() if kind is opposite
)

#: Виды, чья связь меняет поведение задачи: `blocks`/`blocked_by` держат вход в
#: `in_progress`, `parent`/`child` держат закрытие родителя — и `done`, и `cancelled`.
#: Такую связь у закрытой задачи не ставят и не снимают — она задним числом сделала бы
#: неверным уже случившееся (`CONCEPT.md`, 3.5). Набор перечислен, а не выведен из
#: симметричности вида: «влияет на переходы» и «совпадает со своей обратной стороной» —
#: разные свойства, у нынешних видов совпавшие случайно.
BEHAVIOURAL_LINK_KINDS: frozenset[LinkKind] = frozenset(
    {LinkKind.PARENT, LinkKind.CHILD, LinkKind.BLOCKS, LinkKind.BLOCKED_BY}
)

#: Хранимые виды, в которых кольцо запрещено. Каждый — свой граф, и проверка идёт по
#: рёбрам **одного** вида: см. раздел «Иерархия и блокировки — два независимых графа».
ACYCLIC_LINK_KINDS: frozenset[LinkKind] = frozenset({LinkKind.PARENT, LinkKind.BLOCKS})

#: Предел подъёма по цепочке при проверке цикла. Кольцо в базе появиться всё-таки может
#: (проверка живёт в сценарии и на гонку двух одновременных запросов не рассчитана,
#: `docs/notes/links.md`), и без ограничителя рекурсивный запрос крутился бы вечно
#: вместо того, чтобы честно отказать.
MAX_LINK_DEPTH = 100


@dataclass(frozen=True, slots=True)
class CanonicalLink:
    """Как запрошенная связь ложится в таблицу.

    `swapped` означает, что местами меняются сами задачи: клиент сказал «A blocked_by
    B», а в таблицу пойдёт «B blocks A». Возвращается решение, а не готовая пара задач,
    потому что домен не знает ORM-объектов — их подставляет сценарий.
    """

    kind: LinkKind
    swapped: bool


#: Кем приходится другая сторона этой задаче — по виду связи **своей** задачи. Для
#: заголовка записи о связи (TRK-135): «Link added: parent TRK-3» читали как «родитель —
#: TRK-3», хотя вид называл роль своей задачи. Фраза с подлежащим не читается двояко.
OTHER_SIDE_PHRASES: Mapping[LinkKind, str] = {
    LinkKind.PARENT: "{other} is a child of this task",
    LinkKind.CHILD: "{other} is the parent of this task",
    LinkKind.BLOCKS: "{other} is blocked by this task",
    LinkKind.BLOCKED_BY: "{other} blocks this task",
    LinkKind.RELATES: "{other} relates to this task",
}


def other_side_phrase(kind: LinkKind, other_key: str) -> str:
    """Связь словами, с подлежащим — другой стороной: `TRK-3 is a child of this task`."""
    return OTHER_SIDE_PHRASES[kind].format(other=other_key)


def inverse(kind: LinkKind) -> LinkKind:
    """Обратная сторона связи. Таблица полная, поэтому `KeyError` здесь невозможен."""
    return INVERSE_KINDS[kind]


def is_acyclic(stored_kind: LinkKind) -> bool:
    """Нужна ли этому хранимому виду проверка кольца."""
    return stored_kind in ACYCLIC_LINK_KINDS


def changes_behaviour(kind: LinkKind) -> bool:
    """Влияет ли связь этого вида на переходы задачи и на её признаки.

    По этому и различаются связи закрытой задачи: влияющую нельзя ни поставить, ни снять,
    а `relates` — чистый контекст, и статус сторон его не ограничивает. Именно им
    выражается родословная: продолжение, выросшее из закрытой задачи, видно с обеих
    сторон в карточке (`CONCEPT.md`, 3.5).
    """
    return kind in BEHAVIOURAL_LINK_KINDS


def canonical_form(kind: LinkKind, *, source_key: str, target_key: str) -> CanonicalLink:
    """Приводит запрошенную связь к тому виду, в котором она хранится.

    Три случая:

    - вид канонический и асимметричный (`parent`, `blocks`) — ничего не меняется;
    - вид обратный (`child`, `blocked_by`) — задачи меняются местами, вид заменяется
      на прямой;
    - вид симметричный (`relates`) — прямой и обратный вид совпадают, поэтому порядок
      задаётся ключами: меньший ключ всегда становится `source`. Без этого
      `A relates B` и `B relates A` легли бы двумя строками, и уникальное ограничение
      их не поймало бы.

    Ключи сравниваются как строки. Строгого порядка «по номеру задачи» здесь не нужно —
    нужен любой устойчивый, одинаковый для обеих сторон.
    """
    if kind in SYMMETRIC_LINK_KINDS:
        return CanonicalLink(kind=kind, swapped=source_key > target_key)
    if kind in STORED_LINK_KINDS:
        return CanonicalLink(kind=kind, swapped=False)
    return CanonicalLink(kind=inverse(kind), swapped=True)


def visible_kind(stored_kind: LinkKind, *, from_source: bool) -> LinkKind:
    """Как хранимая связь называется со стороны одной из двух задач.

    `from_source` — смотрим ли мы со стороны той задачи, что лежит в колонке `source`.
    Со стороны `source` связь называется тем же видом, каким хранится, со стороны
    `target` — обратным.
    """
    return stored_kind if from_source else inverse(stored_kind)


def parse_link_kind(value: Any) -> LinkKind:
    """Строка из MCP и член перечисления из REST приводятся к одному значению.

    Отдельный код ошибки, а не общий `validation_error`: по нему агент понимает, что
    промахнулся именно видом связи, и видит в подробностях весь допустимый набор.
    """
    try:
        return LinkKind(value)
    except ValueError:
        raise InvalidLinkKindError(
            details={"kind": value, "allowed": [kind.value for kind in LinkKind]},
        ) from None


def ensure_not_self(key: str, other_key: str) -> None:
    """Связь задачи с самой собой запрещена — и у симметричного вида тоже.

    Проверка здесь, а не только ограничением в базе: `relates` сам с собой кольцом не
    является, поэтому проверка цикла его не поймает, и без этой строки он дошёл бы до
    базы и получил бы там непереводимый `IntegrityError` вместо предметного отказа.
    """
    if key == other_key:
        raise LinkSelfError(details={"key": key})
