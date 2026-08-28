"""Поиск задач: разрешение имён и значений, склейка источников фильтра, выборка.

Единственное место, где внутреннее представление фильтра встречается с базой. Разбор
языка живёт в домене и проверяется без базы, компиляция в SQL — в
`app/db/repositories/search.py`; здесь между ними стоит шаг, которому нужны реестр
полей, справочники и тот, кто задал вопрос.

## Три источника фильтра и один результат

Фильтр приходит строкой запроса, структурным набором параметров и ссылкой на
сохранённый фильтр — в любом сочетании. Все три превращаются в `SearchFilter` и
склеиваются по `and`. Отсюда и главное свойство: «доска плюс ещё одно условие» — это не
особый режим, а обычная склейка, и вести себя она обязана так же, как одна строка с тем
же смыслом.

Структурный фильтр разбирает свои значения **той же** функцией, что и язык
(`parse_value_expression`). Поэтому `{"assignee": ["me()"]}` и `assignee: me()` — это
буквально один и тот же путь исполнения, а не два похожих.

## Порядок разрешения имени

1. Системное поле (`app/domain/search.py`) — разрешается в колонку.
2. Зарезервированное системой имя без поиска (`links`, `comments`) — отказ с причиной.
3. Реестр полей — кастомное поле, значение в `values JSONB`.

Порядок явный. Реестр уже не даёт завести кастомное поле с ключом системного, поэтому
пересечения быть не может, но без явной последовательности `status` однажды начал бы
искаться в JSONB — и молча, потому что пустая выдача выглядит как «ничего не нашлось».

## Значение фильтра проверяется тем же валидатором, что и значение задачи

Кастомные значения приводятся к форме хранения через `validate_values` из домена.
Иначе фильтр понимал бы значение по-своему: искал бы `2026-8-1` там, где записано
`2026-08-01`, и не находил бы ничего — без единой ошибки.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.actor import Actor
from app.db.models.field import Field
from app.db.models.issue import Issue
from app.db.pagination import Page
from app.db.repositories import ActorRepository, IssueSearchRepository
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.errors import (
    SearchFieldUnknownError,
    SearchOperatorNotSupportedError,
    SearchValueInvalidError,
)
from app.domain.fields import (
    FieldSpec,
    FieldValueType,
    validate_values,
)
from app.domain.issues import IssuePriority
from app.domain.query_language import parse_query, parse_sort_terms, parse_value_expression
from app.domain.queues import format_issue_key, parse_issue_key
from app.domain.search import (
    MANDATORY_FIELD,
    MAX_CONDITIONS,
    MAX_GROUP_DEPTH,
    SEARCHABLE_SYSTEM_FIELDS,
    SELECTABLE_FIELDS,
    Condition,
    CustomTerm,
    FunctionValue,
    Group,
    Junction,
    Literal,
    Node,
    Operator,
    ResolvedFilter,
    ResolvedSort,
    SearchFilter,
    SearchFunction,
    SearchValue,
    SearchValueKind,
    SortTerm,
    SystemField,
    SystemFieldSpec,
    SystemTerm,
    Term,
    TermGroup,
    combine,
    count_conditions,
    depth_of,
    is_reserved_name,
    system_field_spec,
)
from app.services import fields as fields_service
from app.services import queues as queues_service
from app.services.permissions import ensure_allowed

#: Операторы, допустимые у кастомного поля каждого типа. Таблица здесь, а не в домене:
#: она про то, что умеет хранилище (`values JSONB`), а домен про хранилище не знает.
_TEXTUAL_OPERATORS = frozenset(
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
_ORDERED_OPERATORS = _EXACT_OPERATORS | {
    Operator.GT,
    Operator.GTE,
    Operator.LT,
    Operator.LTE,
}

CUSTOM_FIELD_OPERATORS: dict[FieldValueType, frozenset[Operator]] = {
    FieldValueType.STRING: _TEXTUAL_OPERATORS,
    FieldValueType.TEXT: _TEXTUAL_OPERATORS,
    FieldValueType.ENUM: _TEXTUAL_OPERATORS,
    FieldValueType.ACTOR: _TEXTUAL_OPERATORS,
    FieldValueType.ISSUE: _TEXTUAL_OPERATORS,
    FieldValueType.NUMBER: _ORDERED_OPERATORS,
    FieldValueType.DATE: _ORDERED_OPERATORS,
    FieldValueType.DATETIME: _ORDERED_OPERATORS,
    FieldValueType.BOOLEAN: _EXACT_OPERATORS,
}

_ORDER_ONLY = _ORDERED_OPERATORS - _EXACT_OPERATORS


@dataclass(frozen=True, slots=True)
class StructuredTerm:
    """Одно условие структурного фильтра до разбора значений.

    Значения — то, что прислал клиент: строки языка (`me()`, `today() - 7d`), числа и
    логические значения кастомных полей, `None` как «значения нет». Приведение к
    внутреннему представлению одно на все случаи, поэтому и тип один.
    """

    name: str
    values: Sequence[Any] = ()
    operator: Operator = Operator.EQ


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Результат поиска: страница задач и то, чем её просили ограничить.

    Разрешённый фильтр возвращается вместе со страницей, потому что выбор возвращаемых
    полей — часть ответа: сериализатору нужно знать, что именно просили, и вычислять
    это второй раз в HTTP-слое значило бы завести второе толкование `fields`.
    """

    page: Page[Issue]
    resolved: ResolvedFilter


async def search_issues(
    session: AsyncSession,
    *,
    initiator: Actor,
    query: str | None = None,
    structured: Sequence[StructuredTerm] = (),
    saved_filter_id: uuid.UUID | None = None,
    sort: Sequence[str] = (),
    fields: Sequence[str] = (),
    limit: int | None = None,
    cursor: str | None = None,
) -> SearchOutcome:
    """Находит задачи по любому сочетанию источников фильтра.

    Источники складываются по `and`: пустой набор источников означает «все задачи», а
    не ошибку — иначе перечисление задач и поиск без условий пришлось бы звать
    по-разному.

    Сортировка берётся из вызова, а если её не передали — из сохранённого фильтра. Свой
    порядок у сохранённого фильтра не украшение: «мои горящие» без сортировки по
    дедлайну отвечают на другой вопрос.
    """
    resolved = await resolve_issue_filter(
        session,
        initiator=initiator,
        query=query,
        structured=structured,
        saved_filter_id=saved_filter_id,
        sort=sort,
        fields=fields,
    )
    page = await IssueSearchRepository(session).search_page(resolved, limit=limit, cursor=cursor)
    return SearchOutcome(page=page, resolved=resolved)


async def resolve_issue_filter(
    session: AsyncSession,
    *,
    initiator: Actor,
    query: str | None = None,
    structured: Sequence[StructuredTerm] = (),
    saved_filter_id: uuid.UUID | None = None,
    sort: Sequence[str] = (),
    fields: Sequence[str] = (),
) -> ResolvedFilter:
    """Склейка всех источников отбора в один разрешённый фильтр, без самой выборки.

    Отдельно от `search_issues`, потому что выборка бывает не только страницей поиска:
    доска отбирает задачи тем же фильтром, но упорядочивает их своим рангом и потому
    строит запрос сама (`app/db/repositories/boards.py`). Разрешение имён и значений
    при этом обязано остаться одним — иначе доска понимала бы `assignee: me()` иначе,
    чем поиск, и расхождение было бы молчаливым.
    """
    ensure_allowed(initiator, "issue.search")

    parts: list[SearchFilter] = []
    if saved_filter_id is not None:
        # Импорт внутри функции: сценарии сохранённых фильтров опираются на этот
        # модуль (фильтр проверяется разбором при сохранении), и импорт на уровне
        # модуля замкнул бы их в цикл.
        from app.services import saved_filters as saved_filters_service

        stored = await saved_filters_service.get_saved_filter(session, saved_filter_id)
        parts.append(saved_filters_service.filter_of(stored))
    if query:
        parts.append(parse_query(query))
    if structured:
        parts.append(filter_from_structured(structured))

    merged = combine(parts)
    if sort:
        merged = replace(merged, sort=parse_sort_terms(sort))

    return await resolve_filter(session, merged, initiator=initiator, fields=fields)


def filter_from_structured(
    terms: Sequence[StructuredTerm],
    sort: Sequence[str] = (),
) -> SearchFilter:
    """Структурный фильтр → внутреннее представление.

    Условия складываются по `and`, значения одного условия — по `or` (`status: open,
    in_progress`). Это и есть смысл структурного фильтра: сузить по каждому параметру,
    но принять любое из перечисленных значений.
    """
    nodes: list[Node] = []
    for term in terms:
        if not term.values:
            continue
        values = tuple(_structured_value(item, position=0) for item in term.values)
        operator = term.operator
        if operator in {Operator.EQ, Operator.NE}:
            # Несколько значений превращают равенство во вхождение — тем же правилом,
            # что и в языке: `status: open, in_progress` обязано значить одно и то же,
            # как бы его ни прислали.
            payload = [value for value in values if not _is_empty_marker(value)]
            if len(payload) > 1:
                operator = Operator.IN if operator is Operator.EQ else Operator.NOT_IN
        nodes.append(Condition(name=term.name, operator=operator, values=values))
    if not nodes:
        return SearchFilter(sort=parse_sort_terms(sort) if sort else ())
    return SearchFilter(
        root=Group(Junction.AND, tuple(nodes)),
        sort=parse_sort_terms(sort) if sort else (),
    )


def _structured_value(value: Any, *, position: int) -> SearchValue:
    """Значение структурного фильтра по правилам языка.

    `None` — это `empty()`: в `values JSONB` отсутствие значения выражается именно так
    (`app/domain/fields.py`), и второй способ сказать то же самое проект не заводит.
    """
    if value is None:
        return FunctionValue(function=SearchFunction.EMPTY, position=position)
    if isinstance(value, bool):
        return Literal(text="true" if value else "false", position=position)
    if isinstance(value, int | float):
        return Literal(text=str(value), position=position)
    if isinstance(value, str):
        return parse_value_expression(value, position=position)
    raise SearchValueInvalidError(
        details={"value": repr(value), "reason": "unsupported_value_type"},
    )


def _is_empty_marker(value: SearchValue) -> bool:
    return isinstance(value, FunctionValue) and value.function is SearchFunction.EMPTY


# --- Разрешение --------------------------------------------------------------------


async def resolve_filter(
    session: AsyncSession,
    search_filter: SearchFilter,
    *,
    initiator: Actor,
    fields: Sequence[str] = (),
) -> ResolvedFilter:
    """Разобранный фильтр → готовый к компиляции: имена в поля, значения в значения.

    Потолки проверяются здесь, а не только при разборе строки: склейка нескольких
    источников может дать дерево, которого не было ни в одном из них.
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

    root = (
        None
        if search_filter.root is None
        else await _resolve_node(session, search_filter.root, initiator=initiator)
    )
    sort = await _resolve_sort(session, search_filter.sort, initiator=initiator)
    selected, value_refs = await _resolve_fields(session, fields, initiator=initiator)
    return ResolvedFilter(root=root, sort=sort, fields=selected, value_refs=value_refs)


async def _resolve_node(session: AsyncSession, node: Node, *, initiator: Actor) -> Term:
    if isinstance(node, Group):
        nodes = [await _resolve_node(session, child, initiator=initiator) for child in node.nodes]
        return TermGroup(junction=node.junction, nodes=tuple(nodes))
    return await _resolve_condition(session, node, initiator=initiator)


async def _resolve_condition(
    session: AsyncSession,
    condition: Condition,
    *,
    initiator: Actor,
) -> Term:
    spec = system_field_spec(condition.name)
    if spec is not None:
        return await _resolve_system(session, condition, spec, initiator=initiator)
    if is_reserved_name(condition.name):
        raise SearchFieldUnknownError(
            details={
                "field": condition.name,
                "position": condition.position,
                "reason": "not_searchable",
                "hint": "the name is reserved by the system and has no filter yet",
            },
        )
    field = await _lookup_field(session, condition.name, condition.position, initiator=initiator)
    return _resolve_custom(condition, field, initiator=initiator)


async def _lookup_field(
    session: AsyncSession,
    name: str,
    position: int,
    *,
    initiator: Actor,
) -> Field:
    """Кастомное поле по ссылке. Любой отказ становится «имя не разрешается».

    Не `field_not_found` с кодом 404: для поиска ненайденное имя — это неверный фильтр,
    а не отсутствующий ресурс, и `404` на поиске сбивал бы клиента с толку. Исходная
    причина остаётся в `details.reason`.
    """
    try:
        return await queues_service.resolve_field_ref(session, name, initiator=initiator)
    except AppError as exc:
        raise SearchFieldUnknownError(
            details={
                "field": name,
                "position": position,
                "reason": exc.code,
                **{key: value for key, value in exc.details.items() if key != "reason"},
            },
        ) from exc


def _ensure_operator(condition: Condition, allowed: frozenset[Operator]) -> None:
    if condition.operator not in allowed:
        raise SearchOperatorNotSupportedError(
            details={
                "field": condition.name,
                "position": condition.position,
                "operator": condition.operator.value,
                "allowed": sorted(operator.value for operator in allowed),
            },
        )


def _split_empty(
    condition: Condition,
    *,
    nullable: bool,
) -> tuple[tuple[SearchValue, ...], bool]:
    """Отделяет `empty()` от остальных значений условия.

    `empty()` — не значение, а признак его отсутствия, и держать их вперемешку значило
    бы искать маркер перебором в компиляторе. Поле, у которого пустого состояния не
    бывает (`queue`, `author`), отвергает маркер здесь, а не молча им пренебрегает.
    """
    values: list[SearchValue] = []
    include_empty = False
    for value in condition.values:
        if _is_empty_marker(value):
            if not nullable:
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


async def _resolve_system(
    session: AsyncSession,
    condition: Condition,
    spec: SystemFieldSpec,
    *,
    initiator: Actor,
) -> SystemTerm:
    _ensure_operator(condition, spec.operators)
    values, include_empty = _split_empty(condition, nullable=spec.is_nullable)
    resolved = [
        await _resolve_system_value(session, condition, spec, value, initiator=initiator)
        for value in values
    ]
    _ensure_single_for_order(condition, len(resolved))
    return SystemTerm(
        name=condition.name,
        field=spec.field,
        kind=spec.kind,
        operator=condition.operator,
        values=tuple(resolved),
        include_empty=include_empty,
    )


def _ensure_single_for_order(condition: Condition, count: int) -> None:
    """Сравнение по порядку принимает одно значение: «больше двух сразу» не значит ничего."""
    if condition.operator in _ORDER_ONLY and count != 1:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": condition.position,
                "reason": "single_value_required",
                "operator": condition.operator.value,
                "got": count,
            },
        )


async def _resolve_system_value(
    session: AsyncSession,
    condition: Condition,
    spec: SystemFieldSpec,
    value: SearchValue,
    *,
    initiator: Actor,
) -> Any:
    match spec.kind:
        case SearchValueKind.QUEUE_KEY:
            return (await _queue(session, condition, value)).id
        case SearchValueKind.PROJECT_KEY:
            return (await _project(session, condition, value)).id
        case SearchValueKind.CATALOG_REF:
            entry = await _catalog_entry(session, condition, spec, value, initiator=initiator)
            return entry.id
        case SearchValueKind.ACTOR_KEY:
            return (await _actor(session, condition, value, initiator=initiator)).id
        case SearchValueKind.STATUS_CATEGORY:
            return _enum_value(condition, value, StatusCategory)
        case SearchValueKind.PRIORITY:
            return _enum_value(condition, value, IssuePriority)
        case SearchValueKind.ISSUE_KEY:
            return _issue_key(condition, value)
        case SearchValueKind.MOMENT:
            return _moment(condition, value)
        case _:
            return _plain_text(condition, value)


def _plain_text(condition: Condition, value: SearchValue) -> str:
    if isinstance(value, FunctionValue):
        raise _function_not_allowed(condition, value, expected="a text value")
    return value.text


async def _queue(session: AsyncSession, condition: Condition, value: SearchValue) -> Any:
    key = _plain_text(condition, value)
    try:
        return await queues_service.get_queue_by_key(session, key)
    except AppError as exc:
        raise _value_rejected(condition, value, exc, key) from exc


async def _project(session: AsyncSession, condition: Condition, value: SearchValue) -> Any:
    """Проект по ключу. Ненайденный проект — неверное значение фильтра, а не `404`.

    Импорт внутри функции: сценарии проектов опираются на этот модуль (список задач
    проекта — это тот же поиск со склеенным условием), и импорт на уровне модуля
    замкнул бы их в цикл. Ровно тот же приём, что и с сохранёнными фильтрами выше.
    """
    from app.services import projects as projects_service

    key = _plain_text(condition, value)
    try:
        return await projects_service.get_project_by_key(session, key)
    except AppError as exc:
        raise _value_rejected(condition, value, exc, key) from exc


async def _catalog_entry(
    session: AsyncSession,
    condition: Condition,
    spec: SystemFieldSpec,
    value: SearchValue,
    *,
    initiator: Actor,
) -> Any:
    ref = _plain_text(condition, value)
    assert spec.catalog_kind is not None
    try:
        return await queues_service.resolve_catalog_ref(
            session,
            CatalogKind(spec.catalog_kind),
            ref,
            initiator=initiator,
        )
    except AppError as exc:
        raise _value_rejected(condition, value, exc, ref) from exc


async def _actor(
    session: AsyncSession,
    condition: Condition,
    value: SearchValue,
    *,
    initiator: Actor,
) -> Actor:
    key = _actor_key(condition, value, initiator=initiator)
    actor = await ActorRepository(session).get_by_key(key)
    if actor is None:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": key,
                "reason": "actor_not_found",
            },
        )
    return actor


def _actor_key(condition: Condition, value: SearchValue, *, initiator: Actor) -> str:
    """Ключ актора из значения. `me()` — тот, кто задал вопрос.

    Подстановка идёт в момент выполнения, а не сохранения: сохранённый фильтр
    «мои задачи» обязан означать «мои» для каждого, кто его запускает.
    """
    if isinstance(value, FunctionValue):
        if value.function is not SearchFunction.ME:
            raise _function_not_allowed(condition, value, expected="me() or an actor key")
        return initiator.key
    return value.text


def _issue_key(condition: Condition, value: SearchValue) -> str:
    raw = _plain_text(condition, value)
    try:
        queue_key, number = parse_issue_key(raw)
    except AppError as exc:
        raise _value_rejected(condition, value, exc, raw) from exc
    return format_issue_key(queue_key, number)


def _enum_value(condition: Condition, value: SearchValue, enum_type: type) -> Any:
    raw = _plain_text(condition, value)
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


def _moment(condition: Condition, value: SearchValue) -> date | datetime:
    """Момент времени или календарный день из значения.

    `date` в результате — это осознанный сигнал компилятору: сравнивать интервалом
    суток. Возвращать всегда `datetime`, подставив полночь, было бы проще и неверно:
    `deadline: <= today()` перестало бы находить просроченное сегодня.
    """
    if isinstance(value, FunctionValue):
        return _moment_function(condition, value)
    return _moment_literal(condition, value)


def _moment_function(condition: Condition, value: FunctionValue) -> date | datetime:
    if value.function is SearchFunction.NOW:
        return datetime.now(UTC) + timedelta(seconds=value.offset_seconds)
    if value.function is not SearchFunction.TODAY:
        raise _function_not_allowed(condition, value, expected="today(), now() or a date")
    moment = _today_start() + timedelta(seconds=value.offset_seconds)
    # Сдвиг, кратный суткам, оставляет значение днём; `today() + 12h` — уже момент.
    # Так `today() - 7d` продолжает означать «весь тот день», а не его полночь.
    if moment.timetz() == _today_start().timetz():
        return moment.date()
    return moment


def _moment_literal(condition: Condition, value: Literal) -> date | datetime:
    raw = value.text.strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": raw,
                "reason": "invalid_moment",
                "expected": "YYYY-MM-DD or ISO 8601 with a UTC offset",
            },
        ) from exc
    if parsed.tzinfo is None:
        # То же правило, что у дедлайна и кастомных полей: зону за клиента не
        # домысливают. Иначе фильтр «до полуночи» сработал бы со сдвигом в часах, и
        # заметили бы это на границе суток.
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": raw,
                "reason": "timezone_required",
                "expected": "ISO 8601 with a UTC offset",
            },
        )
    return parsed.astimezone(UTC)


def _today_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def _function_not_allowed(
    condition: Condition,
    value: FunctionValue,
    *,
    expected: str,
) -> SearchValueInvalidError:
    return SearchValueInvalidError(
        details={
            "field": condition.name,
            "position": value.position,
            "value": f"{value.function.value}()",
            "reason": "function_not_applicable",
            "expected": expected,
        },
    )


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


# --- Кастомные поля ----------------------------------------------------------------


def _resolve_custom(condition: Condition, field: Field, *, initiator: Actor) -> CustomTerm:
    spec = fields_service.spec_of(field)
    allowed = CUSTOM_FIELD_OPERATORS[field.value_type]
    if field.is_multiple:
        # У множественного поля значение — массив, и «больше» у массива не определено.
        # Молча сравнить первый элемент значило бы отвечать не на заданный вопрос.
        allowed = allowed - _ORDER_ONLY
    _ensure_operator(condition, allowed)

    values, include_empty = _split_empty(condition, nullable=True)
    resolved = [
        _custom_value(condition, spec, field, value, initiator=initiator) for value in values
    ]
    _ensure_single_for_order(condition, len(resolved))
    return CustomTerm(
        name=condition.name,
        ref=spec.ref,
        value_type=field.value_type,
        is_multiple=field.is_multiple,
        operator=condition.operator,
        values=tuple(resolved),
        include_empty=include_empty,
    )


def _custom_value(
    condition: Condition,
    spec: FieldSpec,
    field: Field,
    value: SearchValue,
    *,
    initiator: Actor,
) -> Any:
    """Значение кастомного поля в форме хранения.

    Вхождение подстроки — исключение: оно ищет по тексту, и приводить значение к типу
    поля здесь не нужно и вредно (`~ 26-08` — законный кусок даты, но не дата).
    """
    if condition.operator in {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        return _plain_text(condition, value)
    native = _custom_native(condition, spec, value, initiator=initiator)
    if isinstance(native, date) and not isinstance(native, datetime):
        # Календарный день у поля с временем компилируется интервалом; приводить его к
        # строке здесь нельзя — граница интервала зависит от оператора.
        return native
    single = FieldSpec(
        ref=spec.ref,
        value_type=spec.value_type,
        is_multiple=False,
        options=spec.options,
    )
    outcome = validate_values({spec.ref: native}, [single])
    if outcome.issues:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": native if isinstance(native, str | int | float | bool) else str(native),
                "reason": outcome.issues[0].reason,
                **outcome.issues[0].context,
            },
        )
    stored = outcome.values.get(spec.ref)
    if stored is None:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "reason": "empty_value",
                "hint": f"use empty() to look for issues without {field.key}",
            },
        )
    return stored


def _custom_native(
    condition: Condition,
    spec: FieldSpec,
    value: SearchValue,
    *,
    initiator: Actor,
) -> Any:
    """Текст из запроса → значение того типа, которого ждёт поле.

    Язык умеет только строки, а валидатор значений — только настоящие типы JSON. Этот
    шаг между ними и есть то место, где `estimate: > 5` перестаёт быть строкой `"5"`.
    """
    match spec.value_type:
        case FieldValueType.NUMBER:
            return _number(condition, value)
        case FieldValueType.BOOLEAN:
            return _boolean(condition, value)
        case FieldValueType.DATE:
            moment = _moment(condition, value)
            return moment.date().isoformat() if isinstance(moment, datetime) else moment.isoformat()
        case FieldValueType.DATETIME:
            moment = _moment(condition, value)
            # Календарный день остаётся `date`: границу интервала выберет компилятор,
            # и она зависит от оператора. Точный момент уходит строкой хранения.
            return moment.isoformat() if isinstance(moment, datetime) else moment
        case FieldValueType.ACTOR:
            # Ключ актора, а не идентификатор: в `values` лежит именно ключ
            # (`app/domain/fields.py`), поэтому и сравнивается ключ. `me()` работает
            # здесь так же, как у исполнителя, — иначе один и тот же вопрос «моё»
            # писался бы двумя способами.
            return _actor_key(condition, value, initiator=initiator)
        case _:
            return _plain_text(condition, value)


def _number(condition: Condition, value: SearchValue) -> float | int:
    raw = _plain_text(condition, value)
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError as exc:
        raise SearchValueInvalidError(
            details={
                "field": condition.name,
                "position": value.position,
                "value": raw,
                "reason": "type_mismatch",
                "expected": "number",
            },
        ) from exc


def _boolean(condition: Condition, value: SearchValue) -> bool:
    raw = _plain_text(condition, value).strip().lower()
    if raw in {"true", "yes", "1"}:
        return True
    if raw in {"false", "no", "0"}:
        return False
    raise SearchValueInvalidError(
        details={
            "field": condition.name,
            "position": value.position,
            "value": raw,
            "reason": "type_mismatch",
            "expected": "boolean",
        },
    )


# --- Сортировка и выбор полей ------------------------------------------------------


async def _resolve_sort(
    session: AsyncSession,
    terms: Sequence[SortTerm],
    *,
    initiator: Actor,
) -> tuple[ResolvedSort, ...]:
    """Ключи сортировки. Без явного порядка — по времени создания.

    Порядок по умолчанию тот же, что у простого перечисления задач: два разных
    умолчания на один и тот же список означали бы, что переход с `GET /issues` на поиск
    молча меняет выдачу.
    """
    if not terms:
        return (ResolvedSort(field=SystemField.CREATED_AT),)

    resolved: list[ResolvedSort] = []
    for term in terms:
        spec = system_field_spec(term.name)
        if spec is not None:
            if not spec.is_sortable:
                raise SearchFieldUnknownError(
                    details={
                        "field": term.name,
                        "reason": "not_sortable",
                        "allowed": sorted(_sortable_system_names()),
                    },
                )
            resolved.append(ResolvedSort(field=spec.field, descending=term.descending))
            continue
        if is_reserved_name(term.name):
            raise SearchFieldUnknownError(
                details={"field": term.name, "reason": "not_searchable"},
            )
        field = await _lookup_field(session, term.name, 0, initiator=initiator)
        if field.is_multiple:
            raise SearchFieldUnknownError(
                details={
                    "field": term.name,
                    "reason": "not_sortable",
                    "hint": "a multi-valued field has no single value to order by",
                },
            )
        resolved.append(
            ResolvedSort(
                ref=fields_service.field_ref(field),
                value_type=field.value_type,
                descending=term.descending,
            )
        )
    return tuple(resolved)


def _sortable_system_names() -> set[str]:
    return {spec.field.value for spec in SEARCHABLE_SYSTEM_FIELDS.values() if spec.is_sortable}


async def _resolve_fields(
    session: AsyncSession,
    names: Sequence[str],
    *,
    initiator: Actor,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Выбор возвращаемых полей: системные имена и ссылки кастомных полей.

    Пустой список означает «всё»: у запроса без явного выбора поведение должно
    совпадать с чтением задачи, иначе клиент получал бы разные объекты из двух мест.

    Ключ задачи добавляется всегда. Выдача без ключа бесполезна — по ней нельзя ни
    прочитать задачу, ни сослаться на неё, — а объяснять это каждому клиенту дороже,
    чем добавить одно поле.
    """
    if not names:
        return (), ()

    selected: list[str] = [MANDATORY_FIELD]
    refs: list[str] = []
    for name in names:
        candidate = name.strip()
        if candidate in SELECTABLE_FIELDS:
            if candidate not in selected:
                selected.append(candidate)
            continue
        if is_reserved_name(candidate) or system_field_spec(candidate) is not None:
            raise SearchFieldUnknownError(
                details={
                    "field": candidate,
                    "reason": "not_selectable",
                    "allowed": sorted(SELECTABLE_FIELDS),
                },
            )
        field = await _lookup_field(session, candidate, 0, initiator=initiator)
        reference = fields_service.field_ref(field)
        if reference not in refs:
            refs.append(reference)
    if refs and "values" not in selected:
        selected.append("values")
    return tuple(selected), tuple(refs)
