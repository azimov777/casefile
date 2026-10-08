"""Демо-данные наполняют каждый экран.

Проверяется не «что-то записалось», а покрытие: экран, для которого в демо нечего
показать, читается разработчиком интерфейса как «этой механики нет». Поэтому здесь
сплошные проверки по словарям домена — статусы, типы записей, виды связей, — а не
выборочные утверждения о конкретных задачах.
"""

from collections import Counter

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.domain.authors import AuthorKind
from app.domain.case import EntryType
from app.domain.discussions import DiscussionStatus, DiscussionTurn
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.tasks import AskedParent, TaskParent, TaskStatus
from app.services import case as case_service
from app.services import demo as demo_service
from app.services import discussions as discussions_service
from app.services import links as links_service
from app.services import participants as participants_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.demo import DEMO_LABEL, DEMO_PROJECT_KEY, seed_demo
from app.services.setup import DEFAULT_OWNER_NAME


@pytest.fixture
async def seeded(db_session: AsyncSession) -> demo_service.DemoData:
    """Наполненная демо-установка. Идёт первой в базу теста: `init` ей не нужен."""
    return await seed_demo(db_session)


@pytest.fixture
def reader(seeded: demo_service.DemoData, db_session: AsyncSession) -> Actor:
    """Автор для чтения: набор `main`, потому что читается всё подряд."""
    assert seeded.project is not None
    return Actor(author=seeded.project.created_by)


async def _entry_types(
    session: AsyncSession, data: demo_service.DemoData, reader: Actor
) -> Counter[EntryType]:
    """Сколько записей каждого типа во всех делах демо: задач, проекта и обсуждений."""
    found: Counter[EntryType] = Counter()
    for task in data.tasks:
        page = await case_service.list_entries(session, task, actor=reader, limit=200)
        found.update(entry.type for entry in page.items)
    assert data.project is not None
    project_page = await case_service.list_project_entries(
        session, data.project, actor=reader, limit=200
    )
    found.update(entry.type for entry in project_page.items)
    discussions = await discussions_service.list_discussions(
        session, actor=reader, project=data.project, limit=200
    )
    for row in discussions.items:
        discussion_page = await case_service.list_discussion_entries(
            session, row.discussion, actor=reader, limit=200
        )
        found.update(entry.type for entry in discussion_page.items)
    return found


async def test_demo_fills_every_status(seeded: demo_service.DemoData) -> None:
    """Доска фронтенда — это столбцы по статусам, и пустой столбец читается как дефект."""
    assert seeded.created
    assert seeded.project is not None
    assert seeded.project.key == DEMO_PROJECT_KEY
    assert seeded.project.description, "проект без описания не даёт агенту общего контекста"

    assert {task.status for task in seeded.tasks} == set(TaskStatus)


async def test_demo_fills_every_entry_type(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Все типы записей, включая служебные, — в делах задач и в деле проекта.

    Служебные типы попадают в демо только через настоящие сценарии: `section_changed`
    — правкой раздела в `backlog`, `assignee_changed` — сменой исполнителя,
    `link_removed` — снятой связью. Пропущенный сценарий виден здесь и нигде больше.
    """
    found = await _entry_types(db_session, seeded, reader)

    assert set(found) == set(EntryType), sorted(item.value for item in set(EntryType) - set(found))


async def test_demo_fills_every_link_kind(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Три вида связей, каждый виден с обеих сторон под своим именем."""
    kinds: set[LinkKind] = set()
    for task in seeded.tasks:
        links = await links_service.list_links(db_session, task, actor=reader)
        kinds.update(link.kind for link in links)

    assert kinds == set(LinkKind)


async def test_demo_registers_a_human_and_an_agent_and_signs_with_a_label(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Обе формы identity агента и человек-адресат — иначе половину экранов нечем занять.

    Метка временного агента проверяется по подписи записи, а не по реестру: временного
    агента в реестре нет и быть не может, и это ровно то, что демо обязано показать.
    """
    registry = await participants_service.list_participants(db_session, actor=reader, limit=200)
    kinds = {participant.kind for participant in registry.items}
    assert kinds == {ParticipantKind.HUMAN, ParticipantKind.AGENT}

    signatures: set[tuple[AuthorKind, str | None]] = set()
    for task in seeded.tasks:
        page = await case_service.list_entries(db_session, task, actor=reader, limit=200)
        signatures.update((entry.author.kind, entry.author.signature) for entry in page.items)

    assert (AuthorKind.AGENT, DEMO_LABEL) in signatures, "нет записи временного агента"
    assert any(kind is AuthorKind.HUMAN for kind, _ in signatures), "нет записи человека"


async def test_every_demo_row_carries_the_features_of_its_own_card(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Признаки строки списка и признаки карточки сходятся на каждой задаче демо.

    Демо покрывает все статусы, все типы записей и все виды связей, поэтому здесь
    признаки встречаются во всех сочетаниях сразу: заблокированная задача, открытый
    блокирующий вопрос, задача со сводкой и задача без неё. Считаны они разными путями —
    подзапросом по каждой строке выдачи и чистой функцией над прочитанным делом, — и
    расхождение означало бы, что список и карточка отвечают по-разному на один вопрос.
    """
    outcome = await search_service.search_tasks(
        db_session, actor=reader, query=f"project: {DEMO_PROJECT_KEY}", limit=200
    )
    rows = {found.task.key: found.features for found in outcome.page.items}

    assert set(rows) == {task.key for task in seeded.tasks}
    for task in seeded.tasks:
        package = await tasks_service.read_task_package(db_session, task.key, actor=reader)
        assert rows[task.key] == package.features, task.key

    # Признак, всегда отвечающий одно и то же, совпал бы с карточкой и ничего не значил.
    assert any(features is not None and features.blocked for features in rows.values())
    assert any(features is not None and features.open_questions for features in rows.values())
    assert any(features is not None and features.last_summary_at for features in rows.values())
    assert any(features is not None and features.deferred for features in rows.values())


async def test_every_demo_row_names_the_parent_its_card_shows(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Родитель строки списка — поле `parent` карточки, на каждой задаче демо (TRK-95).

    Считаны они разными путями — подзапросом в выборке страницы и чтением связей
    пакета преемника, — и сойтись обязаны. Демо покрывает все виды связей, поэтому
    рядом с детьми есть и блокировки, и `relates`, которые в поле попасть не должны.
    """
    outcome = await search_service.search_tasks(
        db_session, actor=reader, query=f"project: {DEMO_PROJECT_KEY}", limit=200
    )
    rows = {found.task.key: found.parent for found in outcome.page.items}

    assert set(rows) == {task.key for task in seeded.tasks}
    for task in seeded.tasks:
        package = await tasks_service.read_task_package(db_session, task.key, actor=reader)
        from_card = (
            None
            if package.parent is None
            else TaskParent(key=package.parent.other.key, title=package.parent.other.title)
        )
        assert rows[task.key] == AskedParent(from_card), task.key

    # Поле, всегда пустое, совпало бы с карточкой и ничего не значило.
    assert any(row is not None and row.value for row in rows.values()), "в демо нет детей"


async def test_decomposed_test_is_a_child_of_the_task_in_progress(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Тест, выделенный декомпозицией, — ребёнок задачи в работе, а не наоборот (TRK-97).

    `_child_task` создаёт тест из задачи в работе, поэтому родитель — она: направление
    однажды стояло навыворот (UI-119#8), и здесь проверена именно эта пара задач, а не
    словарь видов связей вообще (им занята `test_demo_fills_every_link_kind`).
    """
    _done, in_progress, _candidate, _asking, child, *_rest = seeded.tasks
    assert in_progress.status is TaskStatus.IN_PROGRESS
    assert child.status is TaskStatus.BACKLOG

    outcome = await search_service.search_tasks(
        db_session, actor=reader, query=f"project: {DEMO_PROJECT_KEY}", limit=200
    )
    rows = {found.task.key: found.parent for found in outcome.page.items}

    assert rows[child.key] == AskedParent(TaskParent(key=in_progress.key, title=in_progress.title))
    assert rows[in_progress.key] == AskedParent(None)


async def test_demo_leaves_exactly_one_open_blocking_question(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Ожидание ответа — вопросом в обсуждении (`TRK#51`, п. 4 и 6), а не в деле задачи.

    Открытых вопросов в делах демо-задач нет; единственный блокирующий вопрос — в открытом
    обсуждении, к которому привязана DEMO-4. Он наполняет «входящую» и первый экран и
    делает осмысленным запрос кандидатов: задача с таким вопросом в работу не отдаётся,
    и в демо обязана быть и такая задача, и свободная.
    """
    blocking: list[str] = []
    for task in seeded.tasks:
        assert await case_service.open_questions(db_session, task, actor=reader) == [], task.key
        refs = await case_service.open_blocking_question_refs(db_session, task)
        if refs:
            assert len(refs) == 1 and "~" in refs[0], (task.key, refs)
            blocking.append(task.key)

    assert blocking == [f"{DEMO_PROJECT_KEY}-4"], blocking

    waiting = await search_service.search_tasks(
        db_session,
        actor=reader,
        query=f"project: {DEMO_PROJECT_KEY} and open_blocking_questions: 1",
    )
    assert [found.task.key for found in waiting.page.items] == blocking

    outcome = await search_service.search_tasks(
        db_session,
        actor=reader,
        query=(
            f"project: {DEMO_PROJECT_KEY} and status: open and blocked: false "
            "and open_blocking_questions: 0 and deferred: false"
        ),
    )
    candidates = [found.task.key for found in outcome.page.items]

    assert len(candidates) == 1, candidates
    assert candidates[0] not in blocking


async def test_seeding_twice_changes_nothing(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Обзорная проверка 5: повтор не меняет ни числа задач, ни числа записей.

    Команда стоит в Compose рядом с миграциями, и её случайный повтор не должен
    удваивать демо. Признак «уже наполнено» — сам проект `DEMO`.
    """
    before = await _entry_types(db_session, seeded, reader)
    tasks_before = len(
        (await search_service.search_tasks(db_session, actor=reader, limit=200)).page.items
    )

    again = await seed_demo(db_session)

    assert not again.created
    assert again.tasks == []
    after_tasks = (await search_service.search_tasks(db_session, actor=reader, limit=200)).page
    assert len(after_tasks.items) == tasks_before
    assert await _entry_types(db_session, seeded, reader) == before


async def test_the_demo_human_is_the_owner_the_init_command_creates(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Иначе блокирующий вопрос ушёл бы участнику, чьего токена никому не выдавали.

    Первый экран после `init` и `demo` обязан показать ненулевое число ждущих человека, а
    показывает он их владельцу — тому самому, чей токен лежит в фикстуре. Ждёт он
    обсуждения с вопросом (`TRK#51`); открытых вопросов в делах задач у владельца нет.
    """
    owner: Participant = await participants_service.get_participant(db_session, DEFAULT_OWNER_NAME)

    assert await case_service.count_open_questions(db_session, participant=owner) == 0
    assert await discussions_service.count_waiting_on_humans(db_session) == 1
    page = await discussions_service.list_discussions(
        db_session,
        actor=reader,
        status=DiscussionStatus.OPEN,
        turn=DiscussionTurn.HUMAN,
    )
    assert [row.discussion.address for row in page.items] == ["DEMO~2"]
