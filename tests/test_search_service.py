"""Сценарий отбора задач: два входа с одним результатом, вычисляемые признаки, курсор.

Главная проверка набора — не «фильтр находит задачу», а «строка и структурный фильтр
находят одно и то же в одном порядке» и «признак в карточке совпадает с отбором». Оба
свойства держатся на том, что второй реализации нет; тесты стерегут это на данных.
"""

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.errors import (
    SearchFieldUnknownError,
    SearchOperatorNotSupportedError,
    SearchValueInvalidError,
)
from app.domain.links import LinkKind
from app.domain.tasks import TaskFeatures, TaskPriority, TaskStatus
from app.services import case as case_service
from app.services import links as links_service
from app.services import queues as queues_service
from app.services import search as service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.search import StructuredTerm


async def make(
    session: AsyncSession,
    actor: Actor,
    queue: Queue,
    title: str,
    *,
    description: str = "описание",
    assignee: str | None = None,
    tags: list[str] | None = None,
    priority: TaskPriority = TaskPriority.NORMAL,
) -> Task:
    """Задача в `backlog` с заполненными разделами: готова идти по цепочке статусов."""
    return await tasks_service.create_task(
        session,
        actor=actor,
        queue=queue,
        title=title,
        description=description,
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
        assignee=assignee,
        tags=tags or [],
        priority=priority,
    )


async def open_task(session: AsyncSession, actor: Actor, task: Task) -> Task:
    """Переводит задачу в `open`: в этом статусе её и ищет назначатель."""
    mutation = await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.OPEN)
    return mutation.task


async def keys(
    session: AsyncSession,
    actor: Actor,
    **call: object,
) -> list[str]:
    """Ключи найденных задач в порядке выдачи — то, что сравнивают почти все проверки."""
    outcome = await service.search_tasks(session, actor=actor, **call)  # type: ignore[arg-type]
    return [found.task.key for found in outcome.page.items]


async def found_features(session: AsyncSession, actor: Actor, key: str) -> TaskFeatures | None:
    """Признаки задачи так, как их видит строка списка: подзапросами прямо при выборке."""
    outcome = await service.search_tasks(session, actor=actor)
    found = [item for item in outcome.page.items if item.task.key == key]
    assert len(found) == 1, key
    return found[0].features


@pytest.fixture
async def board(db_session: AsyncSession, task_actor: Actor, queue: Queue) -> dict[str, Task]:
    """Набор назначателя: обычная открытая задача, заблокированная и с блокирующим вопросом.

    Ровно та расстановка, на которой проверяется обзорный запрос кандидатов: выдача
    обязана содержать только `plain`.
    """
    plain = await make(db_session, task_actor, queue, "обычная")
    plain = await open_task(db_session, task_actor, plain)
    blocked = await make(db_session, task_actor, queue, "заблокированная")
    blocker = await make(db_session, task_actor, queue, "блокер")
    await links_service.add_link(
        db_session, blocked, blocker, actor=task_actor, kind=LinkKind.BLOCKED_BY
    )
    blocked = await open_task(db_session, task_actor, blocked)
    asking = await make(db_session, task_actor, queue, "вопрос без ответа")
    asking = await open_task(db_session, task_actor, asking)
    await case_service.ask(
        db_session,
        asking,
        actor=task_actor,
        addressees=["owner"],
        title="Каким способом чинить?",
        blocking=True,
    )
    return {"plain": plain, "blocked": blocked, "blocker": blocker, "asking": asking}


# --- Два входа, один результат ----------------------------------------------------------


async def test_the_assignee_query_finds_exactly_the_tasks_that_can_be_taken(
    db_session: AsyncSession, task_actor: Actor, board: dict[str, Task]
) -> None:
    """Обзорная проверка 1: одна строка отбирает кандидатов назначателя.

    Заблокированная задача, задача с блокирующим вопросом и блокер в `backlog` из
    выдачи выпадают — каждая по своей причине.
    """
    found = await keys(
        db_session,
        task_actor,
        query="queue: TRK and status: open and blocked: false and open_blocking_questions: 0",
    )

    assert found == [board["plain"].key]


async def test_the_structured_filter_gives_the_same_list_in_the_same_order(
    db_session: AsyncSession, task_actor: Actor, board: dict[str, Task]
) -> None:
    """Обзорная проверка 2: тот же отбор структурными параметрами — тот же список."""
    by_query = await keys(
        db_session,
        task_actor,
        query="queue: TRK and status: open and blocked: false and open_blocking_questions: 0",
    )
    by_filter = await keys(
        db_session,
        task_actor,
        structured=[
            StructuredTerm(name="queue", values=["TRK"]),
            StructuredTerm(name="status", values=["open"]),
            StructuredTerm(name="blocked", values=[False]),
            StructuredTerm(name="open_blocking_questions", values=[0]),
        ],
    )

    assert by_query == by_filter


async def test_both_inputs_narrow_each_other_instead_of_replacing(
    db_session: AsyncSession, task_actor: Actor, board: dict[str, Task]
) -> None:
    """Источники складываются по `and`: строка не отменяет параметры и наоборот."""
    found = await keys(
        db_session,
        task_actor,
        query="status: open",
        structured=[StructuredTerm(name="blocked", values=[True])],
    )

    assert found == [board["blocked"].key]


async def test_waiting_is_selected_by_status_without_touching_the_search(
    db_session: AsyncSession, task_actor: Actor, queue: Queue, board: dict[str, Task]
) -> None:
    """Обзорная проверка 6: новый статус находится отбором, и поиск для этого не правился.

    Это главное свойство статуса: очередь ожидания человек получает списком, а не
    вычитыванием сводок. Поиск разбирает значение статуса перечислением `TaskStatus`,
    поэтому новый член работает сам — тест стережёт, что это так и осталось, и заодно
    что `waiting` не подмешивается в выдачу `status: open`.
    """
    parked = await make(db_session, task_actor, queue, "ждёт человека")
    parked = await open_task(db_session, task_actor, parked)
    await tasks_service.transition_task(
        db_session, parked, actor=task_actor, to=TaskStatus.WAITING, reason="Жду решения владельца"
    )

    assert await keys(db_session, task_actor, query="status: waiting") == [parked.key]
    assert parked.key not in await keys(db_session, task_actor, query="status: open")

    both = await keys(db_session, task_actor, query="status: in waiting, open")
    assert parked.key in both
    assert board["plain"].key in both

    # Структурный вход обязан находить то же самое: второй реализации отбора нет.
    assert await keys(
        db_session, task_actor, structured=[StructuredTerm(name="status", values=["waiting"])]
    ) == [parked.key]


async def test_waiting_does_not_touch_the_blocked_feature(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Признак `blocked` остался про `blocked_by` и нового смысла не приобрёл.

    Ожидание человека и блокировка задачей — разные вещи (`CONCEPT.md`, 4.6), и слить их
    в один признак значило бы потерять различие ровно там, где оно и нужно.
    """
    parked = await make(db_session, task_actor, queue, "ждёт человека")
    parked = await open_task(db_session, task_actor, parked)
    await tasks_service.transition_task(
        db_session, parked, actor=task_actor, to=TaskStatus.WAITING, reason="Жду доступ"
    )

    features = await found_features(db_session, task_actor, parked.key)
    assert features is not None
    assert features.blocked is False
    assert await keys(db_session, task_actor, query="blocked: true") == []


# --- Вычисляемые признаки ---------------------------------------------------------------


async def test_the_search_and_the_card_agree_on_every_computed_feature(
    db_session: AsyncSession, task_actor: Actor, board: dict[str, Task]
) -> None:
    """Признаки карточки и отбор поиска считаны разными путями и обязаны совпасть.

    Это и есть страховка от расхождения двух форм одного определения: пока проверка
    зелёная, `EXISTS` поиска и чистая функция карточки отвечают одинаково.
    """
    for task in board.values():
        package = await tasks_service.read_task_package(db_session, task.key, actor=task_actor)
        features = package.features

        assert await found_features(db_session, task_actor, task.key) == features
        assert task.key in await keys(
            db_session, task_actor, query=f"blocked: {str(features.blocked).lower()}"
        )
        assert task.key in await keys(
            db_session, task_actor, query=f"open_questions: {features.open_questions}"
        )
        assert task.key in await keys(
            db_session,
            task_actor,
            query=f"open_blocking_questions: {features.open_blocking_questions}",
        )


async def test_a_closed_blocker_stops_blocking(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Закрытый блокер связь не снимает, но признак опускает — как и в карточке."""
    task = await make(db_session, task_actor, queue, "зависимая")
    blocker = await make(db_session, task_actor, queue, "блокер")
    await links_service.add_link(
        db_session, task, blocker, actor=task_actor, kind=LinkKind.BLOCKED_BY
    )
    assert await keys(db_session, task_actor, query="blocked: true") == [task.key]

    await tasks_service.transition_task(
        db_session, blocker, actor=task_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )

    assert await keys(db_session, task_actor, query="blocked: true") == []
    assert task.key in await keys(db_session, task_actor, query="blocked: false")


async def test_an_answered_question_stops_being_counted(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Открытость вопроса считается запросом, а не колонкой: ответ закрывает его сразу."""
    task = await make(db_session, task_actor, queue, "вопрос без ответа")
    question = await case_service.ask(
        db_session, task, actor=task_actor, addressees=["owner"], title="Как быть?", blocking=True
    )
    assert await keys(db_session, task_actor, query="open_blocking_questions: > 0") == [task.key]

    await case_service.answer(db_session, task, actor=task_actor, question_no=question.no)

    assert await keys(db_session, task_actor, query="open_blocking_questions: > 0") == []


async def test_a_non_blocking_question_counts_only_in_the_wider_counter(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    task = await make(db_session, task_actor, queue, "вопрос без ответа")
    await case_service.ask(
        db_session, task, actor=task_actor, addressees=["owner"], title="Уточнение?", blocking=False
    )

    assert await keys(db_session, task_actor, query="open_questions: 1") == [task.key]
    assert await keys(db_session, task_actor, query="open_blocking_questions: 0") == [task.key]


# --- Поля отбора ------------------------------------------------------------------------


async def test_a_tag_is_found_among_several(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 7: метка находится в задаче с несколькими метками."""
    task = await make(
        db_session, task_actor, queue, "много меток", tags=["ui", "backend", "release"]
    )
    await make(db_session, task_actor, queue, "без меток")

    assert await keys(db_session, task_actor, query="tags: backend") == [task.key]


async def test_a_tag_is_matched_exactly_and_case_sensitively(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Регистр метки значим — это решение ради индекса, а не недоработка."""
    task = await make(db_session, task_actor, queue, "одна метка", tags=["Backend"])

    assert await keys(db_session, task_actor, query="tags: backend") == []
    assert await keys(db_session, task_actor, query="tags: ~ backend") == [task.key]
    assert await keys(db_session, task_actor, query="tags: Backend") == [task.key]


async def test_negation_keeps_the_tasks_without_a_value(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """«Все, кроме Алисы» обязано включать неназначенные: NULL не выпадает молча."""
    alice = await make(db_session, task_actor, queue, "задача Алисы", assignee="alice")
    bob = await make(db_session, task_actor, queue, "задача Боба", assignee="bob")
    nobody = await make(db_session, task_actor, queue, "ничей")

    found = await keys(db_session, task_actor, query="assignee: != alice")

    assert set(found) == {bob.key, nobody.key}
    assert alice.key not in found


async def test_empty_finds_the_tasks_without_a_value(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    await make(db_session, task_actor, queue, "задача Алисы", assignee="alice", tags=["ui"])
    nobody = await make(db_session, task_actor, queue, "ничей")

    assert await keys(db_session, task_actor, query="assignee: empty()") == [nobody.key]
    assert await keys(db_session, task_actor, query="tags: empty()") == [nobody.key]


async def test_empty_combines_with_values_by_or(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """`assignee: alice, empty()` — это «Алиса или никто», а не «Алиса и никто»."""
    alice = await make(db_session, task_actor, queue, "задача Алисы", assignee="alice")
    nobody = await make(db_session, task_actor, queue, "ничей")
    await make(db_session, task_actor, queue, "задача Боба", assignee="bob")

    found = await keys(db_session, task_actor, query="assignee: alice, empty()")

    assert set(found) == {alice.key, nobody.key}


async def test_text_looks_into_the_title_and_the_description(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    by_title = await make(db_session, task_actor, queue, "выдача ключей задач")
    by_description = await make(
        db_session, task_actor, queue, "другая", description="ключей не хватает"
    )
    await make(db_session, task_actor, queue, "совсем другая", description="ничего похожего")

    found = await keys(db_session, task_actor, query="text: ключей")

    assert set(found) == {by_title.key, by_description.key}


async def test_a_like_wildcard_in_the_value_is_escaped(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """`_` в запросе ищется как символ, а не как «любой»: экранирование одно на проект."""
    literal = await make(db_session, task_actor, queue, "сто_процентов")
    await make(db_session, task_actor, queue, "стоипроцентов")

    assert await keys(db_session, task_actor, query="text: сто_процентов") == [literal.key]


async def test_priority_compares_by_rank_and_not_by_alphabet(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    low = await make(db_session, task_actor, queue, "низкий", priority=TaskPriority.LOW)
    high = await make(db_session, task_actor, queue, "высокий", priority=TaskPriority.HIGH)
    critical = await make(db_session, task_actor, queue, "срочный", priority=TaskPriority.CRITICAL)

    found = await keys(db_session, task_actor, query="priority: >= high")

    assert set(found) == {high.key, critical.key}
    assert low.key not in found


# --- Порядок и курсор -------------------------------------------------------------------


async def test_the_default_order_puts_the_tenth_task_after_the_second(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Ключ сортируется числом, а не строкой: иначе `TRK-10` встал бы перед `TRK-2`."""
    made = [
        await make(db_session, task_actor, queue, f"задача {number}") for number in range(1, 12)
    ]

    found = await keys(db_session, task_actor, limit=200)

    assert found == [task.key for task in made]


async def test_an_insertion_between_pages_neither_duplicates_nor_loses_tasks(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 4: курсор задан значением ключа, а не смещением.

    Вставка идёт по возрастанию ключа, то есть **после** уже отданной страницы:
    смещение сдвинуло бы выдачу, а курсор — нет.
    """
    before = [await make(db_session, task_actor, queue, f"задача {number}") for number in range(6)]

    first = await service.search_tasks(db_session, actor=task_actor, limit=3)
    await make(db_session, task_actor, queue, "вставленная посреди обхода")
    second = await service.search_tasks(
        db_session, actor=task_actor, limit=3, cursor=first.page.next_cursor
    )

    seen = [found.task.key for found in first.page.items + second.page.items]
    assert seen == [task.key for task in before]
    assert len(seen) == len(set(seen))


async def test_paging_holds_whether_or_not_the_features_were_asked_for(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Курсор берёт из строки только значения ключей порядка, а признаки в него не попадают.

    Признаки — такие же колонки выдачи, как значения сортировки, и стоят в строке рядом с
    ними, но число их зависит от `fields`. Курсор, собранный «от первой колонки до конца
    строки», на выдаче с признаками молча уехал бы не туда: в него попали бы `blocked` и
    счётчики, а страница продолжилась бы с чужого места. Поэтому обход проверяется обоими
    наборами полей и обязан дать один и тот же список.
    """
    made = [await make(db_session, task_actor, queue, f"задача {number}") for number in range(5)]

    async def walk(fields: tuple[str, ...]) -> list[str]:
        """Полный обход по страницам в две задачи, от курсора к курсору."""
        seen: list[str] = []
        cursor: str | None = None
        while True:
            outcome = await service.search_tasks(
                db_session, actor=task_actor, fields=fields, limit=2, cursor=cursor
            )
            seen.extend(found.task.key for found in outcome.page.items)
            cursor = outcome.page.next_cursor
            if cursor is None:
                return seen

    with_features = await walk(())
    without_features = await walk(("title",))

    assert with_features == [task.key for task in made]
    assert without_features == with_features


async def test_sorting_by_update_time_descending_puts_the_latest_first(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Направление задаётся явно: `-updated_at` ставит свежее впереди.

    Время правится запросом, а не настоящим обновлением задачи: `now()` в PostgreSQL —
    время начала транзакции, а весь тест идёт в одной (`docs/notes/db.md`). Настоящая
    правка проставила бы всем задачам одно и то же время, и порядок решал бы тайбрейкер
    по случайному `id` — проверка стала бы непроходимой через раз.
    """
    first = await make(db_session, task_actor, queue, "первая")
    second = await make(db_session, task_actor, queue, "вторая")
    await db_session.execute(
        update(Task).where(Task.id == first.id).values(updated_at=text("now() + interval '1 hour'"))
    )

    assert await keys(db_session, task_actor, sort=["-updated_at"]) == [first.key, second.key]
    assert await keys(db_session, task_actor, sort=["updated_at"]) == [second.key, first.key]


async def test_a_cursor_from_another_order_is_refused(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Смена `sort` посреди обхода — не «начать сначала», а испорченный курсор."""
    for number in range(3):
        await make(db_session, task_actor, queue, f"задача {number}")
    page = await service.search_tasks(db_session, actor=task_actor, limit=1)

    with pytest.raises(Exception, match="cursor"):
        await service.search_tasks(
            db_session,
            actor=task_actor,
            sort=["priority"],
            limit=1,
            cursor=page.page.next_cursor,
        )


# --- Выбор полей ------------------------------------------------------------------------


async def test_selected_fields_always_include_the_key(
    db_session: AsyncSession, task_actor: Actor, task: Task
) -> None:
    outcome = await service.search_tasks(db_session, actor=task_actor, fields=["title", "status"])

    assert outcome.resolved.fields == ("key", "title", "status")


async def test_no_selection_means_the_whole_task(
    db_session: AsyncSession, task_actor: Actor, task: Task
) -> None:
    outcome = await service.search_tasks(db_session, actor=task_actor)

    assert outcome.resolved.fields == ()


# --- Отказы -----------------------------------------------------------------------------


async def test_an_unknown_field_lists_the_allowed_ones(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    """Обзорная проверка 6: `deadline: today` отвечает перечнем допустимых полей."""
    with pytest.raises(SearchFieldUnknownError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="deadline: today")

    assert raised.value.details["field"] == "deadline"
    assert "queue" in raised.value.details["allowed"]
    assert raised.value.details["position"] == 0


async def test_an_unknown_status_lists_the_allowed_values(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    """Обзорная проверка 3: опечатка в значении — позиция и список допустимых."""
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="status: opne")

    assert raised.value.details["position"] == 8
    assert raised.value.details["value"] == "opne"
    assert "open" in raised.value.details["allowed"]


async def test_an_unknown_queue_is_a_wrong_value_and_not_an_empty_answer(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    """Опечатка в ключе очереди обязана назваться, а не дать пустую выдачу."""
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="queue: TKR")

    assert raised.value.details["reason"] == "queue_not_found"


async def test_an_operator_the_field_does_not_support_is_refused(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    with pytest.raises(SearchOperatorNotSupportedError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="status: > open")

    assert raised.value.details["operator"] == ">"
    assert "=" in raised.value.details["allowed"]


async def test_empty_is_refused_where_a_value_always_exists(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="queue: empty()")

    assert raised.value.details["reason"] == "empty_not_supported"


async def test_an_order_comparison_takes_a_single_value(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="priority: > high, low")

    assert raised.value.details["reason"] == "single_value_required"


async def test_an_unknown_sort_key_lists_the_allowed_ones(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    with pytest.raises(SearchFieldUnknownError) as raised:
        await service.search_tasks(db_session, actor=task_actor, sort=["created_at"])

    assert raised.value.details["reason"] == "not_sortable"
    assert raised.value.details["allowed"] == ["key", "last_entry_at", "priority", "updated_at"]


async def test_an_unselectable_field_is_refused(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    with pytest.raises(SearchFieldUnknownError) as raised:
        await service.search_tasks(db_session, actor=task_actor, fields=["blocked"])

    assert raised.value.details["reason"] == "not_selectable"


async def test_an_empty_value_points_at_the_marker_instead(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    """Пустая строка — не `empty()`: молча искать по ней значило бы отдавать не то."""
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query='assignee: ""')

    assert raised.value.details["reason"] == "empty_value"
    assert "empty()" in raised.value.details["hint"]


# --- Очередь как условие ----------------------------------------------------------------


async def test_a_queue_narrows_the_answer_to_its_own_tasks(
    db_session: AsyncSession, main_actor: Actor, task_actor: Actor, queue: Queue
) -> None:
    other = await queues_service.create_queue(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация", description="вторая очередь"
    )
    mine = await make(db_session, task_actor, queue, "своя")
    theirs = await make(db_session, task_actor, other, "чужая")

    assert await keys(db_session, task_actor, query="queue: TRK") == [mine.key]
    assert await keys(db_session, task_actor, query="queue: ops") == [theirs.key]
