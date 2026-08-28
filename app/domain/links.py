"""Связи между задачами: типы, обратные стороны, канонический вид хранения.

Чистый Python: ни ORM, ни HTTP. Здесь описано то, что обязано быть одинаковым у
таблицы связей, у сценариев и у ответов API, — иначе одна и та же связь начнёт
называться по-разному в трёх местах.

## Связь хранится один раз, а показывается с двух сторон

У каждого типа есть обратная сторона (`depends_on` ↔ `blocks`). Хранить обе строки
нельзя: рано или поздно одна удалится, а вторая останется, и задача окажется
заблокирована задачей, которая её не блокирует. Поэтому направление приводится к
каноническому (`canonical_form`), в таблицу ложится одна строка, а имя связи для
конкретной задачи вычисляется при чтении (`visible_type`).

Следствие, ради которого это и сделано: уникальное ограничение на тройку
`(source, target, link_type)` ловит дубликат само. Без канонизации «A blocks B» и
«B depends_on A» были бы двумя разными строками про одно и то же.

`relates` симметричен — обратная сторона равна прямой, — и уникальное ограничение его
дубликат не поймает: `A relates B` и `B relates A` отличаются только порядком колонок.
Поэтому у симметричных типов пара дополнительно упорядочивается по ключу задачи.

## Эпик — это тип задачи, а не тип связи

Отдельной связи «эпик» нет и заводить её нельзя. Эпик — обычная задача с типом `epic`,
а входящие в него задачи держатся на той же иерархической связи, что и подзадачи.
Разделение на «подзадачи» и «содержимое эпика» ничего не добавляло бы: оно выводится
из типа задачи-родителя, а хранимая копия этого различия неизбежно разъехалась бы с
типом при первой же его смене.

От эпика в связях остаётся одно правило: **у задачи типа `epic` не может быть
родителя**. Эпик — верхний уровень планирования, и вложенный в задачу эпик означал бы,
что верхний уровень находится внутри нижнего. Проверка стоит в двух местах — при
создании связи и при смене типа задачи, — потому что иначе `PATCH` с новым типом
обошёл бы её с чёрного хода.

Отсюда же ответ на вопрос «в каком эпике задача»: это ближайший предок с типом `epic`.
Так как у эпика родителя нет, он всегда корень цепочки, и ответ считается подъёмом
вверх по одному родителю, а не хранится копией в каждой подзадаче.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import InvalidTreeDepthError


class LinkType(StrEnum):
    """Тип связи. Перечислены обе стороны каждой пары: клиент адресует любую из них."""

    RELATES = "relates"
    DEPENDS_ON = "depends_on"
    BLOCKS = "blocks"
    SUBTASK_OF = "subtask_of"
    PARENT_OF = "parent_of"
    DUPLICATES = "duplicates"
    DUPLICATED_BY = "duplicated_by"


#: Прямая сторона → обратная. Таблица полная и симметричная: `inverse(inverse(x)) == x`
#: для любого типа, и это стережёт тест. Неполная таблица означала бы связь, которую
#: видно только с одной стороны, — то есть ровно то, ради чего связь и заводят.
INVERSE_TYPES: dict[LinkType, LinkType] = {
    LinkType.RELATES: LinkType.RELATES,
    LinkType.DEPENDS_ON: LinkType.BLOCKS,
    LinkType.BLOCKS: LinkType.DEPENDS_ON,
    LinkType.SUBTASK_OF: LinkType.PARENT_OF,
    LinkType.PARENT_OF: LinkType.SUBTASK_OF,
    LinkType.DUPLICATES: LinkType.DUPLICATED_BY,
    LinkType.DUPLICATED_BY: LinkType.DUPLICATES,
}

#: Типы, в которых связь попадает в таблицу. Всё остальное — та же связь, записанная с
#: другой стороны. Набор продублирован ограничением CHECK в модели: инвариант
#: «в базе только канонические типы» слишком дорог, чтобы держаться на одном коде.
STORED_LINK_TYPES: frozenset[LinkType] = frozenset(
    {
        LinkType.RELATES,
        LinkType.DEPENDS_ON,
        LinkType.SUBTASK_OF,
        LinkType.DUPLICATES,
    }
)

#: Симметричные типы: обратная сторона совпадает с прямой.
SYMMETRIC_LINK_TYPES: frozenset[LinkType] = frozenset(
    link_type for link_type, opposite in INVERSE_TYPES.items() if link_type is opposite
)

#: Иерархия: ребро «ребёнок → родитель» и его обратная сторона. Только у этой пары есть
#: запрет на циклы и правило «не более одного родителя».
HIERARCHY_LINK_TYPES: frozenset[LinkType] = frozenset({LinkType.SUBTASK_OF, LinkType.PARENT_OF})

#: Тип, которым иерархия лежит в таблице: `source` — ребёнок, `target` — родитель.
HIERARCHY_STORED_TYPE = LinkType.SUBTASK_OF

#: Имя поля в журнале изменений задачи. Входит в `SYSTEM_FIELD_KEYS`
#: (`app/domain/fields.py`), поэтому кастомное поле с таким ключом завести нельзя и
#: строка истории читается однозначно.
LINKS_CHANGE_FIELD = "links"

#: Глубина дерева по умолчанию и потолок. Ограничение обязательное, а не декоративное:
#: без него один запрос к корню эпика вытащил бы всё, что под ним, вместе со всеми
#: связанными объектами каждой задачи.
DEFAULT_TREE_DEPTH = 3
MAX_TREE_DEPTH = 10

#: Потолок числа узлов в одной выдаче дерева. Срабатывает раньше глубины на широких
#: эпиках. Обрезка не молчаливая: узел, чьи дети не поместились, помечается
#: `has_more_children`, и клиент видит, что за ним ещё что-то есть.
MAX_TREE_NODES = 200

#: Предел подъёма по цепочке родителей при проверке цикла. Родитель у задачи один,
#: поэтому цепочка не ветвится и в здоровой базе короткая. Предел нужен на случай, если
#: цикл всё же появился (см. `docs/notes/links.md`): без него рекурсивный запрос
#: крутился бы вечно вместо того, чтобы честно отказать.
MAX_HIERARCHY_DEPTH = 100


@dataclass(frozen=True, slots=True)
class CanonicalLink:
    """Как запрошенная связь ложится в таблицу.

    `swapped` означает, что местами меняются сами задачи: клиент сказал «A blocks B»,
    а в таблицу пойдёт «B depends_on A». Возвращается решение, а не готовая пара задач,
    потому что домен не знает ORM-объектов — их подставляет сценарий.
    """

    link_type: LinkType
    swapped: bool


def inverse(link_type: LinkType) -> LinkType:
    """Обратная сторона связи. Таблица полная, поэтому `KeyError` здесь невозможен."""
    return INVERSE_TYPES[link_type]


def is_hierarchy(link_type: LinkType) -> bool:
    """Иерархическая ли связь: у неё есть родитель, ребёнок и запрет на циклы."""
    return link_type in HIERARCHY_LINK_TYPES


def canonical_form(link_type: LinkType, *, source_key: str, target_key: str) -> CanonicalLink:
    """Приводит запрошенную связь к тому виду, в котором она хранится.

    Три случая:

    - тип канонический и асимметричный (`depends_on`, `subtask_of`, `duplicates`) —
      ничего не меняется;
    - тип обратный (`blocks`, `parent_of`, `duplicated_by`) — задачи меняются местами,
      тип заменяется на прямой;
    - тип симметричный (`relates`) — прямой и обратный вид совпадают, поэтому порядок
      задаётся ключами: меньший ключ всегда становится `source`. Без этого
      `A relates B` и `B relates A` легли бы двумя строками, и уникальное ограничение
      их не поймало бы.

    Ключи сравниваются как строки. Строгого порядка «по номеру задачи» здесь не нужно —
    нужен любой устойчивый, одинаковый для обеих сторон.
    """
    if link_type in SYMMETRIC_LINK_TYPES:
        return CanonicalLink(link_type=link_type, swapped=source_key > target_key)
    if link_type in STORED_LINK_TYPES:
        return CanonicalLink(link_type=link_type, swapped=False)
    return CanonicalLink(link_type=inverse(link_type), swapped=True)


def visible_type(stored_type: LinkType, *, from_source: bool) -> LinkType:
    """Как хранимая связь называется со стороны одной из двух задач.

    `from_source` — смотрим ли мы со стороны той задачи, что лежит в колонке `source`.
    Со стороны `source` связь называется тем же типом, каким хранится, со стороны
    `target` — обратным.
    """
    return stored_type if from_source else inverse(stored_type)


def validate_tree_depth(depth: int | None) -> int:
    """Проверяет глубину дерева и подставляет значение по умолчанию.

    Выход за границы — ошибка, а не тихое срезание до потолка: то же правило, что у
    размера страницы (`app/db/pagination.py`). Срезание означало бы, что REST запрос
    отвергает границами параметра, а MCP молча выполняет по-своему.
    """
    if depth is None:
        return DEFAULT_TREE_DEPTH
    if not 1 <= depth <= MAX_TREE_DEPTH:
        raise InvalidTreeDepthError(
            details={"depth": depth, "min": 1, "max": MAX_TREE_DEPTH},
        )
    return depth
