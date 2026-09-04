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
from app.domain.case import EntryType, is_blocking_question
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.tasks import TaskStatus
from app.domain.tokens import TokenScope
from app.services import case as case_service
from app.services import demo as demo_service
from app.services import links as links_service
from app.services import participants as participants_service
from app.services import search as search_service
from app.services.auth import Actor
from app.services.demo import DEMO_LABEL, DEMO_QUEUE_KEY, seed_demo
from app.services.setup import DEFAULT_OWNER_NAME


@pytest.fixture
async def seeded(db_session: AsyncSession) -> demo_service.DemoData:
    """Наполненная демо-установка. Идёт первой в базу теста: `init` ей не нужен."""
    return await seed_demo(db_session)


@pytest.fixture
def reader(seeded: demo_service.DemoData, db_session: AsyncSession) -> Actor:
    """Автор для чтения: набор `main`, потому что читается всё подряд."""
    assert seeded.queue is not None
    return Actor(author=seeded.queue.created_by, scope=TokenScope.MAIN)


async def _entry_types(
    session: AsyncSession, data: demo_service.DemoData, reader: Actor
) -> Counter[EntryType]:
    """Сколько записей каждого типа во всех делах демо."""
    found: Counter[EntryType] = Counter()
    for task in data.tasks:
        page = await case_service.list_entries(session, task, actor=reader, limit=200)
        found.update(entry.type for entry in page.items)
    return found


async def test_demo_fills_every_status(seeded: demo_service.DemoData) -> None:
    """Доска фронтенда — это столбцы по статусам, и пустой столбец читается как дефект."""
    assert seeded.created
    assert seeded.queue is not None
    assert seeded.queue.key == DEMO_QUEUE_KEY
    assert seeded.queue.description, "очередь без описания не даёт агенту общего контекста"

    assert {task.status for task in seeded.tasks} == set(TaskStatus)


async def test_demo_fills_every_entry_type(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Все пятнадцать типов записей, включая служебные.

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


async def test_demo_leaves_exactly_one_open_blocking_question(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Открытый блокирующий вопрос — то, чем наполняются «входящая» и первый экран.

    Он же делает осмысленным запрос кандидатов: задача с таким вопросом в работу не
    отдаётся, и в демо обязана быть и такая задача, и свободная.
    """
    blocking: list[str] = []
    for task in seeded.tasks:
        for question in await case_service.open_questions(db_session, task, actor=reader):
            if is_blocking_question(question.payload):
                blocking.append(task.key)

    assert len(blocking) == 1, blocking

    outcome = await search_service.search_tasks(
        db_session,
        actor=reader,
        query=(
            f"queue: {DEMO_QUEUE_KEY} and status: open and blocked: false "
            "and open_blocking_questions: 0"
        ),
    )
    candidates = [task.key for task in outcome.page.items]

    assert len(candidates) == 1, candidates
    assert candidates[0] not in blocking


async def test_seeding_twice_changes_nothing(
    db_session: AsyncSession, seeded: demo_service.DemoData, reader: Actor
) -> None:
    """Обзорная проверка 5: повтор не меняет ни числа задач, ни числа записей.

    Команда стоит в Compose рядом с миграциями, и её случайный повтор не должен
    удваивать демо. Признак «уже наполнено» — сама очередь `DEMO`.
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

    Первый экран после `init` и `demo` обязан показать ненулевое число вопросов, а
    показывает он их владельцу — тому самому, чей токен напечатала инициализация.
    """
    owner: Participant = await participants_service.get_participant(db_session, DEFAULT_OWNER_NAME)

    assert await case_service.count_open_questions(db_session, participant=owner) == 1
