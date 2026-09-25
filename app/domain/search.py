"""Внутреннее представление отбора задач: во что сходятся язык запросов и структурный фильтр.

Чистый Python: ни ORM, ни HTTP. Здесь описано, **что** ищем; во что это превращается в
SQL — в `app/db/repositories/search.py`, а разрешение имён и значений против проектов и
перечислений — в `app/services/search.py`.

## Почему представление одно

Строка `project: TRK and status: open` и структурный фильтр `?project=TRK&status=open`
обязаны давать **идентичный** результат. Единственный способ этого добиться — свести оба
входа к одному объекту до того, как начнётся построение запроса. Две независимые
реализации разошлись бы на первом же краевом случае (пустое значение, отрицание,
несколько значений), и агент с фронтендом получили бы разные ответы на одинаковый по
смыслу вопрос — молча.

## Две стадии, и это не усложнение

1. **Разобранный фильтр** (`SearchFilter`): имена полей и значения — ещё строки, ровно
   такие, какими их написал клиент. Домен не знает ни проектов, ни того, какие задачи
   существуют, поэтому проверить их здесь нечем.
2. **Разрешённый фильтр** (`ResolvedFilter`): имя стало полем отбора, значение —
   идентификатором проекта, членом перечисления, числом или строкой.

Между стадиями стоит `app/services/search.py` — единственное место, которое видит базу.
Разделение нужно затем, чтобы разбор языка проверялся без базы, а разрешение имён было
одной функцией и для языка, и для структурного фильтра.

## Отбирать и сортировать можно по разным полям, и это не оговорка

Набор полей отбора и набор ключей сортировки пересекаются не целиком (`CONCEPT.md`,
4.4): по времени обновления сортируют, но не фильтруют — функций дат в языке нет.
Поэтому наборы объявлены двумя перечислениями, а не одним с признаками: общий список с
двумя флагами читался бы как «поле почти всё умеет», и в отказе пришлось бы объяснять,
какой из двух наборов имелся в виду.

Ключ задачи стоит в обоих. По одному ключу задачу читают по адресу `GET /tasks/{key}`,
но вопрос «что сейчас с этими пятью» одним адресом не выражается вовсе, а по статусу
выражается выборкой всего проекта с отбором глазами (TRK-76).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: Потолки языка и фильтра. Ограничения неочевидные, поэтому названы прямо: фильтр
#: приезжает и строкой запроса, и набором параметров, а запрос на тысячу условий
#: превратился бы в план, который PostgreSQL строит дольше, чем выполняет.
MAX_CONDITIONS = 50
MAX_GROUP_DEPTH = 5
MAX_VALUES_PER_CONDITION = 100
MAX_SORT_TERMS = 3
MAX_QUERY_LENGTH = 4096


class Operator(StrEnum):
    """Набор операторов фиксирован: язык — не SQL.

    `IN` и `NOT_IN` отдельными членами, хотя в языке пишутся тем же `=` со списком через
    запятую: представление обязано различать «равно одному» и «входит в набор», иначе
    компилятор гадал бы по длине списка.
    """

    EQ = "="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    CONTAINS = "~"
    NOT_CONTAINS = "!~"
    IN = "in"
    NOT_IN = "not in"


#: Операторы отрицания: у них общее правило по пустому значению — строка без значения
#: условию удовлетворяет. `assignee: != alice` обязано находить и неназначенные задачи,
#: иначе «все, кроме Алисы» тихо теряло бы половину выдачи.
NEGATIVE_OPERATORS = frozenset({Operator.NE, Operator.NOT_IN, Operator.NOT_CONTAINS})

#: Операторы порядка: применимы только там, где у значений есть порядок.
ORDER_OPERATORS = frozenset({Operator.GT, Operator.GTE, Operator.LT, Operator.LTE})

#: Точное совпадение и его отрицание — минимум, который умеет любое поле отбора.
EXACT_OPERATORS = frozenset({Operator.EQ, Operator.NE, Operator.IN, Operator.NOT_IN})

#: Точное совпадение плюс вхождение подстроки: у полей со свободным текстом.
TEXT_OPERATORS = EXACT_OPERATORS | {Operator.CONTAINS, Operator.NOT_CONTAINS}

#: Точное совпадение плюс сравнение по порядку: у приоритета и счётчиков.
ORDERED_OPERATORS = EXACT_OPERATORS | ORDER_OPERATORS

#: Сравнение мгновений: порядок плюс равенство. `in` и `not in` не предлагаются
#: намеренно — «быть одним из двух мгновений» не значит ничего, а список дат сам по
#: себе не диапазон. Диапазон пишется двумя условиями через `and`, как у счётчиков.
#: Равенство оставлено не ради сравнения с точным мгновением, а потому что `empty()`
#: разбирается как значение при нём.
TIME_OPERATORS = frozenset({Operator.EQ, Operator.NE}) | ORDER_OPERATORS

#: Операторы, которым нужно ровно одно значение: «больше двух сразу» не значит ничего.
SINGLE_VALUE_OPERATORS = ORDER_OPERATORS

#: Множественные операторы: получаются из `=` и `!=`, когда значений больше одного.
_PLURAL = {Operator.EQ: Operator.IN, Operator.NE: Operator.NOT_IN}


def plural_operator(operator: Operator, count: int) -> Operator:
    """`=` со списком значений — это `in`. Приведение одно на язык и на структурный фильтр."""
    if count > 1 and operator in _PLURAL:
        return _PLURAL[operator]
    return operator


class Junction(StrEnum):
    """Логическая связка группы условий."""

    AND = "and"
    OR = "or"


# --- Разобранный фильтр -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Literal:
    """Значение, написанное как есть: `TRK`, `open`, `0`, `"выдача ключей"`.

    `quoted` сохраняется потому, что кавычки — единственный способ написать значение со
    словом языка внутри (`"and"`), с пробелом или похожее на вызов функции (`"empty()"`).
    """

    text: str
    position: int = 0
    quoted: bool = False


@dataclass(frozen=True, slots=True)
class EmptyValue:
    """`empty()` — не значение, а признак его отсутствия.

    Отдельный тип, а не строка `"empty()"`: иначе тег с таким именем стал бы
    ненаходимым, а компилятор искал бы маркер перебором по значениям.
    """

    position: int = 0


SearchValue = Literal | EmptyValue


def is_empty_marker(value: SearchValue) -> bool:
    return isinstance(value, EmptyValue)


@dataclass(frozen=True, slots=True)
class Condition:
    """Одно условие: имя поля, оператор и значения.

    `name` хранится ровно так, как его написал клиент (`Status`, `deadline`): по нему
    строится сообщение об ошибке, и подставлять туда канонический вид значило бы
    показать агенту не тот текст, который он прислал.
    """

    name: str
    operator: Operator
    values: tuple[SearchValue, ...]
    position: int = 0


@dataclass(frozen=True, slots=True)
class Group:
    """Группа условий под одной связкой.

    Вложенность ограничена `MAX_GROUP_DEPTH`: язык не поддерживает произвольную
    структуру, и запрос на двадцать уровней скобок — это либо опечатка, либо попытка
    написать на нём SQL.
    """

    junction: Junction
    nodes: tuple[Node, ...]


Node = Condition | Group


@dataclass(frozen=True, slots=True)
class SortTerm:
    """Ключ сортировки в том виде, в каком его назвал клиент."""

    name: str
    descending: bool = False


@dataclass(frozen=True, slots=True)
class SearchFilter:
    """Разобранный фильтр: условия и порядок, имена и значения — ещё строки.

    `root is None` означает «условий нет» — законный фильтр, отбирающий все задачи.
    """

    root: Group | None = None
    sort: tuple[SortTerm, ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.root is None


def combine(filters: Sequence[SearchFilter]) -> SearchFilter:
    """Склеивает фильтры по `and`, сохраняя порядок первого непустого.

    Нужна там, где источников больше одного: строка запроса и структурные параметры
    приходят одним запросом, и складывать их «где-нибудь по дороге» значило бы получить
    два разных правила склейки в двух местах.
    """
    nodes: list[Node] = []
    sort: tuple[SortTerm, ...] = ()
    for item in filters:
        if item.root is not None:
            nodes.append(item.root)
        if not sort and item.sort:
            sort = item.sort
    if not nodes:
        return SearchFilter(sort=sort)
    if len(nodes) == 1:
        root = nodes[0]
        return SearchFilter(
            root=root if isinstance(root, Group) else Group(Junction.AND, (root,)),
            sort=sort,
        )
    return SearchFilter(root=Group(Junction.AND, tuple(nodes)), sort=sort)


def count_conditions(node: Node | None) -> int:
    """Сколько условий в дереве. Считается до компиляции, чтобы отказ был внятным."""
    if node is None:
        return 0
    if isinstance(node, Condition):
        return 1
    return sum(count_conditions(child) for child in node.nodes)


def depth_of(node: Node | None) -> int:
    """Глубина вложенности групп: у одиночного условия — ноль."""
    if node is None or isinstance(node, Condition):
        return 0
    return 1 + max((depth_of(child) for child in node.nodes), default=0)


# --- Поля отбора --------------------------------------------------------------------


class SearchField(StrEnum):
    """Поле, по которому можно отбирать задачи (`CONCEPT.md`, 4.4).

    Набор закрыт: новое поле отбора — правка концепции, а не запроса. Имена после
    `priority` — не колонки: они считаются из связей и дела прямо в запросе. Пять из них
    вычисляемые признаки карточки (`CONCEPT.md`, 4.3), а `remarks_in_work` — только поле
    отбора: оно смотрит на статус **чужой** задачи и признаком не стало намеренно
    (`CONCEPT.md`, 4.4).

    `KEY` — ключ самой задачи: им сессия, ведущая несколько дел, спрашивает про них
    разом. Значение у него того же вида, что у `PARENT`, и разрешается тем же путём;
    различает их компилятор.
    """

    KEY = "key"
    PROJECT = "project"
    PARENT = "parent"
    STATUS = "status"
    ASSIGNEE = "assignee"
    PRIORITY = "priority"
    BLOCKED = "blocked"
    OPEN_QUESTIONS = "open_questions"
    OPEN_BLOCKING_QUESTIONS = "open_blocking_questions"
    OPEN_REMARKS = "open_remarks"
    REMARKS_IN_WORK = "remarks_in_work"
    LAST_ENTRY_AT = "last_entry_at"
    TEXT = "text"


class SearchValueKind(StrEnum):
    """Что означает значение поля: от этого зависят и проверка, и SQL."""

    PROJECT_KEY = "project_key"
    TASK_KEY = "task_key"
    STATUS = "status"
    ASSIGNEE = "assignee"
    PRIORITY = "priority"
    FLAG = "flag"
    COUNT = "count"
    TIMESTAMP = "timestamp"
    FULLTEXT = "fulltext"


@dataclass(frozen=True, slots=True)
class SearchFieldSpec:
    """Описание поля отбора глазами поиска.

    `is_nullable` — есть ли у поля состояние «значения нет»: только у таких полей
    принимается `empty()`. У остальных маркер отвергается ошибкой, а не игнорируется
    молча: `project: empty()` — это непонимание модели, а не пустая выдача.
    """

    field: SearchField
    kind: SearchValueKind
    operators: frozenset[Operator]
    is_nullable: bool = False


SEARCH_FIELDS: dict[SearchField, SearchFieldSpec] = {
    spec.field: spec
    for spec in (
        # Ключ самой задачи. Пустого состояния у него нет: ключ есть у каждой задачи, и
        # `key: empty()` — непонимание модели, а не пустая выдача. Сравнения по порядку
        # тоже нет: `TRK-10 > TRK-2` означало бы порядок, а не отбор, и для порядка есть
        # `sort`. Несуществующий ключ отвечает отказом ровно по тому же доводу, что у
        # родителя: пустая выдача на вопрос «что с этими задачами» читается как ответ.
        SearchFieldSpec(SearchField.KEY, SearchValueKind.TASK_KEY, EXACT_OPERATORS),
        SearchFieldSpec(SearchField.PROJECT, SearchValueKind.PROJECT_KEY, EXACT_OPERATORS),
        # Родство прямое и на одно колено: `parent: UI-10` — дети UI-10, а не всё
        # поддерево. Рекурсия по внукам потребовала бы обхода графа на каждую строку
        # выдачи, а вопрос, ради которого поле заведено, — «можно ли закрывать
        # программу» — про прямых детей (`CONCEPT.md`, 3.5). Пустое состояние здесь
        # есть и означает верхний уровень проекта: задачи, у которых родителя нет.
        SearchFieldSpec(
            SearchField.PARENT, SearchValueKind.TASK_KEY, EXACT_OPERATORS, is_nullable=True
        ),
        SearchFieldSpec(SearchField.STATUS, SearchValueKind.STATUS, EXACT_OPERATORS),
        # Исполнитель — свободная строка, а не ссылка на участника (`CONCEPT.md`, 3.3),
        # поэтому вхождение подстроки здесь осмысленно: `assignee: ~ bot` находит и
        # `release_bot`, и `bot_nightly`, каких бы меток ни навыдумывали агенты.
        SearchFieldSpec(
            SearchField.ASSIGNEE, SearchValueKind.ASSIGNEE, TEXT_OPERATORS, is_nullable=True
        ),
        # Приоритет упорядочен: члены `TaskPriority` идут от низшего к высшему, и
        # `priority: >= high` опирается именно на этот порядок, а не на алфавит.
        SearchFieldSpec(SearchField.PRIORITY, SearchValueKind.PRIORITY, ORDERED_OPERATORS),
        SearchFieldSpec(SearchField.BLOCKED, SearchValueKind.FLAG, EXACT_OPERATORS),
        SearchFieldSpec(SearchField.OPEN_QUESTIONS, SearchValueKind.COUNT, ORDERED_OPERATORS),
        SearchFieldSpec(
            SearchField.OPEN_BLOCKING_QUESTIONS, SearchValueKind.COUNT, ORDERED_OPERATORS
        ),
        SearchFieldSpec(SearchField.OPEN_REMARKS, SearchValueKind.COUNT, ORDERED_OPERATORS),
        # «Разобрано, но работа не закрыта»: замечания с резолюцией `accepted`, чья
        # задача-продолжение ещё не в `done` и не в `cancelled`. Единственное условие
        # отбора, зависящее от статуса другой задачи.
        SearchFieldSpec(SearchField.REMARKS_IN_WORK, SearchValueKind.COUNT, ORDERED_OPERATORS),
        # Время последней записи агента или человека. Пустое состояние настоящее и
        # осмысленное: у свежей задачи в деле только служебная `created`, и `empty()`
        # находит именно те задачи, в которые агент ещё ничего не писал.
        SearchFieldSpec(
            SearchField.LAST_ENTRY_AT,
            SearchValueKind.TIMESTAMP,
            TIME_OPERATORS,
            is_nullable=True,
        ),
        # Псевдополе: подстрока в названии **и** описании разом. Равенство здесь
        # означает то же, что вхождение: точное совпадение со всем текстом задачи
        # смысла не имеет, а отдельный оператор ради этого был бы лишним.
        SearchFieldSpec(SearchField.TEXT, SearchValueKind.FULLTEXT, TEXT_OPERATORS),
    )
}


def search_field_spec(name: str) -> SearchFieldSpec | None:
    """Поле отбора по имени из запроса. `None` — такого поля нет."""
    try:
        field = SearchField(name.strip().lower())
    except ValueError:
        return None
    return SEARCH_FIELDS[field]


def searchable_names() -> list[str]:
    """Допустимые имена полей отбора — то, что уезжает в `details.allowed` при отказе."""
    return sorted(field.value for field in SEARCH_FIELDS)


# --- Порядок ------------------------------------------------------------------------


class SortKey(StrEnum):
    """Ключ сортировки (`CONCEPT.md`, 4.4). Набор закрыт, направление задаётся явно.

    `KEY` — не строковое сравнение ключа: `TRK-10` обязан идти после `TRK-2`, а по
    алфавиту он идёт раньше. Как именно это выражается в SQL, решает компилятор.
    """

    KEY = "key"
    UPDATED_AT = "updated_at"
    PRIORITY = "priority"
    #: «Сначала где шевелилось» — `-last_entry_at`. Пустые значения кладутся
    #: последними в обоих направлениях общим правилом порядка, а не исключением.
    LAST_ENTRY_AT = "last_entry_at"


#: Порядок по умолчанию: по ключу задачи, по возрастанию. Естественный порядок списка
#: задач — тот, в котором их заводили, — и он же устойчив: ключ уникален и не
#: переиспользуется, поэтому страница не поедет от правки чужой задачи.
DEFAULT_SORT_KEY = SortKey.KEY


def sortable_names() -> list[str]:
    """Допустимые ключи сортировки — то, что уезжает в `details.allowed` при отказе."""
    return sorted(key.value for key in SortKey)


def split_names(values: Sequence[str]) -> list[str]:
    """`["title,status"]` и `["title", "status"]` — одно и то же.

    Список имён приезжает и повтором параметра (`?fields=title&fields=status`), и
    перечислением через запятую (`?fields=title,status`): первое пишет клиент,
    сгенерированный по схеме, второе — человек и агент, набирающие адрес руками.
    Признавать только одну форму значило бы отвечать «поля `title,status` нет» на
    запись, которая выглядит совершенно законной.
    """
    return [part.strip() for value in values for part in value.split(",") if part.strip()]


# --- Выбор полей ответа -------------------------------------------------------------

#: Вычисляемые признаки в строке списка (`CONCEPT.md`, 4.3): выбираются целиком, одним
#: именем. Признак поодиночке (`fields=blocked`) не выбирается намеренно — тогда `blocked`
#: означал бы в `fields` одно, а в отборе другое, и клиенту пришлось бы помнить, где
#: имя — поле выдачи, а где условие.
FEATURES_FIELD = "features"

#: Родитель задачи в строке списка (`CONCEPT.md`, 4.4): ключ и название или `null`.
#: Имя то же, что у условия отбора `parent`, и значит оно то же самое: родитель у задачи
#: один (TRK-135), и `parent: TRK-7` отбирает строки, у которых в поле `parent` стоит
#: TRK-7. До TRK-135 поле звалось `parents` и было списком (TRK-95).
PARENT_FIELD = "parent"

#: Поля, которые можно попросить в выдаче: поля карточки задачи плюс `features` и
#: `parent`. Два разных представления одной задачи в одном API — то, чего проект не
#: допускает, поэтому список строки совпадает с карточкой, признаки приходят тем же
#: вложенным объектом, что и в пакете преемника (`CONCEPT.md`, 4.2), а родитель — это
#: поле `parent` того же пакета, сжатое до ключа и названия.
SELECTABLE_FIELDS: tuple[str, ...] = (
    "id",
    "key",
    "project",
    "title",
    "description",
    "goal",
    "context",
    "constraints",
    "output",
    "checks",
    "status",
    "assignee",
    "priority",
    "version",
    "created_by",
    "created_at",
    "updated_at",
    FEATURES_FIELD,
    PARENT_FIELD,
)

#: Ключ задачи возвращается всегда: выдача без него бесполезна — по ней нельзя ни
#: прочитать задачу, ни сослаться на неё.
MANDATORY_FIELD = "key"


def selectable_names() -> list[str]:
    """Что принимает `fields` — то же, что уезжает в `details.allowed` при отказе.

    Одна функция на описание параметра и на отказ намеренно: агент, прочитавший отказ,
    обязан узнать в нём тот же перечень, что видел в контракте инструмента, — иначе он
    решит, что домен зависит от вызова. Порядок поэтому тоже один, алфавитный.
    """
    return sorted(SELECTABLE_FIELDS)


def field_requested(name: str, fields: Sequence[str]) -> bool:
    """Просили ли это поле в выдаче. Пустой набор означает «все поля», а не «ни одного».

    Нужна тем, для кого поле стоит денег: признаки в строке считаются подзапросами, и
    считать их для запроса, который просил один столбец ключей, — работа в никуда.
    Сериализаторы фильтруют готовый словарь тем же правилом; здесь оно названо функцией,
    потому что решение принимается **до** выборки, за пределами сериализатора.
    """
    return not fields or name in fields


# --- Разрешённый фильтр -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchTerm:
    """Условие с уже разрешёнными значениями.

    `values` держит то, что пойдёт в запрос: `uuid` проекта, член перечисления, число,
    строку. `include_empty` вынесен из значений отдельно: `empty()` — это не значение, а
    отсутствие значения, и хранить его вперемешку с идентификаторами значило бы искать
    его перебором в компиляторе.
    """

    name: str
    field: SearchField
    kind: SearchValueKind
    operator: Operator
    values: tuple[Any, ...] = ()
    include_empty: bool = False


@dataclass(frozen=True, slots=True)
class TermGroup:
    """Группа разрешённых условий под связкой."""

    junction: Junction
    nodes: tuple[Term, ...]


Term = SearchTerm | TermGroup


@dataclass(frozen=True, slots=True)
class ResolvedSort:
    """Ключ сортировки после разрешения имени."""

    key: SortKey
    descending: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedFilter:
    """Фильтр, готовый к компиляции в SQL.

    Сортировка обязана заканчиваться уникальным тайбрейкером, и его добавляет
    компилятор, а не этот объект: `id` — свойство таблицы, а не фильтра. Без
    тайбрейкера страницы теряли бы и дублировали задачи, у которых совпало значение
    ключа сортировки.
    """

    root: TermGroup | None = None
    sort: tuple[ResolvedSort, ...] = ()
    fields: tuple[str, ...] = ()


def iter_terms(node: Term | None) -> Iterable[SearchTerm]:
    """Обход дерева условий: нужен проверкам, которым важен набор, а не структура."""
    if node is None:
        return
    if isinstance(node, TermGroup):
        for child in node.nodes:
            yield from iter_terms(child)
    else:
        yield node


# --- Архивный проект в выдаче ---------------------------------------------------------

#: Операторы, которыми условие **называет** значение: равенство и вхождение в набор.
#: Отрицание не называет ничего — `project: != OPS` не просит показать архивный TRK.
NAMING_OPERATORS = frozenset({Operator.EQ, Operator.IN})


@dataclass(frozen=True, slots=True)
class NamedInFilter:
    """Что отбор называет явно: проекты, ключи задач и родителей — идентификаторами.

    Задачи архивного проекта в выдачу не попадают, пока отбор не назовёт их явно:
    условием `project:` с этим проектом, ключом самой задачи (`key:`) или, для детей,
    ключом родителя (`parent:`) (`CONCEPT.md`, 3.2 и 4.4; `TRK-164#9`, `TRK-151#17`).
    Поля в языке запросов для этого нет намеренно: архив показывается названием, а не
    отдельным флагом.

    Названное собирается по всему дереву, в какой бы ветке `or` оно ни стояло: условие
    видимости добавляется к отбору через `and` и пропускает только названное, поэтому
    `key: TRK-1 or status: open` покажет архивную TRK-1, но не остальные открытые задачи
    её проекта.
    """

    projects: frozenset[Any] = frozenset()
    tasks: frozenset[Any] = frozenset()
    parents: frozenset[Any] = frozenset()


def named_in_filter(root: Term | None) -> NamedInFilter:
    """Проекты, задачи и родители, названные условиями равенства или вхождения."""
    found: dict[SearchField, set[Any]] = {
        SearchField.PROJECT: set(),
        SearchField.KEY: set(),
        SearchField.PARENT: set(),
    }
    for term in iter_terms(root):
        if term.field in found and term.operator in NAMING_OPERATORS:
            found[term.field].update(term.values)
    return NamedInFilter(
        projects=frozenset(found[SearchField.PROJECT]),
        tasks=frozenset(found[SearchField.KEY]),
        parents=frozenset(found[SearchField.PARENT]),
    )
