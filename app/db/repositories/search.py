"""Отбор задач: компиляция разрешённого фильтра в запрос.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

## Почему компилятор здесь, а не в сценарии

Это единственное место проекта, где SQL строится по данным клиента. Собери его
сценарий — и `app/services` начал бы знать про колонки и операторы JSONB, а домен про
них знать не может вовсе. Сценарий отвечает на вопрос «что означает это имя и это
значение», сюда приходит уже разрешённый фильтр, и остаётся механический перевод.

## Четыре правила, которые здесь соблюдаются везде

**Отрицание включает отсутствие.** `assignee: != alice` обязано находить и
неназначенные задачи. В SQL сравнение с NULL даёт NULL, а не «истина», поэтому
отрицания собираются через `IS DISTINCT FROM` и явное `IS NULL`. Без этого «все, кроме
Алисы» молча теряло бы половину выдачи, и заметить это можно было бы, только пересчитав
руками.

**Вычисляемый признак не переписывается.** `blocked` — это `EXISTS` над запросом
`open_blockers_of` из `app/db/repositories/links.py`, счётчики вопросов — скалярный
подзапрос `open_question_count` из `app/db/repositories/entries.py`. Оба запроса
написаны один раз и там же, где ими пользуется карточка: второе написание того же
условия развело бы поиск с карточкой молча (`CONCEPT.md`, 4.3).

**Порядок по ключу — это не порядок строки.** `TRK-10` обязан идти после `TRK-2`, а по
алфавиту он идёт раньше. Поэтому ключ раскладывается на пару «ключ очереди, номер», и
номер сравнивается числом.

**Порядок всегда заканчивается идентификатором.** Тайбрейкер добавляется здесь, а не
приходит из фильтра: `id` — свойство таблицы. Без него страницы теряли бы и дублировали
задачи с одинаковым значением ключа сортировки — а это ровно то, что делает массовая
вставка, ставящая всем задачам одно время.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import BigInteger, Select, and_, case, cast, false, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.pagination import Page, decode_sort_cursor, encode_sort_cursor, resolve_limit
from app.db.repositories.entries import open_question_count
from app.db.repositories.links import open_blockers_of
from app.db.sql import ilike_contains
from app.domain.search import (
    NEGATIVE_OPERATORS,
    ORDER_OPERATORS,
    Junction,
    Operator,
    ResolvedFilter,
    ResolvedSort,
    SearchField,
    SearchTerm,
    SearchValueKind,
    SortKey,
    Term,
    TermGroup,
)
from app.domain.tasks import TASK_KEY_SEPARATOR, TaskPriority

#: Ранг приоритета: порядок членов `TaskPriority` — от низшего к высшему. Сравнение
#: `priority: >= high` и сортировка опираются на него, а не на алфавит, в котором
#: `critical` меньше `low`. Словарь строится из перечисления, а не переписывается
#: руками: второй список приоритетов разошёлся бы с первым при добавлении значения.
PRIORITY_RANK: dict[TaskPriority, int] = {
    priority: index for index, priority in enumerate(TaskPriority)
}

#: Номер задачи внутри очереди, вынутый из ключа. Ключ очереди по шаблону не содержит
#: дефиса (`app/domain/queues.py`), поэтому вторая часть — всегда номер, и он приводится
#: к числу: строковое сравнение поставило бы `TRK-10` перед `TRK-2`.
TASK_NUMBER = cast(func.split_part(Task.key, TASK_KEY_SEPARATOR, 2), BigInteger)


class TaskSearchRepository:
    """Выборка задач по разрешённому фильтру."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_page(
        self,
        resolved: ResolvedFilter,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Task]:
        """Страница задач по фильтру, в заданном порядке.

        Очередь присоединяется явно и загружается через `contains_eager`, а не ленивой
        стратегией `joined` из модели: та добавила бы **второе** соединение с той же
        таблицей под собственным псевдонимом, к которому не обратиться из `ORDER BY`.
        Одно явное соединение и дешевле, и делает порядок по ключу выразимым.

        Запрашивается на одну запись больше нужного — лишняя строка и есть признак
        следующей страницы. Значения ключей сортировки выбираются вместе с задачей:
        собрать из них курсор иначе было бы нечем, а второй запрос за теми же
        значениями означал бы удвоение работы на каждую страницу.
        """
        size = resolve_limit(limit)
        keys = sort_keys(resolved.sort)
        statement: Select[Any] = select(Task).join(Task.queue).options(contains_eager(Task.queue))
        condition = compile_filter(resolved)
        if condition is not None:
            statement = statement.where(condition)
        statement = statement.add_columns(*(expression for expression, _ in keys))

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
    """Условие отбора или `None`, если условий нет."""
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
    return _compile_term(term)


def _compile_term(term: SearchTerm) -> ColumnElement[bool]:
    # Условие «значения нет» строится только когда его просили: у поля без пустого
    # состояния (`queue`, `status`) его не существует, и вычислять его заранее значило
    # бы падать на запросе, который ничего такого не спрашивал.
    empty = _empty_state(term) if term.include_empty else None
    body = _body(term) if term.values else None
    return _combine(body, empty, term.operator)


def _body(term: SearchTerm) -> ColumnElement[bool]:
    match term.kind:
        case SearchValueKind.QUEUE_KEY:
            return _scalar(Task.queue_id, term.operator, term.values)
        case SearchValueKind.STATUS:
            return _scalar(Task.status, term.operator, term.values)
        case SearchValueKind.ASSIGNEE:
            return _text(Task.assignee, term.operator, term.values)
        case SearchValueKind.TAG:
            return _tags(term.operator, term.values)
        case SearchValueKind.PRIORITY:
            return _priority(term.operator, term.values)
        case SearchValueKind.FLAG:
            return _blocked(term.operator, term.values)
        case SearchValueKind.COUNT:
            return _open_questions(term, term.operator, term.values)
        case SearchValueKind.FULLTEXT:
            return _fulltext(term.operator, term.values)


def _empty_state(term: SearchTerm) -> ColumnElement[bool]:
    """Что значит «значения нет» у поля.

    У исполнителя это NULL, у меток — пустой массив. Один общий `IS NULL` дал бы неверный
    ответ ровно там, где пустое значение выражено иначе: `tags` в базе никогда не NULL.
    """
    match term.kind:
        case SearchValueKind.ASSIGNEE:
            return Task.assignee.is_(None)
        case SearchValueKind.TAG:
            return func.jsonb_array_length(Task.tags) == 0
        case _:
            # Недостижимо: `empty()` пропускается только к полям с `is_nullable`. Явная
            # ошибка вместо тихого `false` — чтобы новое поле с пустым состоянием,
            # забытое здесь, назвало себя, а не отдавало неверную выдачу.
            raise ValueError(f"Search field {term.field.value!r} has no empty state")


# --- Отдельные виды значений ---------------------------------------------------------


def _tags(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Метки задачи: вхождение в массив JSONB.

    Точное совпадение, а не регистронезависимое: `tags @> '["backend"]'` ложится на
    GIN-индекс `ix_tasks_tags`, а `lower()` по элементам массива не ложится ни на какой,
    и регистронезависимый фильтр означал бы чтение всей таблицы на каждый запрос. Нужна
    нечёткость — есть оператор вхождения: `tags: ~ back`.
    """
    if operator in {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        elements = func.jsonb_array_elements_text(Task.tags).table_valued("value").lateral()
        matching = or_(
            *(
                select(elements.c.value)
                .where(ilike_contains(elements.c.value, value))
                .correlate(Task)
                .exists()
                for value in values
            )
        )
    else:
        matching = or_(*(Task.tags.contains([value]) for value in values))
    return not_(matching) if operator in NEGATIVE_OPERATORS else matching


def _priority(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Приоритет: равенство — по колонке, сравнение по порядку — по рангу.

    Равенство намеренно не переводится в ранг: `priority: high` ложится на колонку и
    читается в плане, а `CASE` вокруг неё отрезал бы от индекса всё условие сразу.
    """
    if operator not in ORDER_OPERATORS:
        return _scalar(Task.priority, operator, values)
    return _order_condition(_priority_rank(), operator, PRIORITY_RANK[values[0]])


def _blocked(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Признак `blocked` по тому же запросу, что и список блокеров у перехода.

    `EXISTS`, а не соединение: у задачи блокеров может быть несколько, и соединение
    размножило бы её по их числу, сломав и страницу, и порядок.
    """
    is_blocked = open_blockers_of(Task.id).correlate(Task).exists()
    matching = or_(*(is_blocked if value else not_(is_blocked) for value in values))
    return not_(matching) if operator in NEGATIVE_OPERATORS else matching


def _open_questions(
    term: SearchTerm,
    operator: Operator,
    values: Sequence[Any],
) -> ColumnElement[bool]:
    """Счётчик открытых вопросов — скалярный подзапрос по тому же определению, что в карточке.

    Подзапрос считается для каждой строки, дошедшей до этого условия, и это осознанная
    цена: колонки под признак нет намеренно (`CONCEPT.md`, 4.3), а сузить набор заранее
    можно любым условием по колонке — очередью, статусом, исполнителем. Подзапрос идёт
    по `ix_entries_task_id_type`.
    """
    blocking = True if term.field is SearchField.OPEN_BLOCKING_QUESTIONS else None
    counted = open_question_count(Task.id, blocking=blocking).correlate(Task).scalar_subquery()
    return _scalar(counted, operator, values)


def _fulltext(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Подстрока в названии и описании разом.

    Равенство здесь означает то же, что вхождение: точное совпадение со всем текстом
    задачи не имеет смысла, а отдельный оператор ради этого был бы лишним. Оба условия
    ложатся на триграммные индексы — но только на запросах от трёх символов
    (`docs/notes/search.md`).
    """
    matching = or_(
        *(
            or_(ilike_contains(Task.title, value), ilike_contains(Task.description, value))
            for value in values
        )
    )
    return not_(matching) if operator in NEGATIVE_OPERATORS else matching


# --- Общие формы условий -------------------------------------------------------------


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
        assert empty is not None
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


# --- Порядок и курсор ----------------------------------------------------------------


def _priority_rank() -> ColumnElement[Any]:
    return case(PRIORITY_RANK, value=Task.priority)


def sort_keys(terms: Sequence[ResolvedSort]) -> list[tuple[ColumnElement[Any], bool]]:
    """Ключи порядка выражениями: один ключ сортировки может дать больше одного.

    Так устроен порядок по ключу задачи: он раскладывается на пару «ключ очереди, номер»
    — иначе `TRK-10` встал бы перед `TRK-2`. Курсор от этого не усложняется: он хранит
    значения **выражений**, а не имена ключей, и их число проверяет `decode_sort_cursor`.
    """
    keys: list[tuple[ColumnElement[Any], bool]] = []
    for term in terms:
        for expression in _expressions(term.key):
            keys.append((expression, term.descending))
    return keys


def _expressions(key: SortKey) -> tuple[ColumnElement[Any], ...]:
    match key:
        case SortKey.KEY:
            return (Queue.key, TASK_NUMBER)
        case SortKey.UPDATED_AT:
            return (Task.updated_at,)
        case SortKey.PRIORITY:
            return (_priority_rank(),)


def _order_by(keys: Sequence[tuple[ColumnElement[Any], bool]]) -> list[Any]:
    """Порядок с явным `NULLS LAST` и обязательным тайбрейкером в конце.

    `NULLS LAST` задан для обоих направлений намеренно, хотя PostgreSQL по умолчанию
    ставит их последними только при возрастании. Причина в курсоре: условие «строки
    после этой» приходится писать руками, и одно правило на оба направления вдвое
    короче двух — а короче здесь значит «без ошибки на границе, где значение пустое».
    """
    order: list[Any] = [
        expression.desc().nullslast() if descending else expression.asc().nullslast()
        for expression, descending in keys
    ]
    order.append(Task.id.asc())
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

    Отсюда и устойчивость страницы к вставкам: граница задана значением ключа, а не
    смещением, поэтому новая задача, попавшая в выборку между запросами, ни сдвинет
    выдачу, ни вытеснит из неё соседа.
    """
    branches: list[ColumnElement[bool]] = []
    prefix: list[ColumnElement[bool]] = []
    for (expression, descending), value in zip(keys, values, strict=True):
        branches.append(and_(*prefix, _strictly_after(expression, value, descending)))
        prefix.append(expression.is_(None) if value is None else expression == value)
    branches.append(and_(*prefix, Task.id > item_id))
    return or_(*branches)


def _strictly_after(
    expression: ColumnElement[Any],
    value: Any,
    descending: bool,
) -> ColumnElement[bool]:
    """Что идёт после значения при `NULLS LAST`.

    После NULL не идёт ничего: пустые значения стоят в конце, и «дальше» там только
    тайбрейкер. Для непустого значения после него идут и большие (меньшие при
    убывании), и пустые — они ниже по порядку.
    """
    if value is None:
        return false()
    beyond = expression < value if descending else expression > value
    return or_(beyond, expression.is_(None))
