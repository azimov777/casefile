"""Поиск задач: компиляция внутреннего представления фильтра в запрос.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

## Почему компилятор здесь, а не в сценарии

Это единственное место проекта, где строится SQL по данным клиента. Собери его сценарий —
и `app/services` начал бы знать про колонки и операторы JSONB, а домен про них знать не
может вовсе. Сценарий отвечает на вопрос «что означает это имя и это значение», сюда
приходит уже разрешённый фильтр, и остаётся механический перевод.

## Три правила, которые здесь соблюдаются везде

**Отрицание включает отсутствие.** `assignee: != alice` обязано находить и неназначенные
задачи. В SQL сравнение с NULL даёт NULL, а не «истина», поэтому отрицания собираются
через `IS DISTINCT FROM` и явное `IS NULL`. Без этого «все, кроме Алисы» молча теряло бы
половину выдачи, и заметить это можно было бы только пересчитав руками.

**Дата без времени — это сутки.** Значение `today()` сравнивается с моментом времени
интервалом `[начало дня, начало следующего)`. Иначе `deadline: <= today()` означало бы
«раньше, чем сегодня началось» и не находило бы то, что просрочено сегодня.

**Порядок всегда заканчивается идентификатором.** Тайбрейкер добавляется здесь, а не
приходит из фильтра: `id` — свойство таблицы. Без него страницы теряли бы и дублировали
задачи с одинаковым значением ключа сортировки — а это ровно то, что делает массовая
вставка, ставящая всем задачам одно `created_at`.

## Что ложится на индексы, а что нет

Равенство по кастомному полю компилируется в `values @> :fragment` и ложится на GIN
`ix_issues_values`; проверка наличия значения — в `values ? :ref`, туда же. Сравнения
диапазонов по JSONB (`>` у числа или даты) индексом не покрываются ни при какой форме
записи: GIN по `jsonb_ops` знает только про вхождение. Это ограничение самого хранилища,
а не запроса, поэтому диапазон по кастомному полю стоит сочетать с условием по колонке —
очередью или статусом.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, case, false, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.catalog import Status
from app.db.models.comment import Comment
from app.db.models.issue import Issue, IssueFollower
from app.db.pagination import Page, decode_sort_cursor, encode_sort_cursor, resolve_limit
from app.db.sql import ilike_contains
from app.domain.fields import FieldValueType
from app.domain.issues import IssuePriority
from app.domain.search import (
    NEGATIVE_OPERATORS,
    CustomTerm,
    Junction,
    Operator,
    ResolvedFilter,
    ResolvedSort,
    SearchValueKind,
    SystemField,
    SystemTerm,
    Term,
    TermGroup,
)

#: Ранг приоритета: порядок членов `IssuePriority` — от низшего к высшему. Сравнение
#: `priority: >= major` опирается на него, а не на алфавит, в котором `blocker` меньше
#: `minor`. Словарь строится из перечисления, а не переписывается руками: второй список
#: приоритетов разошёлся бы с первым при добавлении значения.
PRIORITY_RANK: dict[IssuePriority, int] = {
    priority: index for index, priority in enumerate(IssuePriority)
}

#: Операторы точного совпадения: для них есть форма, ложащаяся на GIN-индекс.
_EXACT_OPERATORS = frozenset({Operator.EQ, Operator.NE, Operator.IN, Operator.NOT_IN})


class IssueSearchRepository:
    """Выборка задач по разрешённому фильтру."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_page(
        self,
        resolved: ResolvedFilter,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Issue]:
        """Страница задач по фильтру, в заданном порядке.

        Запрашивается на одну запись больше нужного — лишняя строка и есть признак
        следующей страницы. Значения ключей сортировки выбираются вместе с задачей:
        собрать из них курсор иначе было бы нечем, а второй запрос за теми же
        значениями означал бы удвоение работы на каждую страницу.
        """
        size = resolve_limit(limit)
        keys = [(_sort_expression(term), term.descending) for term in resolved.sort]

        statement: Select[Any] = select(Issue, *(expression for expression, _ in keys))
        condition = compile_filter(resolved)
        if condition is not None:
            statement = statement.where(condition)
        if cursor is not None:
            values, item_id = decode_sort_cursor(cursor, arity=len(keys))
            statement = statement.where(_after_cursor(keys, values, item_id))

        statement = statement.order_by(*_order_by(keys)).limit(size + 1)
        rows = list(await self._session.execute(statement))

        if len(rows) <= size:
            return Page(items=[row[0] for row in rows], next_cursor=None)
        page = rows[:size]
        last = page[-1]
        return Page(
            items=[row[0] for row in page],
            next_cursor=encode_sort_cursor(list(last[1:]), last[0].id),
        )


def compile_filter(resolved: ResolvedFilter) -> ColumnElement[bool] | None:
    """Условие отбора или `None`, если условий нет. Отдельно от выборки — ради счётчиков."""
    if resolved.root is None:
        return None
    return _compile(resolved.root)


def _compile(term: Term) -> ColumnElement[bool]:
    if isinstance(term, TermGroup):
        parts = [_compile(node) for node in term.nodes]
        if not parts:
            # Пустая группа — это «условий нет», а не «ничего не подходит». Отдать
            # `false()` значило бы молча вернуть пустую страницу на фильтр, который
            # клиент считает пустым.
            return true()
        return and_(*parts) if term.junction is Junction.AND else or_(*parts)
    if isinstance(term, SystemTerm):
        return _compile_system(term)
    return _compile_custom(term)


# --- Системные поля ----------------------------------------------------------------


def _compile_system(term: SystemTerm) -> ColumnElement[bool]:
    # Условие «значения нет» строится только когда его просили: у поля без пустого
    # состояния (`text`, `queue`) его не существует, и вычислять его заранее значило
    # бы падать на запросе, который ничего такого не спрашивал.
    empty = _system_empty(term.field) if term.include_empty else None
    body = _system_body(term) if term.values else None
    return _combine(body, empty, term.operator)


def _system_body(term: SystemTerm) -> ColumnElement[bool]:
    match term.kind:
        case SearchValueKind.QUEUE_KEY:
            return _scalar(Issue.queue_id, term.operator, term.values)
        case SearchValueKind.CATALOG_REF:
            return _scalar(_CATALOG_COLUMNS[term.field], term.operator, term.values)
        case SearchValueKind.ACTOR_KEY:
            if term.field is SystemField.FOLLOWERS:
                return _followers(term.operator, term.values)
            return _scalar(_ACTOR_COLUMNS[term.field], term.operator, term.values)
        case SearchValueKind.STATUS_CATEGORY:
            return _status_category(term.operator, term.values)
        case SearchValueKind.PRIORITY:
            return _priority(term.operator, term.values)
        case SearchValueKind.ISSUE_KEY:
            return _text(Issue.key, term.operator, term.values)
        case SearchValueKind.LINE:
            return _text(_LINE_COLUMNS[term.field], term.operator, term.values)
        case SearchValueKind.FULLTEXT:
            return _fulltext(term.operator, term.values)
        case SearchValueKind.TAG:
            return _tags(term.operator, term.values)
        case SearchValueKind.MOMENT:
            return _moment(_MOMENT_COLUMNS[term.field], term.operator, term.values)


_CATALOG_COLUMNS = {
    SystemField.STATUS: Issue.status_id,
    SystemField.ISSUE_TYPE: Issue.issue_type_id,
    SystemField.RESOLUTION: Issue.resolution_id,
}
_ACTOR_COLUMNS = {SystemField.AUTHOR: Issue.author_id, SystemField.ASSIGNEE: Issue.assignee_id}
_LINE_COLUMNS = {SystemField.SUMMARY: Issue.summary, SystemField.DESCRIPTION: Issue.description}
_MOMENT_COLUMNS = {
    SystemField.DEADLINE: Issue.deadline,
    SystemField.CREATED_AT: Issue.created_at,
    SystemField.UPDATED_AT: Issue.updated_at,
}


def _system_empty(field: SystemField) -> ColumnElement[bool]:
    """Что значит «значения нет» у системного поля.

    У каждого поля своё: у ссылки — NULL, у описания — пустая строка (проект не хранит
    в нём NULL), у тегов и наблюдателей — пустой набор. Один общий `IS NULL` дал бы
    неверный ответ ровно там, где пустое значение выражено иначе.
    """
    match field:
        case SystemField.ASSIGNEE:
            return Issue.assignee_id.is_(None)
        case SystemField.RESOLUTION:
            return Issue.resolution_id.is_(None)
        case SystemField.DEADLINE:
            return Issue.deadline.is_(None)
        case SystemField.DESCRIPTION:
            return Issue.description == ""
        case SystemField.TAGS:
            return func.jsonb_array_length(Issue.tags) == 0
        case SystemField.FOLLOWERS:
            return not_(Issue.id.in_(select(IssueFollower.issue_id)))
        case _:
            # Недостижимо: `empty()` пропускается только к полям с `is_nullable`.
            # Явная ошибка вместо тихого `false` — чтобы новое nullable-поле, забытое
            # здесь, назвало себя, а не отдавало пустую выдачу.
            raise ValueError(f"System field {field.value!r} has no empty state")


def _followers(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Наблюдатель — членство в наборе, а не колонка: у задачи их сколько угодно.

    Отрицание здесь означает «этот актор не наблюдает», а не «наблюдателей нет»:
    подзапрос отбирает задачи с нужным актором, и `NOT IN` убирает именно их.
    """
    member = Issue.id.in_(
        select(IssueFollower.issue_id).where(IssueFollower.actor_id.in_(list(values)))
    )
    return not_(member) if operator in NEGATIVE_OPERATORS else member


def _status_category(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Категория статуса — свойство справочника, поэтому условие идёт подзапросом.

    Подзапрос, а не соединение: соединение пришлось бы тащить через всю сборку запроса
    и следить, чтобы оно не задвоило строки при других условиях.
    """
    matching = Issue.status_id.in_(select(Status.id).where(Status.category.in_(list(values))))
    return not_(matching) if operator in NEGATIVE_OPERATORS else matching


def _priority(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    if operator in {Operator.EQ, Operator.NE, Operator.IN, Operator.NOT_IN}:
        return _scalar(Issue.priority, operator, values)
    rank = case(PRIORITY_RANK, value=Issue.priority)
    return _order_condition(rank, operator, PRIORITY_RANK[values[0]])


def _fulltext(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Название, описание и лента обсуждения одним условием.

    Текст удалённого комментария затёрт (`app/db/models/comment.py`), поэтому отдельное
    условие «кроме удалённых» не нужно: пустая строка не совпадёт ни с чем.

    Подзапрос по комментариям — `EXISTS`, а не соединение: у задачи их сотня, и
    соединение размножило бы задачу по числу совпавших реплик, сломав и пагинацию, и
    счёт. `correlate` указан явно, чтобы подзапрос ссылался на внешнюю задачу, а не
    выбирал все комментарии установки.
    """
    parts = [
        or_(
            ilike_contains(Issue.summary, value),
            ilike_contains(Issue.description, value),
            select(Comment.id)
            .where(Comment.issue_id == Issue.id, ilike_contains(Comment.body, value))
            .correlate(Issue)
            .exists(),
        )
        for value in values
    ]
    matching = or_(*parts)
    return not_(matching) if operator in NEGATIVE_OPERATORS else matching


def _tags(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Метки задачи: вхождение в массив JSONB.

    Точное совпадение, а не регистронезависимое: `tags @> '["release"]'` ложится на
    GIN-индекс, а `lower()` по элементам массива не ложится ни на какой. Канонический
    вид метки берётся из словаря тегов (`GET /api/v1/tags`) — он и есть источник
    написаний, и второй способ их перечислять проект не заводит.
    """
    if operator in {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        elements = func.jsonb_array_elements_text(Issue.tags).table_valued("value").lateral()
        matching = or_(
            *(
                select(elements.c.value)
                .where(ilike_contains(elements.c.value, value))
                .correlate(Issue)
                .exists()
                for value in values
            )
        )
    else:
        matching = or_(*(Issue.tags.contains([value]) for value in values))
    return not_(matching) if operator in NEGATIVE_OPERATORS else matching


# --- Кастомные поля ----------------------------------------------------------------


def _compile_custom(term: CustomTerm) -> ColumnElement[bool]:
    # `values ? :ref` — проверка наличия ключа в JSONB; она ложится на GIN-индекс
    # `ix_issues_values`, поэтому «поле не заполнено» стоит недорого.
    empty = not_(Issue.values.has_key(term.ref)) if term.include_empty else None
    body = _custom_body(term) if term.values else None
    return _combine(body, empty, term.operator)


def _custom_body(term: CustomTerm) -> ColumnElement[bool]:
    if term.operator in {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        return _custom_contains(term)
    matching = or_(*(_custom_single(term, value) for value in term.values))
    return not_(matching) if term.operator in NEGATIVE_OPERATORS else matching


def _custom_single(term: CustomTerm, value: Any) -> ColumnElement[bool]:
    """Одно значение условия по кастомному полю.

    Календарный день (`date`) приходит только от поля с временем и означает интервал
    суток — сценарий не приводит его к строке именно потому, что граница интервала
    зависит от оператора.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return _custom_day(term, value)
    if term.operator in _EXACT_OPERATORS:
        # Вхождение (`@>`), а не сравнение текста: только оно ложится на GIN-индекс
        # `ix_issues_values`. Форма фрагмента зависит от множественности — у
        # множественного поля значение лежит элементом массива, у одиночного скаляром,
        # и одно выражение на оба случая молча не нашло бы половину.
        fragment = {term.ref: [value]} if term.is_multiple else {term.ref: value}
        return Issue.values.contains(fragment)
    return _order_condition(_custom_expression(term.ref, term.value_type), term.operator, value)


def _custom_day(term: CustomTerm, value: date) -> ColumnElement[bool]:
    """Сутки у кастомного поля со временем: сравнение границ лексикографически.

    Строки ISO 8601 в UTC сравниваются как текст в том же порядке, что и моменты
    времени, — формат хранения подобран именно так (`app/domain/fields.py`). Поэтому
    интервал суток выражается парой префиксов, без приведения каждой строки к дате.
    """
    start = value.isoformat()
    end = (value + timedelta(days=1)).isoformat()
    if term.is_multiple:
        elements = (
            func.jsonb_array_elements_text(Issue.values[term.ref]).table_valued("value").lateral()
        )
        return (
            select(elements.c.value)
            .where(_day_condition(elements.c.value, term.operator, start, end))
            .correlate(Issue)
            .exists()
        )
    return _day_condition(Issue.values[term.ref].astext, term.operator, start, end)


def _day_condition(
    expression: ColumnElement[Any],
    operator: Operator,
    start: str,
    end: str,
) -> ColumnElement[bool]:
    match operator:
        case Operator.GT:
            return expression >= end
        case Operator.GTE:
            return expression >= start
        case Operator.LT:
            return expression < start
        case Operator.LTE:
            return expression < end
        case _:
            return and_(expression >= start, expression < end)


def _custom_contains(term: CustomTerm) -> ColumnElement[bool]:
    if term.is_multiple:
        elements = (
            func.jsonb_array_elements_text(Issue.values[term.ref]).table_valued("value").lateral()
        )
        matching = or_(
            *(
                select(elements.c.value)
                .where(ilike_contains(elements.c.value, value))
                .correlate(Issue)
                .exists()
                for value in term.values
            )
        )
    else:
        matching = or_(
            *(ilike_contains(Issue.values[term.ref].astext, value) for value in term.values)
        )
    return not_(matching) if term.operator in NEGATIVE_OPERATORS else matching


def _custom_expression(ref: str, value_type: FieldValueType) -> ColumnElement[Any]:
    """Значение кастомного поля в виде, пригодном для сравнения по порядку.

    Число приводится к `float`, всё остальное сравнивается как текст. Для дат это не
    упрощение, а следствие формата хранения (`app/domain/fields.py`): `YYYY-MM-DD` и
    ISO 8601 в UTC подобраны так, что лексикографический порядок совпадает с
    хронологическим. Приводить их к `timestamptz` пришлось бы на каждой строке, и
    выражение стало бы ещё дороже, чем оно есть.
    """
    if value_type is FieldValueType.NUMBER:
        return Issue.values[ref].as_float()
    return Issue.values[ref].astext


# --- Общие сборки ------------------------------------------------------------------


def _combine(
    body: ColumnElement[bool] | None,
    empty: ColumnElement[bool] | None,
    operator: Operator,
) -> ColumnElement[bool]:
    """Склейка условия по значениям с условием «значения нет».

    Правило зависит от знака оператора и другим быть не может: `assignee: alice,
    empty()` — это «Алиса или никто» (или), а `assignee: != alice, empty()` — «не Алиса
    и вообще назначена» (и). Склеить их одинаково значило бы получить условие, всегда
    истинное либо всегда ложное.
    """
    if body is None and empty is None:
        return true()
    if body is None:
        return not_(empty) if operator in NEGATIVE_OPERATORS else empty
    if empty is None:
        return body
    if operator in NEGATIVE_OPERATORS:
        return and_(body, not_(empty))
    return or_(body, empty)


def _scalar(
    column: ColumnElement[Any],
    operator: Operator,
    values: Sequence[Any],
) -> ColumnElement[bool]:
    """Равенство и его отрицание по колонке. Отрицание захватывает NULL.

    `IS DISTINCT FROM` вместо `<>`: сравнение с NULL даёт NULL, и `assignee <> :alice`
    выбросило бы из выдачи все неназначенные задачи — молча и вопреки смыслу «все,
    кроме Алисы».
    """
    match operator:
        case Operator.EQ:
            return column == values[0]
        case Operator.IN:
            return column.in_(list(values))
        case Operator.NE:
            return column.is_distinct_from(values[0])
        case Operator.NOT_IN:
            return or_(column.is_(None), column.notin_(list(values)))
        case _:
            return _order_condition(column, operator, values[0])


def _text(
    column: ColumnElement[Any],
    operator: Operator,
    values: Sequence[Any],
) -> ColumnElement[bool]:
    if operator in {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        matching = or_(*(ilike_contains(column, value) for value in values))
        return not_(matching) if operator in NEGATIVE_OPERATORS else matching
    return _scalar(column, operator, values)


def _moment(
    column: ColumnElement[Any],
    operator: Operator,
    values: Sequence[Any],
) -> ColumnElement[bool]:
    """Сравнение с моментом времени. Дата без времени сравнивается интервалом суток."""
    if operator in {Operator.EQ, Operator.IN, Operator.NE, Operator.NOT_IN}:
        matching = or_(*(_moment_equals(column, value) for value in values))
        return not_(matching) if operator in NEGATIVE_OPERATORS else matching
    return _moment_order(column, operator, values[0])


def _moment_equals(column: ColumnElement[Any], value: Any) -> ColumnElement[bool]:
    if isinstance(value, datetime):
        return column == value
    start, end = _day_bounds(value)
    return and_(column >= start, column < end)


def _moment_order(
    column: ColumnElement[Any],
    operator: Operator,
    value: Any,
) -> ColumnElement[bool]:
    if isinstance(value, datetime):
        return _order_condition(column, operator, value)
    start, end = _day_bounds(value)
    # Граница выбирается так, чтобы сами сутки целиком попадали в «не позже» и целиком
    # выпадали из «позже». Иначе `deadline: <= today()` теряло бы всё, что просрочено
    # сегодня, а `deadline: > today()` находило бы сегодняшний вечер.
    match operator:
        case Operator.GT:
            return column >= end
        case Operator.GTE:
            return column >= start
        case Operator.LT:
            return column < start
        case _:
            return column < end


def _day_bounds(value: date) -> tuple[datetime, datetime]:
    start = datetime(value.year, value.month, value.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _order_condition(
    expression: ColumnElement[Any],
    operator: Operator,
    value: Any,
) -> ColumnElement[bool]:
    match operator:
        case Operator.GT:
            return expression > value
        case Operator.GTE:
            return expression >= value
        case Operator.LT:
            return expression < value
        case Operator.LTE:
            return expression <= value
        case _:
            # Недостижимо: применимость оператора проверена сценарием до компиляции.
            raise ValueError(f"Operator {operator.value!r} is not an order comparison")


# --- Порядок и курсор --------------------------------------------------------------


def _sort_expression(term: ResolvedSort) -> ColumnElement[Any]:
    if term.ref is not None and term.value_type is not None:
        return _custom_expression(term.ref, term.value_type)
    match term.field:
        case SystemField.PRIORITY:
            return case(PRIORITY_RANK, value=Issue.priority)
        case SystemField.SUMMARY:
            return Issue.summary
        case SystemField.DEADLINE:
            return Issue.deadline
        case SystemField.UPDATED_AT:
            return Issue.updated_at
        case _:
            return Issue.created_at


def _order_by(keys: Sequence[tuple[ColumnElement[Any], bool]]) -> list[Any]:
    """Порядок с явным `NULLS LAST` и обязательным тайбрейкером в конце.

    `NULLS LAST` задан для обоих направлений намеренно, хотя PostgreSQL по умолчанию
    ставит их последними только при возрастании. Причина в курсоре: условие «строки
    после этой» приходится писать руками, и одно правило на оба направления вдвое
    короче двух — а короче здесь значит «без ошибки на границе».
    """
    order: list[Any] = [
        expression.desc().nullslast() if descending else expression.asc().nullslast()
        for expression, descending in keys
    ]
    order.append(Issue.id.asc())
    return order


def _after_cursor(
    keys: Sequence[tuple[ColumnElement[Any], bool]],
    values: Sequence[Any],
    item_id: uuid.UUID,
) -> ColumnElement[bool]:
    """«Строки строго после курсорной» для составного порядка.

    Кортежное сравнение (`(a, b) > (:x, :y)`) здесь неприменимо: направления ключей
    могут различаться, а NULL в кортеже делает сравнение неопределённым. Поэтому
    условие раскрыто лесенкой: равенство по всем предыдущим ключам плюс строгое
    «после» по текущему.
    """
    branches: list[ColumnElement[bool]] = []
    prefix: list[ColumnElement[bool]] = []
    for (expression, descending), value in zip(keys, values, strict=True):
        branches.append(and_(*prefix, _strictly_after(expression, value, descending)))
        prefix.append(expression.is_(None) if value is None else expression == value)
    branches.append(and_(*prefix, Issue.id > item_id))
    return or_(*branches)


def _strictly_after(
    expression: ColumnElement[Any],
    value: Any,
    descending: bool,
) -> ColumnElement[bool]:
    """Что идёт после значения при `NULLS LAST`.

    После NULL не идёт ничего: пустые значения стоят в конце, и «дальше» там только
    тайбрейкер. Для непустого значения после него идут и большие (меньшие при убывании),
    и пустые — они ниже по порядку.
    """
    if value is None:
        return false()
    beyond = expression < value if descending else expression > value
    return or_(beyond, expression.is_(None))
