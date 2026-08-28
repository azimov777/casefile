"""Внутреннее представление фильтра задач: во что сходятся язык запросов и структурный фильтр.

Чистый Python: ни ORM, ни HTTP. Здесь описано, **что** ищем; как это превращается в SQL —
в `app/db/repositories/search.py`, а разрешение имён и значений против реестра полей и
справочников — в `app/services/search.py`.

## Почему представление одно

Строка `queue: TRK and status: open` и структурный фильтр `{"queue": ["TRK"], "status":
["open"]}` обязаны давать **идентичный** результат. Единственный способ этого добиться —
свести оба входа к одному объекту до того, как начнётся построение запроса. Две
независимые реализации разошлись бы поведением на первом же краевом случае, и агент с
фронтендом получили бы разные ответы на одинаковый по смыслу вопрос.

## Две стадии, и это не усложнение

1. **Разобранный фильтр** (`SearchFilter`): имена полей и значения — ещё строки, ровно
   такие, какими их написал клиент. Домен не знает ни реестра полей, ни справочников,
   ни того, кто задал вопрос, поэтому проверить их здесь нечем.
2. **Разрешённый фильтр** (`ResolvedFilter`): имя стало системным полем или ссылкой на
   кастомное, значение — идентификатором записи, моментом времени, числом.

Между стадиями стоит `app/services/search.py` — единственное место, которое видит базу.
Разделение нужно затем, чтобы разбор языка проверялся без базы, а разрешение имён было
одной функцией и для языка, и для структурного фильтра.

## Порядок разрешения имени фиксирован

Имя из запроса сначала сверяется с системными полями (`SYSTEM_FIELD_KEYS` из
`app/domain/fields.py`) и разрешается в колонку, и только потом ищется в реестре полей.
Порядок явный, а не «как получится»: реестр уже не даёт завести кастомное поле с ключом
системного, но без явной последовательности `status` однажды начал бы искаться в JSONB.

Имя, которое зарезервировано системой, но искать по нему пока нечем (`links`,
`comments`), отвергается ошибкой, а не проваливается в реестр: молчаливый уход в JSONB
дал бы пустую выдачу вместо внятного «этого фильтра ещё нет». Набор таких имён
вычисляется вычитанием, поэтому появившийся фильтр уходит из него сам — так `project`
перестал быть недоступным в задаче 10, а `sprint` в задаче 11, и достаточно было одного
описания в `SEARCHABLE_SYSTEM_FIELDS`.

## Даты сравниваются по календарному дню

Значение без времени (`2026-08-28`, `today()`) сравнивается с моментом времени как
**интервал суток**, а не как полночь. Иначе `deadline: <= today()` означало бы «раньше,
чем сегодня началось» и молча теряло бы всё, что просрочено сегодня. Значение с временем
(`now()`, `"2026-08-28T10:00:00+00:00"`) сравнивается точно.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from app.domain.fields import SYSTEM_FIELD_KEYS, FieldValueType

#: Потолки языка и фильтра. Ограничения неочевидные, поэтому названы прямо: фильтр
#: приезжает из строки запроса, из тела и из сохранённого фильтра, и запрос на тысячу
#: условий превратился бы в план, который PostgreSQL строит дольше, чем выполняет.
MAX_CONDITIONS = 50
MAX_GROUP_DEPTH = 5
MAX_VALUES_PER_CONDITION = 100
MAX_SORT_TERMS = 5
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


class SearchFunction(StrEnum):
    """Функции языка. Набор закрыт: своих функций клиент не заводит.

    `ME` подставляет ключ актора, задавшего вопрос, — благодаря ей один сохранённый фильтр
    «мои задачи» работает у всех. `TODAY` и `NOW` дают точку отсчёта на стороне сервера:
    время клиента может отличаться, и «просроченные» у него получились бы другими.
    `EMPTY` — не значение, а признак отсутствия значения.
    """

    ME = "me"
    TODAY = "today"
    NOW = "now"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class Literal:
    """Значение, написанное как есть: `TRK`, `open`, `2026-08-28`, `"выдача ключей"`.

    `quoted` сохраняется потому, что кавычки — единственный способ написать значение со
    словом языка внутри (`"and"`) или с пробелом.
    """

    text: str
    position: int = 0
    quoted: bool = False


@dataclass(frozen=True, slots=True)
class FunctionValue:
    """Вызов функции, возможно со сдвигом: `me()`, `today()`, `today() - 7d`.

    Сдвиг хранится в секундах, а не строкой: складывать его с моментом времени будет
    сценарий, и разбирать `7d` второй раз ему незачем.
    """

    function: SearchFunction
    offset_seconds: int = 0
    position: int = 0


SearchValue = Literal | FunctionValue


@dataclass(frozen=True, slots=True)
class Condition:
    """Одно условие: имя поля, оператор и значения.

    `name` хранится ровно так, как его написал клиент (`TRK.severity`, `Status`): по нему
    строится сообщение об ошибке, и подставлять туда канонический вид значило бы показать
    агенту не тот текст, который он прислал.
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

    Нужна там, где источников больше одного: строка запроса, структурный фильтр и
    сохранённый фильтр приходят одним запросом, и складывать их «где-нибудь по дороге»
    значило бы получить три разных правила склейки в трёх местах.
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


# --- Системные поля ---------------------------------------------------------------


class SystemField(StrEnum):
    """Системное поле задачи, по которому можно искать.

    Значения совпадают с ключами из `SYSTEM_FIELD_KEYS`, поэтому кастомное поле с таким
    именем завести нельзя и имя в запросе однозначно. Совпадение стережёт тест.
    """

    KEY = "key"
    QUEUE = "queue"
    ISSUE_TYPE = "issue_type"
    STATUS = "status"
    STATUS_CATEGORY = "status_category"
    RESOLUTION = "resolution"
    PRIORITY = "priority"
    SUMMARY = "summary"
    DESCRIPTION = "description"
    TEXT = "text"
    AUTHOR = "author"
    ASSIGNEE = "assignee"
    FOLLOWERS = "followers"
    DEADLINE = "deadline"
    TAGS = "tags"
    PROJECT = "project"
    SPRINT = "sprint"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SprintScope(StrEnum):
    """Значение фильтра по спринту, которое разрешается не в один спринт.

    `current` означает «любой активный спринт». Подставить здесь один идентификатор
    нельзя: активный спринт свой у каждой доски, а фильтр про доски не знает. Компилятор
    превращает маркер в подзапрос — ровно так же, как категорию статуса.
    """

    CURRENT = "current"


class SearchValueKind(StrEnum):
    """Что означает значение системного поля: от этого зависят и проверка, и SQL."""

    ISSUE_KEY = "issue_key"
    QUEUE_KEY = "queue_key"
    PROJECT_KEY = "project_key"
    SPRINT_REF = "sprint_ref"
    CATALOG_REF = "catalog_ref"
    STATUS_CATEGORY = "status_category"
    ACTOR_KEY = "actor_key"
    PRIORITY = "priority"
    LINE = "line"
    FULLTEXT = "fulltext"
    TAG = "tag"
    MOMENT = "moment"


_TEXT_OPERATORS = frozenset(
    {
        Operator.EQ,
        Operator.NE,
        Operator.IN,
        Operator.NOT_IN,
        Operator.CONTAINS,
        Operator.NOT_CONTAINS,
    }
)
_EXACT_OPERATORS = frozenset({Operator.EQ, Operator.NE, Operator.IN, Operator.NOT_IN})
_ORDERED_OPERATORS = _EXACT_OPERATORS | ORDER_OPERATORS


@dataclass(frozen=True, slots=True)
class SystemFieldSpec:
    """Описание системного поля глазами поиска.

    `catalog_kind` заполнен только у ссылок на справочник: сценарию нужно знать, какой
    именно справочник разрешать, а держать это знание в самом сценарии значило бы
    завести второй список системных полей.
    """

    field: SystemField
    kind: SearchValueKind
    operators: frozenset[Operator]
    is_nullable: bool = False
    is_sortable: bool = False
    catalog_kind: str | None = None


SEARCHABLE_SYSTEM_FIELDS: dict[SystemField, SystemFieldSpec] = {
    spec.field: spec
    for spec in (
        SystemFieldSpec(SystemField.KEY, SearchValueKind.ISSUE_KEY, _TEXT_OPERATORS),
        SystemFieldSpec(SystemField.QUEUE, SearchValueKind.QUEUE_KEY, _EXACT_OPERATORS),
        SystemFieldSpec(
            SystemField.ISSUE_TYPE,
            SearchValueKind.CATALOG_REF,
            _EXACT_OPERATORS,
            catalog_kind="issue_type",
        ),
        SystemFieldSpec(
            SystemField.STATUS,
            SearchValueKind.CATALOG_REF,
            _EXACT_OPERATORS,
            catalog_kind="status",
        ),
        SystemFieldSpec(
            SystemField.STATUS_CATEGORY, SearchValueKind.STATUS_CATEGORY, _EXACT_OPERATORS
        ),
        SystemFieldSpec(
            SystemField.RESOLUTION,
            SearchValueKind.CATALOG_REF,
            _EXACT_OPERATORS,
            is_nullable=True,
            catalog_kind="resolution",
        ),
        # Приоритет упорядочен: члены `IssuePriority` идут от низшего к высшему, и
        # `priority: >= major` опирается именно на этот порядок, а не на алфавит.
        SystemFieldSpec(
            SystemField.PRIORITY, SearchValueKind.PRIORITY, _ORDERED_OPERATORS, is_sortable=True
        ),
        SystemFieldSpec(
            SystemField.SUMMARY, SearchValueKind.LINE, _TEXT_OPERATORS, is_sortable=True
        ),
        SystemFieldSpec(
            SystemField.DESCRIPTION, SearchValueKind.LINE, _TEXT_OPERATORS, is_nullable=True
        ),
        # Псевдополе полнотекстового поиска: название, описание и лента обсуждения разом.
        # Равенство здесь означает то же, что вхождение: точное совпадение со всем
        # текстом задачи не имеет смысла, а отдельный оператор ради этого — лишний.
        SystemFieldSpec(SystemField.TEXT, SearchValueKind.FULLTEXT, _TEXT_OPERATORS),
        SystemFieldSpec(SystemField.AUTHOR, SearchValueKind.ACTOR_KEY, _EXACT_OPERATORS),
        SystemFieldSpec(
            SystemField.ASSIGNEE, SearchValueKind.ACTOR_KEY, _EXACT_OPERATORS, is_nullable=True
        ),
        SystemFieldSpec(
            SystemField.FOLLOWERS, SearchValueKind.ACTOR_KEY, _EXACT_OPERATORS, is_nullable=True
        ),
        SystemFieldSpec(
            SystemField.DEADLINE,
            SearchValueKind.MOMENT,
            _ORDERED_OPERATORS,
            is_nullable=True,
            is_sortable=True,
        ),
        SystemFieldSpec(SystemField.TAGS, SearchValueKind.TAG, _TEXT_OPERATORS, is_nullable=True),
        # Проект — надочередная ось: `project: alpha and queue: != TRK` находит задачи
        # проекта во всех очередях, кроме одной. Значение — ключ проекта, а не ссылка с
        # областью действия: у проекта области нет, он не принадлежит очереди.
        # `is_nullable`, потому что задача вне проекта — обычное состояние, и
        # `project: empty()` обязано находить именно её.
        SystemFieldSpec(
            SystemField.PROJECT,
            SearchValueKind.PROJECT_KEY,
            _EXACT_OPERATORS,
            is_nullable=True,
        ),
        # Спринт — ось планирования доски. Значение — идентификатор спринта либо слово
        # `current`: «задачи текущего спринта» — самый частый вопрос доски, а какой
        # именно спринт текущий, знает сервер, и заставлять клиента сначала его искать
        # значило бы два запроса вместо одного. `is_nullable`, потому что задача вне
        # спринта — обычное состояние, и `sprint: empty()` — это и есть бэклог.
        SystemFieldSpec(
            SystemField.SPRINT,
            SearchValueKind.SPRINT_REF,
            _EXACT_OPERATORS,
            is_nullable=True,
        ),
        SystemFieldSpec(
            SystemField.CREATED_AT, SearchValueKind.MOMENT, _ORDERED_OPERATORS, is_sortable=True
        ),
        SystemFieldSpec(
            SystemField.UPDATED_AT, SearchValueKind.MOMENT, _ORDERED_OPERATORS, is_sortable=True
        ),
    )
}

#: Синонимы имён. Пополнять его можно только именами, которые уже лежат в
#: `SYSTEM_FIELD_KEYS`: незарезервированный синоним однажды перекрыл бы одноимённое
#: кастомное поле, и то стало бы недостижимым для поиска — молча.
SYSTEM_FIELD_ALIASES: dict[str, SystemField] = {"type": SystemField.ISSUE_TYPE}

#: Зарезервированные имена, по которым искать пока нечем. Набор вычисляется вычитанием,
#: поэтому имя уходит из него ровно тогда, когда у него появляется описание фильтра:
#: `project` ушёл в задаче 10, `sprint` — в задаче 11. Остались `links`, `comments`,
#: `checklist`, `values` и `version`. До тех пор запрос по такому имени обязан отвечать
#: «ещё нет», а не уходить в JSONB за пустым результатом.
NOT_SEARCHABLE_SYSTEM_FIELDS: frozenset[str] = frozenset(
    SYSTEM_FIELD_KEYS
    - {field.value for field in SEARCHABLE_SYSTEM_FIELDS}
    - set(SYSTEM_FIELD_ALIASES)
)

#: Поля, которые можно попросить в выдаче. Совпадают с полями ответа задачи; `values`
#: означает весь набор кастомных полей, а ссылка на конкретное поле — только его.
SELECTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "key",
        "queue",
        "issue_type",
        "status",
        "resolution",
        "priority",
        "summary",
        "description",
        "author",
        "assignee",
        "followers",
        "deadline",
        "tags",
        "project",
        "sprint",
        "values",
        "version",
        "created_at",
        "updated_at",
    }
)

#: Ключ задачи возвращается всегда: выдача без него бесполезна — по ней нельзя ни
#: прочитать задачу, ни сослаться на неё.
MANDATORY_FIELD = "key"


def system_field_spec(name: str) -> SystemFieldSpec | None:
    """Системное поле по имени из запроса. `None` — имя не системное, искать в реестре.

    Имя с префиксом очереди (`TRK.severity`) системным быть не может: у системных полей
    области действия нет, они колонки одной таблицы.
    """
    if "." in name:
        return None
    key = name.strip().lower()
    alias = SYSTEM_FIELD_ALIASES.get(key)
    if alias is not None:
        return SEARCHABLE_SYSTEM_FIELDS[alias]
    try:
        field = SystemField(key)
    except ValueError:
        return None
    return SEARCHABLE_SYSTEM_FIELDS.get(field)


def is_reserved_name(name: str) -> bool:
    """Имя занято системой, но искать по нему нечем: `links`, `comments`, `values`."""
    return "." not in name and name.strip().lower() in NOT_SEARCHABLE_SYSTEM_FIELDS


# --- Разрешённый фильтр ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SystemTerm:
    """Условие по системному полю с уже разрешёнными значениями.

    `values` держит то, что пойдёт в запрос: `uuid` записи справочника или актора,
    момент времени, `date` для сравнения по календарному дню, строку для текста.
    `include_empty` вынесен из значений отдельно: `empty()` — это не значение, а
    отсутствие значения, и хранить его вперемешку с идентификаторами значило бы искать
    его перебором в компиляторе.
    """

    name: str
    field: SystemField
    kind: SearchValueKind
    operator: Operator
    values: tuple[Any, ...] = ()
    include_empty: bool = False


@dataclass(frozen=True, slots=True)
class CustomTerm:
    """Условие по кастомному полю: ссылка, тип значения и множественность.

    Тип нужен компилятору, чтобы выбрать форму сравнения в JSONB: число сравнивается
    приведением, дата — лексикографически (формат хранения подобран так, что
    лексикографический порядок совпадает с хронологическим), остальное — как текст.
    """

    name: str
    ref: str
    value_type: FieldValueType
    is_multiple: bool
    operator: Operator
    values: tuple[Any, ...] = ()
    include_empty: bool = False


@dataclass(frozen=True, slots=True)
class TermGroup:
    """Группа разрешённых условий под связкой."""

    junction: Junction
    nodes: tuple[Term, ...]


Term = SystemTerm | CustomTerm | TermGroup


@dataclass(frozen=True, slots=True)
class ResolvedSort:
    """Ключ сортировки после разрешения имени.

    Либо системное поле, либо ссылка на кастомное с его типом — третьего не бывает, и
    оба поля сразу пустыми не остаются.
    """

    descending: bool = False
    field: SystemField | None = None
    ref: str | None = None
    value_type: FieldValueType | None = None


@dataclass(frozen=True, slots=True)
class ResolvedFilter:
    """Фильтр, готовый к компиляции в SQL.

    Сортировка обязана содержать уникальный тайбрейкер, и его добавляет компилятор, а не
    этот объект: `id` — свойство таблицы, а не фильтра. Без тайбрейкера страницы теряли
    бы и дублировали задачи, у которых совпало значение ключа сортировки.
    """

    root: TermGroup | None = None
    sort: tuple[ResolvedSort, ...] = ()
    fields: tuple[str, ...] = ()
    value_refs: tuple[str, ...] = ()


def moment_is_day(value: Any) -> bool:
    """Значение задаёт календарный день, а не момент: сравнение идёт интервалом суток."""
    return isinstance(value, date) and not isinstance(value, datetime)


def iter_terms(node: Term | None) -> Iterable[SystemTerm | CustomTerm]:
    """Обход дерева условий: нужен проверкам, которым важен набор, а не структура."""
    if node is None:
        return
    if isinstance(node, TermGroup):
        for child in node.nodes:
            yield from iter_terms(child)
    else:
        yield node
