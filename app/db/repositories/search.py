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
подзапрос `open_question_count`, время последней сводки — `latest_summary`, оба из
`app/db/repositories/entries.py`. Все запросы написаны один раз и там же, где ими
пользуется карточка: второе написание того же условия развело бы поиск с карточкой
молча (`CONCEPT.md`, 4.3). Отсюда же собираются признаки **в строках выдачи**
(`feature_columns`): условие отбора и колонка ответа — один и тот же запрос, поэтому
`blocked: false` и `features.blocked` не могут разойтись.

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

from app.db.models.link import Link
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.pagination import (
    Page,
    decode_sort_cursor,
    encode_sort_cursor,
    resolve_limit,
    resolve_offset,
)
from app.db.repositories.entries import (
    last_entry_at,
    last_summary_at,
    open_question_count,
    open_remark_count,
    remarks_in_work_count,
)
from app.db.repositories.links import open_blockers_of, parents_of
from app.db.sql import ilike_contains
from app.domain.links import LinkKind
from app.domain.search import (
    FEATURES_FIELD,
    NEGATIVE_OPERATORS,
    ORDER_OPERATORS,
    PARENTS_FIELD,
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
    field_requested,
)
from app.domain.tasks import TASK_KEY_SEPARATOR, TaskFeatures, TaskParent, TaskPriority

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


#: Строка выдачи: задача, её вычисляемые признаки и её прямые родители. `None` в признаках
#: и в родителях означает «их не просили», а не «признаков нет» или «родителей нет»:
#: считать подзапросы ради ответа, в котором их не будет, — работа в никуда. Задача без
#: родителей — пустой кортеж. Сценарий заворачивает тройку в `FoundTask`.
TaskRow = tuple[Task, TaskFeatures | None, tuple[TaskParent, ...] | None]


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
        offset: int | None = None,
        with_total: bool = False,
    ) -> Page[TaskRow]:
        """Страница задач по фильтру, в заданном порядке, с признаками каждой строки.

        Очередь присоединяется явно и загружается через `contains_eager`, а не ленивой
        стратегией `joined` из модели: та добавила бы **второе** соединение с той же
        таблицей под собственным псевдонимом, к которому не обратиться из `ORDER BY`.
        Одно явное соединение и дешевле, и делает порядок по ключу выразимым.

        Запрашивается на одну запись больше нужного — лишняя строка и есть признак
        следующей страницы. Значения ключей сортировки выбираются вместе с задачей:
        собрать из них курсор иначе было бы нечем, а второй запрос за теми же
        значениями означал бы удвоение работы на каждую страницу.

        Признаки — подзапросы на строку, и добавляются они только когда их просили
        (`fields`): выдача из одного столбца ключей не должна платить за то, чего в ней
        нет. Стоимость измерена и записана в `docs/notes/search.md`. Родители — ещё один
        такой подзапрос (`parents_of`) и по тому же правилу: страница с родителями — это
        по-прежнему **один** запрос, сколько бы в ней ни было строк (`CONCEPT.md`, 4.4).

        `offset` и `with_total` — платные и потому необязательные, а решение платить
        принимает вызывающий: смещение читает и выбрасывает пропускаемые строки и
        сдвигает страницу на вставке, а `with_total` — второй запрос по тому же отбору.
        Обе цены осмысленны только там, где выдачу показывают страницами человеку
        (`GET /api/v1/tasks`); обход выдачи агентом идёт курсором и не платит ни за что
        (задача TRK-41, `app/db/pagination.py`).
        """
        size = resolve_limit(limit)
        start = resolve_offset(offset, cursor=cursor)
        keys = sort_keys(resolved.sort)
        wanted = field_requested(FEATURES_FIELD, resolved.fields)
        with_parents = field_requested(PARENTS_FIELD, resolved.fields)
        statement: Select[Any] = select(Task).join(Task.queue).options(contains_eager(Task.queue))
        condition = compile_filter(resolved)
        if condition is not None:
            statement = statement.where(condition)
        # Порядок колонок в строке: задача, значения ключей сортировки, признаки,
        # родители. Курсор берёт только середину — отсюда явные границы среза ниже:
        # признаки и родители в него попасть не должны, а их наличие зависит от `fields`.
        statement = statement.add_columns(*(expression for expression, _ in keys))
        if wanted:
            statement = statement.add_columns(*feature_columns())
        if with_parents:
            statement = statement.add_columns(parents_column())

        if cursor is not None:
            values, item_id = decode_sort_cursor(cursor, arity=len(keys))
            statement = statement.where(_after_cursor(keys, values, item_id))

        statement = statement.order_by(*_order_by(keys)).limit(size + 1)
        if start is not None:
            statement = statement.offset(start)
        rows = list(await self._session.execute(statement))
        total = await self._count(condition) if with_total else None

        page = rows[:size]
        items: list[TaskRow] = [
            (
                row[0],
                _features_of(row) if wanted else None,
                _parents_of(row) if with_parents else None,
            )
            for row in page
        ]
        if len(rows) <= size:
            return Page(items=items, next_cursor=None, total=total)
        last = page[-1]
        return Page(
            items=items,
            next_cursor=encode_sort_cursor(list(last[1 : 1 + len(keys)]), last[0].id),
            total=total,
        )

    async def _count(self, condition: ColumnElement[bool] | None) -> int:
        """Сколько задач нашлось по отбору — без страницы, порядка и признаков.

        Условие берётся то же самое, что и у страницы, а не пишется вторым текстом:
        разошлись бы они молча, и «всего 98» рядом с двумя страницами по 50 не удивило
        бы никого. Порядок и признаки на число строк не влияют и в счёт не идут:
        сортировать то, что тут же схлопывается в одно число, — работа в никуда.

        Соединение с очередью остаётся: по ней отбирают (`queue: TRK`), а внешний ключ
        обязателен и соединение внутреннее, поэтому число строк от него не меняется.
        """
        statement = select(func.count()).select_from(Task).join(Task.queue)
        if condition is not None:
            statement = statement.where(condition)
        # `COUNT(*)` отдаёт строку всегда, в том числе `0` на пустой выдаче: `None`
        # здесь недостижим и подставлен ради типа.
        return await self._session.scalar(statement) or 0


def feature_columns() -> tuple[ColumnElement[Any], ...]:
    """Вычисляемые признаки колонками выдачи — теми же запросами, что и отбор по ним.

    Ни одного нового условия: `blocked` — тот же `open_blockers_of`, что у проверки
    перехода и у фильтра, счётчики — тот же `open_question_count`, время сводки — тот же
    `latest_summary`, которым карточка читает саму запись. Третье написание любого из них
    развело бы список с карточкой молча (`CONCEPT.md`, 4.3).

    Метки обязательны: строка читается по именам (`_features_of`), а не по номерам
    колонок, — иначе перестановка двух счётчиков местами поменяла бы смысл ответа, ничего
    не сломав ни в одном тесте, кроме тех, где счётчики различаются.
    """
    return (
        open_blockers_of(Task.id).correlate(Task).exists().label("blocked"),
        open_question_count(Task.id).correlate(Task).scalar_subquery().label("open_questions"),
        open_question_count(Task.id, blocking=True)
        .correlate(Task)
        .scalar_subquery()
        .label("open_blocking_questions"),
        open_remark_count(Task.id).correlate(Task).scalar_subquery().label("open_remarks"),
        last_summary_at(Task.id).correlate(Task).scalar_subquery().label("last_summary_at"),
        last_entry_at(Task.id).correlate(Task).scalar_subquery().label("last_entry_at"),
    )


def parents_column() -> ColumnElement[Any]:
    """Прямые родители колонкой выдачи: JSON-список `{key, title}` на каждую строку.

    Подзапрос коррелирован с задачей страницы и считается после `Limit` — по строке
    страницы, а не по всей таблице, — поэтому число запросов от размера страницы не
    зависит. Метка обязательна по той же причине, что у признаков: строка читается по
    именам.
    """
    return parents_of(Task.id).correlate(Task).scalar_subquery().label(PARENTS_FIELD)


def _parents_of(row: Any) -> tuple[TaskParent, ...]:
    """Родители из строки выдачи: доменный тип, а не словари из JSON базы."""
    return tuple(TaskParent(key=item["key"], title=item["title"]) for item in row.parents)


def _features_of(row: Any) -> TaskFeatures:
    """Признаки из строки выдачи. Тот же тип, что у карточки: представление одно."""
    return TaskFeatures(
        blocked=row.blocked,
        open_questions=row.open_questions,
        open_blocking_questions=row.open_blocking_questions,
        open_remarks=row.open_remarks,
        last_summary_at=row.last_summary_at,
        last_entry_at=row.last_entry_at,
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
        case SearchValueKind.TASK_KEY:
            return _task_key(term)
        case SearchValueKind.STATUS:
            return _scalar(Task.status, term.operator, term.values)
        case SearchValueKind.ASSIGNEE:
            return _text(Task.assignee, term.operator, term.values)
        case SearchValueKind.PRIORITY:
            return _priority(term.operator, term.values)
        case SearchValueKind.FLAG:
            return _blocked(term.operator, term.values)
        case SearchValueKind.COUNT:
            return _counter(term, term.operator, term.values)
        case SearchValueKind.TIMESTAMP:
            return _scalar(_last_entry_at_column(), term.operator, term.values)
        case SearchValueKind.FULLTEXT:
            return _fulltext(term.operator, term.values)


def _empty_state(term: SearchTerm) -> ColumnElement[bool]:
    """Что значит «значения нет» у поля.

    У исполнителя это NULL, у времени последней записи — пустой подзапрос. Один общий
    `IS NULL` по колонке подошёл бы не всякому полю: пустое состояние выражается тем, чем
    оно выражено в базе, и у считаемого поля колонки нет вовсе.
    """
    match term.kind:
        case SearchValueKind.ASSIGNEE:
            return Task.assignee.is_(None)
        case SearchValueKind.TASK_KEY if term.field is SearchField.PARENT:
            # «Родителя нет» — верхний уровень очереди: ни одной связи `parent`, где
            # эта задача была бы ребёнком. Колонки под родителя нет, и `IS NULL` тут
            # не о чем спросить. Условие на поле, а не на вид значения: ключ самой
            # задачи того же вида, но пустого состояния у него не бывает.
            return not_(_has_parent())
        case SearchValueKind.TIMESTAMP:
            # «В дело ещё ничего не подшивали»: учтённых записей нет, подзапрос пуст.
            return _last_entry_at_column().is_(None)
        case _:
            # Недостижимо: `empty()` пропускается только к полям с `is_nullable`. Явная
            # ошибка вместо тихого `false` — чтобы новое поле с пустым состоянием,
            # забытое здесь, назвало себя, а не отдавало неверную выдачу.
            raise ValueError(f"Search field {term.field.value!r} has no empty state")


# --- Отдельные виды значений ---------------------------------------------------------


def _has_parent(source_id: Any = None) -> ColumnElement[bool]:
    """Есть ли у строки выдачи родитель — а с `source_id` ещё и назван ли им этот.

    `EXISTS`, а не соединение: соединение размножило бы задачу по числу связей и
    сломало бы и страницу, и порядок. Хранится связь одной строкой `source → target`
    вида `parent`, где источник — родитель, а цель — ребёнок (`app/domain/links.py`,
    `canonical_form`), поэтому ребёнок ищется по `target_id`.
    """
    conditions = [Link.kind == LinkKind.PARENT, Link.target_id == Task.id]
    if source_id is not None:
        conditions.append(Link.source_id == source_id)
    return select(Link.id).where(*conditions).correlate(Task).exists()


def _task_key(term: SearchTerm) -> ColumnElement[bool]:
    """Значение-ключ задачи: чей он, решает поле.

    Вид значения у `parent` и `key` один — оба разрешаются в идентификатор задачи одним
    и тем же путём сценария, — а условия разные: родитель живёт связью, ключ самой
    задачи колонкой. Тот же приём, что у счётчиков (`_counted`): вид значения отвечает
    за проверку, поле — за то, куда условие ложится.
    """
    match term.field:
        case SearchField.PARENT:
            return _parent(term.operator, term.values)
        case SearchField.KEY:
            # Сравнение идёт по `id`, а не по строке ключа: ключ уже разрешён в задачу
            # сценарием, и второе сравнение — по тексту, с оглядкой на регистр — было бы
            # вторым толкованием одного значения.
            return _scalar(Task.id, term.operator, term.values)
        case _:
            # Недостижимо: вид `task_key` носят только эти два поля. Явная ошибка вместо
            # тихого условия — чтобы третье поле назвало себя, а не отбирало не то.
            raise ValueError(f"Search field {term.field.value!r} has no task-key condition")


def _parent(operator: Operator, values: Sequence[Any]) -> ColumnElement[bool]:
    """Дети названной задачи. Значение — идентификатор родителя, разрешённый сценарием.

    Родство прямое и на одно колено: внуки сюда не попадают. Рекурсия потребовала бы
    обхода графа на каждую строку выдачи, а вопрос, ради которого поле заведено, —
    «все ли дети закрыты» — про прямых детей.
    """
    matching = or_(*(_has_parent(value) for value in values))
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


def _counter(
    term: SearchTerm,
    operator: Operator,
    values: Sequence[Any],
) -> ColumnElement[bool]:
    """Счётчик дела — скалярный подзапрос по тому же определению, что в карточке.

    Подзапрос считается для каждой строки, дошедшей до этого условия, и это осознанная
    цена: колонки под признак нет намеренно (`CONCEPT.md`, 4.3), а сузить набор заранее
    можно любым условием по колонке — очередью, статусом, исполнителем. Подзапросы идут
    по `ix_entries_task_id_type`.
    """
    return _scalar(_counted(term.field), operator, values)


def _counted(field: SearchField) -> ColumnElement[Any]:
    """Какой счёт стоит за именем поля. Все четыре — чужие определения, не свои.

    `remarks_in_work` — единственный, кто заглядывает в другую задачу: он соединяется с
    ней по ключу из нагрузки резолюции и смотрит на её статус (`CONCEPT.md`, 4.4).
    Признаком карточки он поэтому и не стал.
    """
    match field:
        case SearchField.OPEN_QUESTIONS:
            counted = open_question_count(Task.id)
        case SearchField.OPEN_BLOCKING_QUESTIONS:
            counted = open_question_count(Task.id, blocking=True)
        case SearchField.OPEN_REMARKS:
            counted = open_remark_count(Task.id)
        case SearchField.REMARKS_IN_WORK:
            counted = remarks_in_work_count(Task.id)
        case _:
            # Недостижимо: сюда приходят только поля вида `COUNT`. Явная ошибка вместо
            # тихого нуля — чтобы новый счётчик, забытый здесь, назвал себя сам.
            raise ValueError(f"Search field {field.value!r} is not a counter")
    return counted.correlate(Task).scalar_subquery()


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


def _last_entry_at_column() -> ColumnElement[Any]:
    """Признак `last_entry_at` выражением — тот же подзапрос, что и в выдаче.

    Одно определение на отбор, сортировку и колонку ответа: три написания разошлись бы
    молча, и список показывал бы одно, а отбирал по другому (`CONCEPT.md`, 4.3).
    """
    return last_entry_at(Task.id).correlate(Task).scalar_subquery()


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
        case SortKey.LAST_ENTRY_AT:
            return (_last_entry_at_column(),)


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
