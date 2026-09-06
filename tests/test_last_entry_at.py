"""Признак `last_entry_at`: когда в дело последний раз подшивали запись агента.

Главное здесь — не «поле есть», а два свойства, ради которых оно заведено: служебные
записи его не двигают (иначе чужая связь выглядела бы жизнью), и оно не подменяет
`updated_at` (иначе два имени означали бы один факт).
"""

import time
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.case import AGENT_ENTRY_TYPES, SERVICE_ENTRY_TYPES, EntryType
from app.domain.errors import SearchFieldUnknownError, SearchValueInvalidError
from app.domain.links import LinkKind
from app.domain.search import SearchField, sortable_names
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import links as links_service
from app.services import search as service
from app.services import tasks as tasks_service
from app.services.auth import Actor

pytestmark = pytest.mark.anyio


async def make(session: AsyncSession, actor: Actor, queue: Queue, title: str) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        queue=queue,
        title=title,
        description="описание",
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
    )


async def feature_of(session: AsyncSession, actor: Actor, task: Task) -> Any:
    """Признак так, как его видит список: тем же подзапросом, что и выдача."""
    # Название в кавычках: в нём пробелы, а без кавычек язык видит два условия.
    found = await service.search_tasks(session, actor=actor, query=f'text: "{task.title}"')
    assert len(found.page.items) == 1, "расстановка должна давать ровно одну задачу"
    features = found.page.items[0].features
    assert features is not None
    return features.last_entry_at


# --- Какие записи считаются -----------------------------------------------------------


@pytest.mark.parametrize("entry_type", sorted(AGENT_ENTRY_TYPES, key=lambda item: item.value))
async def test_an_entry_of_an_agent_moves_the_feature(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
    owner: Any,
    entry_type: EntryType,
) -> None:
    """Каждый учтённый тип двигает признак — ровно по списку из решения TRK-6."""
    task = await make(db_session, task_actor, queue, f"учтённый {entry_type.value}")
    assert await feature_of(db_session, task_actor, task) is None

    entry = await _file(db_session, task_actor, task, entry_type)

    assert await feature_of(db_session, task_actor, task) == entry.created_at


async def _file(session: AsyncSession, actor: Actor, task: Task, entry_type: EntryType) -> Any:
    """Подшивает запись названного типа тем же способом, что и агент через MCP.

    Обёртки, а не общий `append_entry` с нагрузкой руками: у половины типов нагрузка
    проверяется доменом по существу — ответ ссылается на существующий вопрос, вердикт
    на существующую проверку, — и собрать её мимо сценария значит проверять не то.
    """
    match entry_type:
        case EntryType.SUMMARY:
            return await case_service.add_summary(
                session,
                task,
                actor=actor,
                done="сделано",
                remaining="осталось",
                blockers="ничего",
                next_step="следующий шаг",
            )
        case EntryType.QUESTION:
            return await case_service.ask(
                session, task, actor=actor, addressees=["owner"], title="Вопрос", blocking=False
            )
        case EntryType.ANSWER:
            question = await case_service.ask(
                session, task, actor=actor, addressees=["owner"], title="Вопрос", blocking=False
            )
            return await case_service.answer(
                session, task, actor=actor, question_no=question.no, body="Ответ"
            )
        case EntryType.VERDICT:
            return await case_service.add_verdict(
                session, task, actor=actor, check_no=1, outcome="passed", evidence="прогон зелёный"
            )
        case EntryType.RESOLUTION:
            remark = await case_service.add_entry(
                session, task, actor=actor, type=EntryType.REMARK, title="Вышло не то"
            )
            return await case_service.resolve(
                session,
                task,
                actor=actor,
                remark_no=remark.no,
                outcome="fixed",
                body="Поправил",
            )
        case _:
            return await case_service.add_entry(
                session, task, actor=actor, type=entry_type, title="Заголовок записи", body="тело"
            )


async def test_a_service_entry_does_not_move_the_feature(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Служебные записи признак не двигают — все шесть.

    Главный случай здесь — `link_added`: связь ставят с другой стороны, а запись
    появляется в обоих делах. Считай мы служебные, задача, которой месяц никто не
    касался, выглядела бы живой от чужого действия.
    """
    task = await make(db_session, task_actor, queue, "служебные не считаются")
    other = await make(db_session, task_actor, queue, "соседняя задача")

    # Заведение уже подшило `created` — служебную. Признак пуст.
    assert await feature_of(db_session, task_actor, task) is None

    await tasks_service.update_task(
        db_session, task, actor=task_actor, changes=tasks_service.TaskChanges(goal="новая цель")
    )
    await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.OPEN)
    await links_service.add_link(
        db_session, other, actor=task_actor, kind=LinkKind.RELATES, other=task
    )

    index = await case_service.case_index(db_session, task, actor=task_actor)
    kinds = {heading.type for heading in index}
    assert kinds <= SERVICE_ENTRY_TYPES, "в расстановке должны быть только служебные записи"
    assert EntryType.LINK_ADDED in kinds, "связь, поставленная соседом, обязана дойти до этого дела"

    assert await feature_of(db_session, task_actor, task) is None


# --- Разведение с `updated_at` --------------------------------------------------------


async def test_filing_an_entry_touches_neither_updated_at_nor_version(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Подшивка записи — не правка карточки: `updated_at` и `version` стоят на месте."""
    task = await make(db_session, task_actor, queue, "подшивка не трогает карточку")
    before_updated, before_version = task.updated_at, task.version

    await case_service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка"
    )
    await db_session.refresh(task)

    assert task.updated_at == before_updated
    assert task.version == before_version
    assert await feature_of(db_session, task_actor, task) is not None


# --- Пустое значение и порядок --------------------------------------------------------


async def test_a_fresh_task_has_no_value_and_sorts_last_in_both_directions(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Пустое значение осмысленно и в обоих направлениях лежит в конце.

    Пустое — это «агент в дело ещё ничего не писал», и таких задач в очереди много.
    Всплывай они наверх при `-last_entry_at`, сортировка «сначала где шевелилось»
    показывала бы ровно то, где не шевелилось.
    """
    fresh = await make(db_session, task_actor, queue, "свежая задача без записей")
    busy = await make(db_session, task_actor, queue, "задача, где уже есть запись")
    await case_service.add_entry(
        db_session, busy, actor=task_actor, type=EntryType.NOTE, title="Заметка"
    )

    assert await feature_of(db_session, task_actor, fresh) is None

    for sort in (["last_entry_at"], ["-last_entry_at"]):
        found = await service.search_tasks(db_session, actor=task_actor, sort=sort)
        keys = [item.task.key for item in found.page.items]
        assert keys.index(busy.key) < keys.index(fresh.key), f"порядок {sort}"


async def test_paging_by_cursor_does_not_repeat_or_lose_tasks_with_no_value(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Курсор устойчив на пустых значениях: страницы не пересекаются и не теряют строк."""
    for index in range(7):
        task = await make(db_session, task_actor, queue, f"задача {index}")
        if index % 2 == 0:
            await case_service.add_entry(
                db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка"
            )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        found = await service.search_tasks(
            db_session, actor=task_actor, sort=["-last_entry_at"], limit=2, cursor=cursor
        )
        seen.extend(item.task.key for item in found.page.items)
        if found.page.next_cursor is None:
            break
        cursor = found.page.next_cursor

    assert len(seen) == len(set(seen)), "страницы не должны повторять задачи"
    assert len(seen) == 7


# --- Язык запросов --------------------------------------------------------------------


async def test_the_field_filters_in_every_declared_operator(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Все заявленные операторы работают, и `empty()` находит задачи без записей."""
    fresh = await make(db_session, task_actor, queue, "без записей")
    busy = await make(db_session, task_actor, queue, "есть запись")
    entry = await case_service.add_entry(
        db_session, busy, actor=task_actor, type=EntryType.NOTE, title="Заметка"
    )
    moment = entry.created_at.isoformat()

    async def keys(query: str) -> set[str]:
        found = await service.search_tasks(db_session, actor=task_actor, query=query)
        return {item.task.key for item in found.page.items}

    assert busy.key in await keys(f'last_entry_at: >= "{moment}"')
    assert busy.key in await keys(f'last_entry_at: <= "{moment}"')
    assert busy.key not in await keys(f'last_entry_at: > "{moment}"')
    assert busy.key not in await keys(f'last_entry_at: < "{moment}"')
    assert busy.key in await keys(f'last_entry_at: = "{moment}"')
    assert busy.key not in await keys(f'last_entry_at: != "{moment}"')

    # Дата без времени — полночь UTC: задача с записью позже неё находится.
    day = entry.created_at.date().isoformat()
    assert busy.key in await keys(f'last_entry_at: >= "{day}"')

    empty = await keys("last_entry_at: empty()")
    assert fresh.key in empty
    assert busy.key not in empty


async def test_a_broken_moment_is_named_and_not_swallowed(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Негодное значение объясняется, а не даёт пустую выдачу."""
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="last_entry_at: > вчера")

    assert raised.value.details["reason"] == "type_mismatch"
    assert "ISO-8601" in raised.value.details["expected"]


async def test_the_field_is_listed_among_the_allowed_ones(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Ошибка разбора перечисляет новое поле среди допустимых — и в отборе, и в порядке."""
    with pytest.raises(SearchFieldUnknownError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="last_entry: > 2026-01-01")

    assert SearchField.LAST_ENTRY_AT.value in raised.value.details["allowed"]
    assert SearchField.LAST_ENTRY_AT.value in sortable_names()


# --- Стоимость ------------------------------------------------------------------------


async def test_a_page_of_fifty_tasks_still_costs_one_query(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Выдача списка не получила запроса на строку: признак считается подзапросом.

    Запросы считаются событием SQLAlchemy на соединении: перебор строк с походом в базу
    за признаком не виден ни по времени, ни по ответу — только по их числу.
    """
    for index in range(50):
        task = await make(db_session, task_actor, queue, f"строка {index}")
        await case_service.add_entry(
            db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка"
        )

    statements: list[str] = []
    connection = await db_session.connection()

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(connection.sync_connection.engine, "before_cursor_execute", record)
    try:
        found = await service.search_tasks(db_session, actor=task_actor, limit=50)
    finally:
        event.remove(connection.sync_connection.engine, "before_cursor_execute", record)

    assert len(found.page.items) == 50
    selects = [item for item in statements if item.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, f"на страницу ушло больше одного запроса: {selects}"


async def test_sorting_by_the_new_key_is_not_slower_by_an_order_of_magnitude(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Замер стоимости: порядок по новому ключу против порядка по `updated_at`.

    Числа не сравниваются с абсолютным потолком — на разной машине он разный. Сравнение
    относительное: подзапрос по каждой строке не должен превращать выдачу в другую
    задачу по стоимости.
    """
    await _seed_many(db_session, task_actor, queue, tasks=200, entries_per_task=5)

    async def measure(sort: list[str]) -> float:
        started = time.perf_counter()
        found = await service.search_tasks(db_session, actor=task_actor, sort=sort, limit=50)
        assert len(found.page.items) == 50
        return time.perf_counter() - started

    await measure(["-updated_at"])  # прогрев: первый запрос платит за план
    baseline = await measure(["-updated_at"])
    measured = await measure(["-last_entry_at"])

    assert measured < baseline * 20 + 0.5, f"{measured:.3f}s против {baseline:.3f}s"


async def _seed_many(
    session: AsyncSession, actor: Actor, queue: Queue, *, tasks: int, entries_per_task: int
) -> None:
    """Расстановка для замера. Записи подшиваются напрямую: сценарий здесь не проверяется."""
    for index in range(tasks):
        task = await make(session, actor, queue, f"нагрузка {index}")
        for number in range(entries_per_task):
            await session.execute(
                text(
                    "INSERT INTO entries (task_id, no, type, title, body, payload, refs,"
                    " created_by_kind, created_by_signature, created_at, updated_at)"
                    " VALUES (:task_id, :no, 'note', :title, '', '{}'::jsonb, '[]'::jsonb,"
                    " 'agent', 'seed', now(), now())"
                ),
                {"task_id": task.id, "no": number + 2, "title": f"заметка {number}"},
            )
    await session.flush()
