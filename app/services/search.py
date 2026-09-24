"""Отбор задач: разрешение имён и значений, склейка источников фильтра, выборка.

Единственное место, где внутреннее представление фильтра встречается с базой. Разбор
языка живёт в домене и проверяется без базы, компиляция в SQL — в
`app/db/repositories/search.py`; здесь между ними стоит шаг, которому нужны очереди и
перечисления.

## Два источника фильтра и один результат

Фильтр приходит строкой запроса и набором структурных параметров — в любом сочетании.
Оба превращаются в `SearchFilter` и склеиваются по `and`. Отсюда и главное свойство:
«структурный фильтр плюс ещё одно условие строкой» — это не особый режим, а обычная
склейка, и вести себя она обязана так же, как одна строка с тем же смыслом.

Одинаково у двух источников **значение**, а не разбор текста. Значение языка приходит
куском строки, и границы ему задаёт синтаксис: пробел кончает слово, кавычки продолжают.
Значению структурного параметра границы задал протокол, поэтому оно берётся целиком
(`parse_structured_value`), а из синтаксиса языка признаёт один маркер — `empty()`,
и признаёт его парсером языка. Отсюда `?assignee=empty()` и `assignee: empty()` — один
и тот же вопрос, а `?text=выдача ключей` — одно значение с пробелом, а не отказ разбора
(TRK-21).

Соблазн собрать структурный фильтр «напрямую в SQL, там же проще» — главный способ
сломать требование «одинаковые по смыслу фильтр и строка дают одинаковый результат»:
разойдутся сначала краевые случаи (пустое значение, отрицание, несколько значений), и
разойдутся молча.

## Что проверяется здесь, а что раньше

Форму запроса — скобки, операторы, позицию ошибки — проверил разбор. Сюда приезжает
дерево, в котором имена и значения ещё строки, и остаётся то, на что нужна база или
перечисление: существует ли такая очередь, бывает ли такой статус, число ли это.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.task import Task
from app.db.pagination import Page
from app.db.repositories.search import TaskSearchRepository
from app.domain.errors import (
    SearchFieldUnknownError,
    SearchOperatorNotSupportedError,
    SearchValueInvalidError,
)
from app.domain.query_language import parse_query, parse_sort_terms, parse_structured_value
from app.domain.search import (
    DEFAULT_SORT_KEY,
    MANDATORY_FIELD,
    MAX_CONDITIONS,
    MAX_GROUP_DEPTH,
    MAX_VALUES_PER_CONDITION,
    SELECTABLE_FIELDS,
    SINGLE_VALUE_OPERATORS,
    Condition,
    EmptyValue,
    Group,
    Junction,
    Literal,
    Node,
    Operator,
    ResolvedFilter,
    ResolvedSort,
    SearchFieldSpec,
    SearchFilter,
    SearchTerm,
    SearchValue,
    SearchValueKind,
    SortKey,
    SortTerm,
    Term,
    TermGroup,
    combine,
    count_conditions,
    depth_of,
    is_empty_marker,
    search_field_spec,
    searchable_names,
    selectable_names,
    sortable_names,
    split_names,
)
from app.domain.tasks import AskedParent, TaskFeatures, TaskPriority, TaskStatus
from app.domain.tokens import TokenScope
from app.services import queues as queues_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.permissions import ensure_scope


@dataclass(frozen=True, slots=True)
class StructuredTerm:
    """Одно условие структурного фильтра до разбора значений.

    Значения — то, что прислал клиент: строки языка (`empty()`), числа и логические
    значения. Приведение к внутреннему представлению одно на все случаи, поэтому и тип
    один: новый источник отбора (инструмент MCP, подресурс) собирает эти же условия и
    своего разбора не пишет.
    """

    name: str
    values: Sequence[Any] = ()
    operator: Operator = Operator.EQ


@dataclass(frozen=True, slots=True)
class FoundTask:
    """Строка выдачи: задача и её вычисляемые признаки (`CONCEPT.md`, 4.3).

    Признаки едут вместе со строкой, а не запрашиваются по одной задаче: назначатель
    отбирает кандидатов одним запросом и обязан видеть в ответе то же, по чему отбирал.
    Второй вызов на каждую строку означал бы и N+1, и окно, в котором признак успел
    измениться между двумя запросами.

    `features is None` означает «их не просили» (`fields` без `features`), а не «признаков
    нет»: у задачи они есть всегда, и `blocked=False` здесь соврал бы. Сериализатор в
    таком ответе поля `features` не показывает вовсе.

    С родителем то же правило: `parent is None` — «не просили», `AskedParent(None)` — «у
    задачи верхнего уровня родителя нет». Едут они той же строкой и по той же причине:
    доска, называющая программу каждой карточки, не может звать карточку родителя на
    каждую строку (`CONCEPT.md`, 4.4).
    """

    task: Task
    features: TaskFeatures | None = None
    parent: AskedParent | None = None


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Результат поиска: страница строк и то, чем её просили ограничить.

    Разрешённый фильтр возвращается вместе со страницей, потому что выбор возвращаемых
    полей — часть ответа: сериализатору нужно знать, что именно просили, и вычислять
    это второй раз в HTTP-слое значило бы завести второе толкование `fields`.
    """

    page: Page[FoundTask]
    resolved: ResolvedFilter


async def search_tasks(
    session: AsyncSession,
    *,
    actor: Actor,
    query: str | None = None,
    structured: Sequence[StructuredTerm] = (),
    sort: Sequence[str] = (),
    fields: Sequence[str] = (),
    limit: int | None = None,
    cursor: str | None = None,
    offset: int | None = None,
    with_total: bool = False,
) -> SearchOutcome:
    """Находит задачи по любому сочетанию источников фильтра.

    Источники складываются по `and`: пустой набор источников означает «все задачи», а
    не ошибку — иначе перечисление задач и поиск без условий пришлось бы звать
    по-разному.

    Страницу адресует либо `cursor`, либо `offset`, и это выбор вызывающего, а не
    умолчание: курсор обходит выдачу целиком и не теряет строк на вставках, смещение
    попадает на любую страницу и платит за это чтением пропускаемых строк и сдвигом
    границ при вставке между запросами. Вместе они — отказ `cursor_with_offset`.

    `with_total` добавляет к странице число задач по тому же отбору **вторым запросом**.
    Его просит тот, кто рисует «страница 3 из 7, всего 98», и не просит тот, кто читает
    выдачу подряд: без него `page.total is None` — «не считали», а не «ноль»
    (задача TRK-41).
    """
    resolved = await resolve_task_filter(
        session,
        actor=actor,
        query=query,
        structured=structured,
        sort=sort,
        fields=fields,
    )
    page = await TaskSearchRepository(session).search_page(
        resolved,
        limit=limit,
        cursor=cursor,
        offset=offset,
        with_total=with_total,
    )
    return SearchOutcome(
        page=Page(
            items=[
                FoundTask(task=task, features=features, parent=parent)
                for task, features, parent in page.items
            ],
            next_cursor=page.next_cursor,
            total=page.total,
        ),
        resolved=resolved,
    )


async def resolve_task_filter(
    session: AsyncSession,
    *,
    actor: Actor,
    query: str | None = None,
    structured: Sequence[StructuredTerm] = (),
    sort: Sequence[str] = (),
    fields: Sequence[str] = (),
) -> ResolvedFilter:
    """Склейка всех источников отбора в один разрешённый фильтр, без самой выборки.

    Отдельно от `search_tasks`, потому что отбор бывает нужен без страницы: инструмент
    MCP с приклеенным условием и любой будущий подресурс обязаны понимать язык так же,
    как поиск. Разрешение имён и значений при этом остаётся одним — иначе расхождение
    было бы молчаливым.
    """
    ensure_scope(actor, TokenScope.TASK, action="task.search")

    parts: list[SearchFilter] = []
    if query:
        parts.append(parse_query(query))
    if structured:
        parts.append(filter_from_structured(structured))

    merged = combine(parts)
    if sort:
        merged = replace(merged, sort=parse_sort_terms(sort))

    return await resolve_filter(session, merged, fields=fields)


def filter_from_structured(terms: Sequence[StructuredTerm]) -> SearchFilter:
    """Структурный фильтр → внутреннее представление.

    Условия складываются по `and`, значения одного условия — по `or` (`status=open&
    status=in_progress`). Это и есть смысл структурного фильтра: сузить по каждому
    параметру, но принять любое из перечисленных значений.

    Пустой список значений означает «не фильтровать по этому полю», а не «ничего не
    подходит»: иначе снятая в интерфейсе галочка обнуляла бы выдачу.

    Потолок значений в условии тот же, что в языке (`MAX_VALUES_PER_CONDITION`), и
    проверяется здесь по той же причине, по какой потолок ожидания проверяется в домене:
    структурный фильтр приезжает мимо разбора строки, и у REST его сторожит схема
    параметра, а у MCP — ничто. Отказ называет и потолок, и присланное число: молчаливое
    усечение списка ключей дало бы выдачу, в которой части спрошенных задач просто нет.
    """
    nodes: list[Node] = []
    for term in terms:
        if not term.values:
            continue
        if len(term.values) > MAX_VALUES_PER_CONDITION:
            raise SearchValueInvalidError(
                details={
                    "field": term.name,
                    "reason": "too_many_values",
                    "max": MAX_VALUES_PER_CONDITION,
                    "got": len(term.values),
                },
            )
        values = tuple(_structured_value(item) for item in term.values)
        operator = term.operator
        if operator in {Operator.EQ, Operator.NE}:
            # Несколько значений превращают равенство во вхождение — тем же правилом,
            # что и в языке: `status: open, in_progress` обязано значить одно и то же,
            # как бы его ни прислали. `empty()` в счёт не идёт: он не значение.
            payload = [value for value in values if not is_empty_marker(value)]
            if len(payload) > 1:
                operator = Operator.IN if operator is Operator.EQ else Operator.NOT_IN
        nodes.append(Condition(name=term.name, operator=operator, values=values))
    if not nodes:
        return SearchFilter()
    return SearchFilter(root=Group(Junction.AND, tuple(nodes)))


def _structured_value(value: Any) -> SearchValue:
    """Значение структурного фильтра.

    `None` — это `empty()`: у структурного параметра «значения нет» выражается именно
    так, и второй способ сказать то же самое проект не заводит. Логическое значение и
    число превращаются в литерал, а не разбираются как строка языка: `?blocked=false`
    приезжает уже типизированным, и гонять его через лексер незачем.

    Строка уходит в `parse_structured_value`, а не в разбор языка: границы значения у
    структурного параметра задал протокол, и `?text=выдача ключей` — одно значение
    с пробелом. Разбором языка это отвечало `invalid_search_query` (TRK-21).
    """
    if value is None:
        return EmptyValue()
    if isinstance(value, bool):
        return Literal(text="true" if value else "false")
    if isinstance(value, int | float):
        return Literal(text=str(value))
    if isinstance(value, str):
        return parse_structured_value(value)
    raise SearchValueInvalidError(
        details={"value": repr(value), "reason": "unsupported_value_type"},
    )


# --- Разрешение ----------------------------------------------------------------------


async def resolve_filter(
    session: AsyncSession,
    search_filter: SearchFilter,
    *,
    fields: Sequence[str] = (),
) -> ResolvedFilter:
    """Разобранный фильтр → готовый к компиляции: имена в поля, значения в значения.

    Потолки проверяются здесь, а не только при разборе строки: склейка двух источников
    может дать дерево, которого не было ни в одном из них.
    """
    total = count_conditions(search_filter.root)
    if total > MAX_CONDITIONS:
        raise SearchValueInvalidError(
            details={"reason": "too_many_conditions", "max": MAX_CONDITIONS, "got": total},
        )
    depth = depth_of(search_filter.root)
    if depth > MAX_GROUP_DEPTH:
        raise SearchValueInvalidError(
            details={"reason": "too_deep", "max": MAX_GROUP_DEPTH, "got": depth},
        )

    root = None if search_filter.root is None else await _resolve_node(session, search_filter.root)
    return ResolvedFilter(
        root=root,
        sort=_resolve_sort(search_filter.sort),
        fields=_resolve_fields(fields),
    )


async def _resolve_node(session: AsyncSession, node: Node) -> Term:
    if isinstance(node, Group):
        nodes = [await _resolve_node(session, child) for child in node.nodes]
        return TermGroup(junction=node.junction, nodes=tuple(nodes))
    return await _resolve_condition(session, node)


async def _resolve_condition(session: AsyncSession, condition: Condition) -> SearchTerm:
    spec = search_field_spec(condition.name)
    if spec is None:
        raise SearchFieldUnknownError(
            details={
                "field": condition.name,
                "position": condition.position,
                "reason": "unknown_field",
                "allowed": searchable_names(),
            },
        )
    _ensure_operator(condition, spec)
    values, include_empty = _split_empty(condition, spec)
    resolved = [await _resolve_value(session, condition, spec, value) for value in values]
    _ensure_single_for_order(condition, len(resolved))
    return SearchTerm(
        name=condition.name,
        field=spec.field,
        kind=spec.kind,
        operator=condition.operator,
        values=tuple(resolved),
        include_empty=include_empty,
    )


def _ensure_operator(condition: Condition, spec: SearchFieldSpec) -> None:
    if condition.operator not in spec.operators:
        raise SearchOperatorNotSupportedError(
            details={
                "field": condition.name,
                "position": condition.position,
                "operator": condition.operator.value,
                "allowed": sorted(operator.value for operator in spec.operators),
            },
        )


def _ensure_single_for_order(condition: Condition, count: int) -> None:
    """Сравнение по порядку принимает одно значение: «больше двух сразу» не значит ничего."""
    if condition.operator in SINGLE_VALUE_OPERATORS and count != 1:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": condition.position,
                "reason": "single_value_required",
                "operator": condition.operator.value,
                "got": count,
            },
        )


def _split_empty(
    condition: Condition,
    spec: SearchFieldSpec,
) -> tuple[tuple[SearchValue, ...], bool]:
    """Отделяет `empty()` от остальных значений условия.

    `empty()` — не значение, а признак его отсутствия, и держать их вперемешку значило
    бы искать маркер перебором в компиляторе. Поле, у которого пустого состояния не
    бывает (`queue`, `status`), отвергает маркер здесь, а не молча им пренебрегает.
    """
    values: list[SearchValue] = []
    include_empty = False
    for value in condition.values:
        if is_empty_marker(value):
            if not spec.is_nullable:
                raise SearchValueInvalidError(
                    details={
                        "field": condition.name,
                        "position": value.position,
                        "reason": "empty_not_supported",
                        "hint": "this field always has a value",
                    },
                )
            include_empty = True
            continue
        values.append(value)
    return tuple(values), include_empty


async def _resolve_value(
    session: AsyncSession,
    condition: Condition,
    spec: SearchFieldSpec,
    value: SearchValue,
) -> Any:
    match spec.kind:
        case SearchValueKind.QUEUE_KEY:
            return await _queue_id(session, condition, value)
        case SearchValueKind.TASK_KEY:
            return await _task_id(session, condition, value)
        case SearchValueKind.STATUS:
            return _enum_value(condition, value, TaskStatus)
        case SearchValueKind.PRIORITY:
            return _enum_value(condition, value, TaskPriority)
        case SearchValueKind.FLAG:
            return _flag(condition, value)
        case SearchValueKind.COUNT:
            return _count(condition, value)
        case SearchValueKind.TIMESTAMP:
            return _timestamp(condition, value)
        case _:
            return _text(condition, value)


async def _queue_id(session: AsyncSession, condition: Condition, value: SearchValue) -> Any:
    """Очередь по ключу. Ненайденная очередь — неверное значение фильтра, а не `404`.

    Промах здесь особенно важно назвать: `queue: TKR` без проверки дал бы пустую
    выдачу, неотличимую от «в очереди нет подходящих задач», и искать опечатку
    пришлось бы, глядя на данные.
    """
    key = _text(condition, value)
    try:
        queue = await queues_service.get_queue(session, key)
    except AppError as exc:
        raise _value_rejected(condition, value, exc, key) from exc
    return queue.id


async def _task_id(session: AsyncSession, condition: Condition, value: SearchValue) -> Any:
    """Задача по ключу. Ненайденная задача — неверное значение фильтра, а не `404`.

    Названный промах здесь важнее, чем у очереди: `parent: TKR-7` без проверки дал бы
    пустую выдачу, а пустая выдача на вопрос «что у детей этой задачи» читается как
    «детей нет» — то есть как ответ, а не как опечатка. На таком ответе программу
    закрывают.
    """
    key = _text(condition, value)
    try:
        task = await tasks_service.get_task(session, key)
    except AppError as exc:
        raise _value_rejected(condition, value, exc, key) from exc
    return task.id


def _text(condition: Condition, value: SearchValue) -> str:
    """Текст значения. Пустая строка отвергается: она не то же самое, что `empty()`.

    Молча искать по пустой строке значило бы отдавать либо всё (вхождение), либо
    ничего (равенство) — и в обоих случаях не то, что имел в виду клиент. Ни
    исполнителем, ни меткой пустая строка быть не может: домен их выбрасывает.
    """
    assert isinstance(value, Literal)
    if not value.text.strip():
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "reason": "empty_value",
                "hint": "use empty() to look for tasks with no value in this field",
            },
        )
    return value.text


def _enum_value(condition: Condition, value: SearchValue, enum_type: type) -> Any:
    raw = _text(condition, value)
    try:
        return enum_type(raw.strip().lower())
    except ValueError as exc:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": raw,
                "reason": "not_allowed",
                "allowed": [member.value for member in enum_type],
            },
        ) from exc


def _flag(condition: Condition, value: SearchValue) -> bool:
    """Логическое значение признака. Только `true` и `false`, без синонимов.

    Синонимы (`yes`, `1`) выглядят удобством, но означают второй словарь: клиент,
    выучивший `1`, однажды напишет его там, где ждут число, и получит другой ответ.
    """
    raw = _text(condition, value).strip().lower()
    if raw in {"true", "false"}:
        return raw == "true"
    raise SearchValueInvalidError(
        details={
            "field": condition.name,
            "position": value.position,
            "value": raw,
            "reason": "not_allowed",
            "allowed": ["true", "false"],
        },
    )


def _count(condition: Condition, value: SearchValue) -> int:
    """Счётчик — целое неотрицательное. Отрицательное значение всегда даёт пустую выдачу."""
    raw = _text(condition, value).strip()
    if not raw.isdigit():
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": raw,
                "reason": "type_mismatch",
                "expected": "non-negative integer",
            },
        )
    return int(raw)


def _timestamp(condition: Condition, value: SearchValue) -> datetime:
    """Мгновение в ISO-8601: дата или дата со временем.

    Дата (`2026-09-06`) означает полночь UTC. Значение без указания зоны читается как
    UTC: трекер хранит время в UTC, а подставить зону клиента молча значило бы
    отвечать на запрос, которого никто не задавал.

    Относительные значения (`7d`, `-3h`) не принимаются намеренно: они делают запрос
    невоспроизводимым — та же строка завтра означает другое, и пересланная ссылка на
    отбор перестаёт показывать то же самое.
    """
    raw = _text(condition, value).strip()
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": raw,
                "reason": "type_mismatch",
                "expected": "ISO-8601 date or date-time, for example 2026-09-06 "
                "or 2026-09-06T12:30:00Z",
            },
        ) from None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _value_rejected(
    condition: Condition,
    value: SearchValue,
    error: AppError,
    raw: str,
) -> SearchValueInvalidError:
    return SearchValueInvalidError(
        details={
            "field": condition.name,
            "position": value.position,
            "value": raw,
            "reason": error.code,
        },
    )


# --- Сортировка и выбор полей --------------------------------------------------------


def _resolve_sort(terms: Sequence[SortTerm]) -> tuple[ResolvedSort, ...]:
    """Ключи сортировки. Без явного порядка — по ключу задачи, по возрастанию.

    Умолчание одно на весь проект и объявлено в домене: два разных умолчания на один и
    тот же список означали бы, что переход с одного вызова на другой молча меняет
    выдачу.
    """
    if not terms:
        return (ResolvedSort(key=DEFAULT_SORT_KEY),)
    resolved: list[ResolvedSort] = []
    for term in terms:
        try:
            key = SortKey(term.name.strip().lower())
        except ValueError as exc:
            raise SearchFieldUnknownError(
                details={
                    "field": term.name,
                    "reason": "not_sortable",
                    "allowed": sortable_names(),
                },
            ) from exc
        resolved.append(ResolvedSort(key=key, descending=term.descending))
    return tuple(resolved)


def _resolve_fields(names: Sequence[str]) -> tuple[str, ...]:
    """Выбор возвращаемых полей.

    Пустой список означает «всё»: у запроса без явного выбора поведение должно совпадать
    с чтением задачи, иначе клиент получал бы разные объекты из двух мест.

    Ключ задачи добавляется всегда. Выдача без ключа бесполезна — по ней нельзя ни
    прочитать задачу, ни сослаться на неё, — а объяснять это каждому клиенту дороже,
    чем добавить одно поле.
    """
    requested = split_names(names)
    if not requested:
        return ()
    selected: list[str] = [MANDATORY_FIELD]
    for candidate in requested:
        if candidate not in SELECTABLE_FIELDS:
            raise SearchFieldUnknownError(
                details={
                    "field": candidate,
                    "reason": "not_selectable",
                    "allowed": selectable_names(),
                },
            )
        if candidate not in selected:
            selected.append(candidate)
    return tuple(selected)
