"""Сценарий отбора задач: два входа с одним результатом, вычисляемые признаки, курсор.

Главная проверка набора — не «фильтр находит задачу», а «строка и структурный фильтр
находят одно и то же в одном порядке» и «признак в карточке совпадает с отбором». Оба
свойства держатся на том, что второй реализации нет; тесты стерегут это на данных.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.link import Link
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.pagination import CursorWithOffsetError, InvalidPageOffsetError
from app.domain.errors import (
    SearchFieldUnknownError,
    SearchOperatorNotSupportedError,
    SearchValueInvalidError,
)
from app.domain.links import LinkKind
from app.domain.query_language import QUERY_RIGHT_SHAPE
from app.domain.search import MAX_VALUES_PER_CONDITION, Operator
from app.domain.tasks import AskedParent, TaskFeatures, TaskParent, TaskPriority, TaskStatus
from app.services import case as case_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import search as service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.search import StructuredTerm


async def make(
    session: AsyncSession,
    actor: Actor,
    project: Project,
    title: str,
    *,
    description: str = "описание",
    assignee: str | None = None,
    priority: TaskPriority = TaskPriority.NORMAL,
) -> Task:
    """Задача в `backlog` с заполненными разделами: готова идти по цепочке статусов."""
    return await tasks_service.create_task(
        session,
        actor=actor,
        project=project,
        title=title,
        description=description,
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
        assignee=assignee,
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
async def board(db_session: AsyncSession, task_actor: Actor, project: Project) -> dict[str, Task]:
    """Набор назначателя: обычная открытая задача, заблокированная и с блокирующим вопросом.

    Ровно та расстановка, на которой проверяется обзорный запрос кандидатов: выдача
    обязана содержать только `plain`.
    """
    plain = await make(db_session, task_actor, project, "обычная")
    plain = await open_task(db_session, task_actor, plain)
    blocked = await make(db_session, task_actor, project, "заблокированная")
    blocker = await make(db_session, task_actor, project, "блокер")
    await links_service.add_link(
        db_session, blocked, blocker, actor=task_actor, kind=LinkKind.BLOCKED_BY
    )
    blocked = await open_task(db_session, task_actor, blocked)
    asking = await make(db_session, task_actor, project, "вопрос без ответа")
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
        query="project: TRK and status: open and blocked: false and open_blocking_questions: 0",
    )

    assert found == [board["plain"].key]


async def test_the_structured_filter_gives_the_same_list_in_the_same_order(
    db_session: AsyncSession, task_actor: Actor, board: dict[str, Task]
) -> None:
    """Обзорная проверка 2: тот же отбор структурными параметрами — тот же список."""
    by_query = await keys(
        db_session,
        task_actor,
        query="project: TRK and status: open and blocked: false and open_blocking_questions: 0",
    )
    by_filter = await keys(
        db_session,
        task_actor,
        structured=[
            StructuredTerm(name="project", values=["TRK"]),
            StructuredTerm(name="status", values=["open"]),
            StructuredTerm(name="blocked", values=[False]),
            StructuredTerm(name="open_blocking_questions", values=[0]),
        ],
    )

    assert by_query == by_filter


async def test_a_structured_value_with_a_space_is_one_value_and_not_a_parse_error(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Обзорная проверка 1 TRK-21: `text=выдача ключей` ищет, а не отказывает.

    Границы значения у структурного параметра задал протокол, и разбирать его правилами
    языка значило требовать кавычек там, где они уже не нужны. Так и было: до этой
    правки такой отбор отвечал `invalid_search_query` на втором слове — а с ним
    отказывало и поле «Текст» в интерфейсе, где никакого запроса человек не писал.
    """
    task = await make(db_session, task_actor, project, "Ключ задачи сгорает на выдача ключей")
    await make(db_session, task_actor, project, "Другая задача про выдачу")

    by_filter = await keys(
        db_session,
        task_actor,
        structured=[
            StructuredTerm(name="text", values=["выдача ключей"], operator=Operator.CONTAINS)
        ],
    )

    assert by_filter == [task.key]

    # Тот же вопрос строкой языка — с кавычками, потому что там границы задаёт синтаксис.
    by_query = await keys(db_session, task_actor, query='text: ~ "выдача ключей"')
    assert by_query == by_filter


async def test_a_free_string_field_takes_a_space_too(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Не только `text`: исполнитель — свободная строка, и пробел в ней законен."""
    task = await make(db_session, task_actor, project, "чужая работа", assignee="release bot")
    await make(db_session, task_actor, project, "своя работа", assignee="release_bot")

    by_filter = await keys(
        db_session, task_actor, structured=[StructuredTerm(name="assignee", values=["release bot"])]
    )
    by_query = await keys(db_session, task_actor, query='assignee: "release bot"')

    assert by_filter == [task.key]
    assert by_query == by_filter


async def test_a_quote_inside_a_structured_value_is_searched_literally(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Кавычки — часть значения, а не его границы: разбирать структурный ввод нечем.

    Дописать кавычки вокруг значения было бы вторым способом сломать то же самое:
    значение с настоящей кавычкой внутри тогда разобралось бы неверно.
    """
    task = await make(db_session, task_actor, project, 'он сказал "нет" и ушёл')
    await make(db_session, task_actor, project, "он сказал нет и ушёл")

    found = await keys(
        db_session,
        task_actor,
        structured=[
            StructuredTerm(name="text", values=['сказал "нет"'], operator=Operator.CONTAINS)
        ],
    )

    assert found == [task.key]


async def test_empty_still_means_no_value_on_both_inputs(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """`empty()` остаётся маркером, а не подстрокой: иначе правка сломала бы «без исполнителя».

    Маркер разбирается парсером языка, а не сравнением строк, — потому и совпадает
    с языком буква в букву, включая регистр и пробел перед скобками.
    """
    await make(db_session, task_actor, project, "задача Алисы", assignee="alice")
    nobody = await make(db_session, task_actor, project, "ничей")

    by_filter = await keys(
        db_session, task_actor, structured=[StructuredTerm(name="assignee", values=["empty()"])]
    )
    by_query = await keys(db_session, task_actor, query="assignee: empty()")

    assert by_filter == [nobody.key]
    assert by_query == by_filter


async def test_the_shape_from_the_hint_finds_what_the_structured_filter_finds(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Обзорная проверка 2 TRK-13: подсказка чинит запрос, а не просто утешает.

    Агент пишет `status in (open, in_progress)` — форму из SQL, — получает отказ с верной
    формой в `details.hint`, подставляет свои значения и повторяет. Здесь проверяется
    последний шаг: починенный запрос находит ровно то же, что структурный отбор по двум
    статусам. Без этого подсказка была бы обещанием, которое никто не проверял.
    """
    backlog = await make(db_session, task_actor, project, "черновик")
    opened = await open_task(
        db_session, task_actor, await make(db_session, task_actor, project, "открытая")
    )
    working = await make(
        db_session, task_actor, project, "в работе", assignee=task_actor.author.signature
    )
    working = await open_task(db_session, task_actor, working)
    working = (
        await tasks_service.transition_task(
            db_session, working, actor=task_actor, to=TaskStatus.IN_PROGRESS
        )
    ).task

    by_query = await keys(db_session, task_actor, query=QUERY_RIGHT_SHAPE)
    by_filter = await keys(
        db_session,
        task_actor,
        structured=[StructuredTerm(name="status", values=["open", "in_progress"])],
    )

    assert by_query == by_filter
    assert set(by_query) == {opened.key, working.key}
    assert backlog.key not in by_query


@pytest.fixture
async def family(db_session: AsyncSession, task_actor: Actor, project: Project) -> dict[str, Task]:
    """Программа с тремя детьми: один открыт, два закрыты. Плюс чужая задача рядом.

    Ровно та расстановка, на которой стоит вопрос «можно ли закрывать программу»:
    закрытых больше, открытый один, и посторонняя задача обязана в выдачу не попасть.
    """
    program = await make(db_session, task_actor, project, "программа")
    program = await open_task(db_session, task_actor, program)

    children: dict[str, Task] = {}
    for name in ("живой", "первый закрытый", "второй закрытый"):
        child = await make(db_session, task_actor, project, name)
        await links_service.add_link(
            db_session, child, program, actor=task_actor, kind=LinkKind.CHILD
        )
        children[name] = await open_task(db_session, task_actor, child)

    for name in ("первый закрытый", "второй закрытый"):
        children[name] = (
            await tasks_service.transition_task(
                db_session, children[name], actor=task_actor, to=TaskStatus.CANCELLED, reason="не"
            )
        ).task

    return {
        "program": program,
        "outsider": await make(db_session, task_actor, project, "чужая"),
        **children,
    }


async def test_children_are_selected_by_the_parent_field(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """Обзорная проверка 2: «что у детей этой задачи» — один отбор, а не чтение карточки.

    И он складывается с остальными условиями языка: «открытые дети» — это то же поле
    плюс `status`, а не отдельный вопрос и не отдельный инструмент.
    """
    program = family["program"].key

    all_children = await keys(db_session, task_actor, query=f"parent: {program}")
    assert set(all_children) == {
        family["живой"].key,
        family["первый закрытый"].key,
        family["второй закрытый"].key,
    }
    assert program not in all_children, "родитель не попадает в список собственных детей"
    assert family["outsider"].key not in all_children

    alive = await keys(db_session, task_actor, query=f"parent: {program} and status: open")
    assert alive == [family["живой"].key]

    # Структурный параметр отвечает тем же самым — иначе у одного вопроса было бы два
    # ответа в зависимости от того, как его задали.
    by_filter = await keys(
        db_session, task_actor, structured=[StructuredTerm(name="parent", values=[program])]
    )
    assert sorted(by_filter) == sorted(all_children)

    by_filter_alive = await keys(
        db_session,
        task_actor,
        structured=[
            StructuredTerm(name="parent", values=[program]),
            StructuredTerm(name="status", values=["open"]),
        ],
    )
    assert by_filter_alive == alive


async def test_parent_empty_gives_the_top_level_of_the_project(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """Обзорная проверка 3: `parent: empty()` — верхний уровень, и ни одного ребёнка.

    Это то, что человек и агент смотрят первым: список программ, а не всё вперемешку.
    """
    found = await keys(db_session, task_actor, query="parent: empty()")

    assert set(found) == {family["program"].key, family["outsider"].key}
    for name in ("живой", "первый закрытый", "второй закрытый"):
        assert family[name].key not in found


async def test_an_unknown_parent_key_is_refused_and_named(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Обзорная проверка 4: опечатка в ключе — отказ с ключом, а не пустая выдача.

    Пустота на этот вопрос читается как «детей нет» — то есть как ответ. На таком
    ответе программу закрывают, поэтому промах обязан быть назван.
    """
    del project
    with pytest.raises(SearchValueInvalidError) as error:
        await keys(db_session, task_actor, query="parent: TRK-404")

    details = error.value.details
    assert details["field"] == "parent"
    assert details["value"] == "TRK-404"
    assert details["reason"] == "task_not_found"


# --- Родители в строке выдачи ----------------------------------------------------------


async def test_a_row_names_its_direct_parent_by_key_and_title(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """TRK-95, TRK-135: ребёнок называет родителя ключом и названием, верхний уровень — никого.

    `AskedParent(None)` у верхнего уровня — ответ «родителя нет», а не «его не считали»:
    тот ответ — `None`, и его дают только выдачи, где поле не просили.
    """
    program = family["program"]
    outcome = await service.search_tasks(db_session, actor=task_actor)
    rows = {found.task.key: found.parent for found in outcome.page.items}

    for name in ("живой", "первый закрытый", "второй закрытый"):
        assert rows[family[name].key] == AskedParent(
            TaskParent(key=program.key, title=program.title)
        )
    assert rows[program.key] == AskedParent(None)
    assert rows[family["outsider"].key] == AskedParent(None)


async def test_a_row_names_the_direct_parent_and_not_the_grandparent(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Родство прямое, как у отбора `parent:`: цепочки предков в строке нет (`CONCEPT.md`, 4.4)."""
    program = await make(db_session, task_actor, project, "программа")
    child = await make(db_session, task_actor, project, "ребёнок")
    grandchild = await make(db_session, task_actor, project, "внук")
    await links_service.add_link(db_session, program, child, actor=task_actor, kind=LinkKind.PARENT)
    await links_service.add_link(
        db_session, grandchild, child, actor=task_actor, kind=LinkKind.CHILD
    )

    outcome = await service.search_tasks(db_session, actor=task_actor)
    rows = {found.task.key: found.parent for found in outcome.page.items}

    assert rows[grandchild.key] == AskedParent(TaskParent(key=child.key, title=child.title))
    assert rows[child.key] == AskedParent(TaskParent(key=program.key, title=program.title))


async def test_a_task_with_two_parents_from_older_data_shows_the_first_one(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Данные старше запрета (TRK-135): второй родитель мог появиться до него, и строка
    называет первого по времени связи — того же, что и карточка.

    Сценарий второго родителя уже не поставит (`task_has_parent`), поэтому вторая связь
    кладётся прямо в таблицу — так, как она лежит в базе, заведённой раньше. «Первый» —
    по появлению связи, а не по ключу: родитель с меньшим ключом связан позже. Время
    связей задано явно — в одной транзакции `now()` у обеих одно и то же, и выбор решал
    бы случайный `id`.
    """
    linked_later = await make(db_session, task_actor, project, "связан вторым")
    linked_first = await make(db_session, task_actor, project, "связан первым")
    child = await make(db_session, task_actor, project, "ребёнок двух программ")
    await links_service.add_link(
        db_session, linked_first, child, actor=task_actor, kind=LinkKind.PARENT
    )
    db_session.add(
        Link(
            source=linked_later,
            target=child,
            kind=LinkKind.PARENT,
            **created_by_columns(task_actor.author),
        )
    )
    await db_session.flush()
    for parent, moment in ((linked_first, 1), (linked_later, 2)):
        await db_session.execute(
            update(Link)
            .where(Link.source_id == parent.id, Link.target_id == child.id)
            .values(created_at=datetime(2026, 9, moment, tzinfo=UTC))
        )
    assert linked_later.key < linked_first.key, "порядок ключей обязан отличаться от порядка связей"

    outcome = await service.search_tasks(db_session, actor=task_actor, query=f"key: {child.key}")

    assert outcome.page.items[0].parent == AskedParent(
        TaskParent(key=linked_first.key, title=linked_first.title)
    )
    package = await tasks_service.read_task_package(db_session, child.key, actor=task_actor)
    assert package.parent is not None
    assert package.parent.other.key == linked_first.key


async def test_parents_are_not_selected_when_the_fields_leave_them_out(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """`fields` без `parent` — прямая просьба не платить за подзапрос, как у признаков."""
    narrow = await service.search_tasks(db_session, actor=task_actor, fields=["title"])
    assert narrow.page.items
    assert all(found.parent is None for found in narrow.page.items)

    asked = await service.search_tasks(db_session, actor=task_actor, fields=["parent"])
    rows = {found.task.key: found.parent for found in asked.page.items}
    assert rows[family["живой"].key] == AskedParent(
        TaskParent(key=family["program"].key, title=family["program"].title)
    )
    assert all(found.features is None for found in asked.page.items)


async def _page_selects(session: AsyncSession, actor: Actor, **call: Any) -> tuple[int, int]:
    """Сколько `SELECT` ушло на страницу поиска и сколько строк в ней пришло с родителем.

    Запросы считаются событием SQLAlchemy на соединении, как у `last_entry_at`
    (`tests/test_last_entry_at.py`): запрос на строку не виден ни по ответу, ни по времени
    на малых данных — только по числу.
    """
    statements: list[str] = []
    connection = await session.connection()

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(connection.sync_connection.engine, "before_cursor_execute", record)
    try:
        outcome = await service.search_tasks(session, actor=actor, **call)
    finally:
        event.remove(connection.sync_connection.engine, "before_cursor_execute", record)

    with_parents = sum(
        1 for found in outcome.page.items if found.parent is not None and found.parent.value
    )
    selects = [item for item in statements if item.lstrip().upper().startswith("SELECT")]
    return len(selects), with_parents


async def test_a_page_with_parents_costs_the_same_queries_whatever_its_size(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """TRK-95, проверка 4: родители страницы выбираются тем же запросом, что и страница.

    Страница из одной строки и из пятидесяти стоят одинаково. Без отбора это ровно один
    `SELECT`; отбор `parent:` добавляет постоянный запрос — ключ родителя разрешается в
    задачу, — и от размера страницы он тоже не зависит.
    """
    program = await make(db_session, task_actor, project, "программа")
    other_program = await make(db_session, task_actor, project, "вторая программа")
    for index in range(60):
        child = await make(db_session, task_actor, project, f"ребёнок {index}")
        await links_service.add_link(
            db_session, program, child, actor=task_actor, kind=LinkKind.PARENT
        )
        if index % 2:
            # Второй родитель — из данных старше запрета (TRK-135): сценарий его уже не
            # поставит, а подзапрос родителей обязан стоить столько же и с ним.
            db_session.add(
                Link(
                    source=other_program,
                    target=child,
                    kind=LinkKind.PARENT,
                    **created_by_columns(task_actor.author),
                )
            )
            await db_session.flush()

    assert await _page_selects(db_session, task_actor, limit=1) == (1, 0)
    assert await _page_selects(db_session, task_actor, limit=50) == (1, 48)

    by_parent = f"parent: {program.key}"
    one = await _page_selects(db_session, task_actor, query=by_parent, limit=1)
    fifty = await _page_selects(db_session, task_actor, query=by_parent, limit=50)
    assert one == (fifty[0], 1)
    assert fifty[1] == 50


# --- Ключ задачи ---------------------------------------------------------------------


async def test_several_named_tasks_are_asked_about_in_one_request(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """Обзорная проверка 1: `key: in A, B` отдаёт ровно названные задачи.

    Ради этого поле и заведено: сессия ведёт несколько дел и обязана спросить про них
    одним запросом, а не тянуть очередь по статусу и отбирать глазами.
    """
    first = family["живой"].key
    second = family["первый закрытый"].key

    by_query = await keys(db_session, task_actor, query=f"key: in {first}, {second}")
    assert sorted(by_query) == sorted([first, second])

    # Без оператора несколько значений означают то же самое вхождение в набор.
    assert sorted(await keys(db_session, task_actor, query=f"key: {first}, {second}")) == sorted(
        [first, second]
    )

    # Структурный параметр отвечает тем же самым: у одного вопроса не бывает двух
    # ответов в зависимости от того, как его задали.
    by_filter = await keys(
        db_session, task_actor, structured=[StructuredTerm(name="key", values=[first, second])]
    )
    assert sorted(by_filter) == sorted(by_query)


async def test_a_single_key_and_a_negated_key_pick_and_drop_one_task(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """Обзорная проверка 1: `key: A` берёт одну задачу, `key: != A` исключает её одну."""
    alive = family["живой"].key

    assert await keys(db_session, task_actor, query=f"key: {alive}") == [alive]

    everything = await keys(db_session, task_actor)
    without = await keys(db_session, task_actor, query=f"key: != {alive}")

    assert alive not in without
    assert sorted(without) == sorted(key for key in everything if key != alive)


async def test_the_key_field_narrows_together_with_the_rest(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """Ключ — обычное условие: складывается с остальными по «и», а не отменяет их."""
    alive = family["живой"].key
    cancelled = family["первый закрытый"].key

    found = await keys(
        db_session, task_actor, query=f"key: in {alive}, {cancelled} and status: open"
    )

    assert found == [alive]


async def test_an_unknown_key_is_refused_rather_than_answered_with_an_empty_page(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Обзорная проверка 1: несуществующий ключ — отказ, а не пустота.

    Довод тот же, что у родителя, и здесь он сильнее: пустая выдача на вопрос «что
    сейчас с этими задачами» читается как «по ним ничего», и опечатка спряталась бы за
    ответом, который выглядит осмысленным.
    """
    del project
    with pytest.raises(SearchValueInvalidError) as error:
        await keys(db_session, task_actor, query="key: TRK-404")

    details = error.value.details
    assert details["field"] == "key"
    assert details["value"] == "TRK-404"
    assert details["reason"] == "task_not_found"


async def test_a_key_has_no_empty_state_and_the_marker_is_refused(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """`key: empty()` — непонимание модели: ключ есть у каждой задачи."""
    del project
    with pytest.raises(SearchValueInvalidError) as error:
        await keys(db_session, task_actor, query="key: empty()")

    assert error.value.details["reason"] == "empty_not_supported"


async def test_a_structured_filter_refuses_more_values_than_the_ceiling(
    db_session: AsyncSession, task_actor: Actor, family: dict[str, Task]
) -> None:
    """Потолок значений действует и на структурный фильтр, а не только на язык.

    Строку разбирает парсер и отказывает сам; структурный фильтр приезжает мимо него, и
    без этой проверки список в тысячу ключей ушёл бы в запрос целиком. Отказ называет и
    потолок, и присланное число — усечение молча дало бы выдачу без части спрошенных
    задач.
    """
    alive = family["живой"].key
    with pytest.raises(SearchValueInvalidError) as error:
        await keys(
            db_session,
            task_actor,
            structured=[
                StructuredTerm(name="key", values=[alive] * (MAX_VALUES_PER_CONDITION + 1))
            ],
        )

    details = error.value.details
    assert details["reason"] == "too_many_values"
    assert details["max"] == MAX_VALUES_PER_CONDITION
    assert details["got"] == MAX_VALUES_PER_CONDITION + 1


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
    db_session: AsyncSession, task_actor: Actor, project: Project, board: dict[str, Task]
) -> None:
    """Обзорная проверка 6: новый статус находится отбором, и поиск для этого не правился.

    Это главное свойство статуса: очередь ожидания человек получает списком, а не
    вычитыванием сводок. Поиск разбирает значение статуса перечислением `TaskStatus`,
    поэтому новый член работает сам — тест стережёт, что это так и осталось, и заодно
    что `waiting` не подмешивается в выдачу `status: open`.
    """
    parked = await make(db_session, task_actor, project, "ждёт человека")
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
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Признак `blocked` остался про `blocked_by` и нового смысла не приобрёл.

    Ожидание человека и блокировка задачей — разные вещи (`CONCEPT.md`, 4.6), и слить их
    в один признак значило бы потерять различие ровно там, где оно и нужно.
    """
    parked = await make(db_session, task_actor, project, "ждёт человека")
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
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Закрытый блокер связь не снимает, но признак опускает — как и в карточке."""
    task = await make(db_session, task_actor, project, "зависимая")
    blocker = await make(db_session, task_actor, project, "блокер")
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
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Открытость вопроса считается запросом, а не колонкой: ответ закрывает его сразу."""
    task = await make(db_session, task_actor, project, "вопрос без ответа")
    question = await case_service.ask(
        db_session, task, actor=task_actor, addressees=["owner"], title="Как быть?", blocking=True
    )
    assert await keys(db_session, task_actor, query="open_blocking_questions: > 0") == [task.key]

    await case_service.answer(db_session, task, actor=task_actor, question_no=question.no)

    assert await keys(db_session, task_actor, query="open_blocking_questions: > 0") == []


async def test_a_non_blocking_question_counts_only_in_the_wider_counter(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    task = await make(db_session, task_actor, project, "вопрос без ответа")
    await case_service.ask(
        db_session, task, actor=task_actor, addressees=["owner"], title="Уточнение?", blocking=False
    )

    assert await keys(db_session, task_actor, query="open_questions: 1") == [task.key]
    assert await keys(db_session, task_actor, query="open_blocking_questions: 0") == [task.key]


# --- Поля отбора ------------------------------------------------------------------------


async def test_negation_keeps_the_tasks_without_a_value(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """«Все, кроме Алисы» обязано включать неназначенные: NULL не выпадает молча."""
    alice = await make(db_session, task_actor, project, "задача Алисы", assignee="alice")
    bob = await make(db_session, task_actor, project, "задача Боба", assignee="bob")
    nobody = await make(db_session, task_actor, project, "ничей")

    found = await keys(db_session, task_actor, query="assignee: != alice")

    assert set(found) == {bob.key, nobody.key}
    assert alice.key not in found


async def test_empty_finds_the_tasks_without_a_value(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    await make(db_session, task_actor, project, "задача Алисы", assignee="alice")
    nobody = await make(db_session, task_actor, project, "ничей")

    assert await keys(db_session, task_actor, query="assignee: empty()") == [nobody.key]


async def test_empty_combines_with_values_by_or(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """`assignee: alice, empty()` — это «Алиса или никто», а не «Алиса и никто»."""
    alice = await make(db_session, task_actor, project, "задача Алисы", assignee="alice")
    nobody = await make(db_session, task_actor, project, "ничей")
    await make(db_session, task_actor, project, "задача Боба", assignee="bob")

    found = await keys(db_session, task_actor, query="assignee: alice, empty()")

    assert set(found) == {alice.key, nobody.key}


async def test_text_looks_into_the_title_and_the_description(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    by_title = await make(db_session, task_actor, project, "выдача ключей задач")
    by_description = await make(
        db_session, task_actor, project, "другая", description="ключей не хватает"
    )
    await make(db_session, task_actor, project, "совсем другая", description="ничего похожего")

    found = await keys(db_session, task_actor, query="text: ключей")

    assert set(found) == {by_title.key, by_description.key}


async def test_a_like_wildcard_in_the_value_is_escaped(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """`_` в запросе ищется как символ, а не как «любой»: экранирование одно на проект."""
    literal = await make(db_session, task_actor, project, "сто_процентов")
    await make(db_session, task_actor, project, "стоипроцентов")

    assert await keys(db_session, task_actor, query="text: сто_процентов") == [literal.key]


async def test_priority_compares_by_rank_and_not_by_alphabet(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    low = await make(db_session, task_actor, project, "низкий", priority=TaskPriority.LOW)
    high = await make(db_session, task_actor, project, "высокий", priority=TaskPriority.HIGH)
    critical = await make(
        db_session, task_actor, project, "срочный", priority=TaskPriority.CRITICAL
    )

    found = await keys(db_session, task_actor, query="priority: >= high")

    assert set(found) == {high.key, critical.key}
    assert low.key not in found


# --- Порядок и курсор -------------------------------------------------------------------


async def test_the_default_order_puts_the_tenth_task_after_the_second(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Ключ сортируется числом, а не строкой: иначе `TRK-10` встал бы перед `TRK-2`."""
    made = [
        await make(db_session, task_actor, project, f"задача {number}") for number in range(1, 12)
    ]

    found = await keys(db_session, task_actor, limit=200)

    assert found == [task.key for task in made]


async def test_an_insertion_between_pages_neither_duplicates_nor_loses_tasks(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Обзорная проверка 4: курсор задан значением ключа, а не смещением.

    Вставка идёт по возрастанию ключа, то есть **после** уже отданной страницы:
    смещение сдвинуло бы выдачу, а курсор — нет.
    """
    before = [
        await make(db_session, task_actor, project, f"задача {number}") for number in range(6)
    ]

    first = await service.search_tasks(db_session, actor=task_actor, limit=3)
    await make(db_session, task_actor, project, "вставленная посреди обхода")
    second = await service.search_tasks(
        db_session, actor=task_actor, limit=3, cursor=first.page.next_cursor
    )

    seen = [found.task.key for found in first.page.items + second.page.items]
    assert seen == [task.key for task in before]
    assert len(seen) == len(set(seen))


async def test_paging_holds_whether_or_not_the_features_were_asked_for(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Курсор берёт из строки только значения ключей порядка, а признаки в него не попадают.

    Признаки — такие же колонки выдачи, как значения сортировки, и стоят в строке рядом с
    ними, но число их зависит от `fields`. Курсор, собранный «от первой колонки до конца
    строки», на выдаче с признаками молча уехал бы не туда: в него попали бы `blocked` и
    счётчики, а страница продолжилась бы с чужого места. Поэтому обход проверяется обоими
    наборами полей и обязан дать один и тот же список.
    """
    made = [await make(db_session, task_actor, project, f"задача {number}") for number in range(5)]

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
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Направление задаётся явно: `-updated_at` ставит свежее впереди.

    Время правится запросом, а не настоящим обновлением задачи: `now()` в PostgreSQL —
    время начала транзакции, а весь тест идёт в одной (`docs/notes/db.md`). Настоящая
    правка проставила бы всем задачам одно и то же время, и порядок решал бы тайбрейкер
    по случайному `id` — проверка стала бы непроходимой через раз.
    """
    first = await make(db_session, task_actor, project, "первая")
    second = await make(db_session, task_actor, project, "вторая")
    await db_session.execute(
        update(Task).where(Task.id == first.id).values(updated_at=text("now() + interval '1 hour'"))
    )

    assert await keys(db_session, task_actor, sort=["-updated_at"]) == [first.key, second.key]
    assert await keys(db_session, task_actor, sort=["updated_at"]) == [second.key, first.key]


async def test_a_cursor_from_another_order_is_refused(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Смена `sort` посреди обхода — не «начать сначала», а испорченный курсор."""
    for number in range(3):
        await make(db_session, task_actor, project, f"задача {number}")
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
    assert "project" in raised.value.details["allowed"]
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


async def test_an_unknown_project_is_a_wrong_value_and_not_an_empty_answer(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    """Опечатка в ключе проекта обязана назваться, а не дать пустую выдачу."""
    with pytest.raises(SearchValueInvalidError) as raised:
        await service.search_tasks(db_session, actor=task_actor, query="project: TKR")

    assert raised.value.details["reason"] == "project_not_found"


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
        await service.search_tasks(db_session, actor=task_actor, query="project: empty()")

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


# --- Проект как условие ----------------------------------------------------------------


async def test_a_project_narrows_the_answer_to_its_own_tasks(
    db_session: AsyncSession, main_actor: Actor, task_actor: Actor, project: Project
) -> None:
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация", description="второй проект"
    )
    mine = await make(db_session, task_actor, project, "своя")
    theirs = await make(db_session, task_actor, other, "чужая")

    assert await keys(db_session, task_actor, query="project: TRK") == [mine.key]
    assert await keys(db_session, task_actor, query="project: ops") == [theirs.key]


# --- Общее число выдачи и адрес страницы -------------------------------------------------


async def test_the_total_is_not_counted_unless_it_was_asked_for(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Подсчёт — второй запрос, и по умолчанию его нет: агент за него не платит.

    `None` здесь означает «не считали», а не «ноль»: обход выдачи курсором работает без
    подсчёта, и инструмент MCP просит страницу ровно так же, как до задачи TRK-41.
    """
    for number in range(5):
        await make(db_session, task_actor, project, f"задача {number}")

    silent = await service.search_tasks(db_session, actor=task_actor, limit=2)
    counted = await service.search_tasks(db_session, actor=task_actor, limit=2, with_total=True)

    assert silent.page.total is None
    assert counted.page.total == 5
    assert [found.task.key for found in silent.page.items] == [
        found.task.key for found in counted.page.items
    ]


async def test_the_total_counts_the_filtered_selection_in_any_order(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Число зависит от отбора и не зависит от порядка: сортировка строк не добавляет."""
    for number in range(4):
        task = await make(db_session, task_actor, project, f"задача {number}")
        if number % 2:
            await open_task(db_session, task_actor, task)

    for sort in ((), ("-updated_at",), ("priority",), ("key",)):
        outcome = await service.search_tasks(
            db_session,
            actor=task_actor,
            structured=[StructuredTerm(name="status", values=[TaskStatus.OPEN])],
            sort=sort,
            limit=1,
            with_total=True,
        )

        assert outcome.page.total == 2, sort
        assert len(outcome.page.items) == 1, sort


async def test_the_offset_lands_on_the_same_rows_the_walk_reaches(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Смещение — второй адрес той же страницы: порядок один, отбор один, строки те же."""
    made = [await make(db_session, task_actor, project, f"задача {number}") for number in range(7)]

    outcome = await service.search_tasks(db_session, actor=task_actor, limit=3, offset=3)

    assert [found.task.key for found in outcome.page.items] == [task.key for task in made[3:6]]
    assert outcome.page.next_cursor is not None


async def test_a_cursor_and_an_offset_together_are_refused_in_the_scenario(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Отказ живёт в пагинации, а не в параметре запроса: MCP идёт мимо схем FastAPI."""
    for number in range(4):
        await make(db_session, task_actor, project, f"задача {number}")
    first = await service.search_tasks(db_session, actor=task_actor, limit=2)

    with pytest.raises(CursorWithOffsetError) as raised:
        await service.search_tasks(
            db_session, actor=task_actor, limit=2, offset=2, cursor=first.page.next_cursor
        )

    assert raised.value.code == "cursor_with_offset"
    assert raised.value.details["offset"] == 2


async def test_a_negative_offset_is_refused_in_the_scenario_too(
    db_session: AsyncSession, task_actor: Actor
) -> None:
    """Границы смещения проверяются и здесь — по той же причине, что и границы `limit`."""
    with pytest.raises(InvalidPageOffsetError) as raised:
        await service.search_tasks(db_session, actor=task_actor, offset=-1)

    assert raised.value.details == {"offset": -1, "min": 0}
