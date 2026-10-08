"""Гонка перехода со связью: очередь изменений не даёт двум сценариям чередоваться.

Проверять это на общей фикстуре `db_session` бессмысленно: она живёт внутри одной
транзакции, а разъезжаются здесь именно **две** транзакции. Поэтому тут всё своё —
сессии с настоящими коммитами поверх движка прогона и ручная уборка закоммиченных строк.

## Как ставится гонка

Переход собирает факты обычным `SELECT`, а фиксацию задачи страхует только её `version`.
Появление ребёнка и постановка блокера версию переводимой задачи не двигают, поэтому без
общей очереди проходило бы такое чередование:

1. транзакция A читает факты перехода — детей нет, блокеров нет — и останавливается;
2. транзакция B ставит связь и **фиксируется**: с её точки зрения родитель ещё открыт;
3. транзакция A фиксирует переход.

Получается состояние, которое обе проверки поодиночке запрещают: закрытый родитель с
открытым ребёнком либо задача в `in_progress` с открытым блокером.

Остановка A в нужной точке — подмена функции факта (`unclosed_children`,
`open_blockers`): она честно считает факт и потом ждёт события теста. Ждать барьером,
как в гонке за номером, здесь нельзя — нужен не одновременный старт, а **пауза между
чтением и фиксацией**, то есть ровно то окно, которое закрывает очередь.

## Что делает тест зелёным

Только блокировка. Уберите `lock_changes` из `apply_task_changes` и `add_link` — и обе
проверки покраснеют: B успевает пройти целиком, пока A стоит на паузе.

## Снятие вопроса против ответа (TRK-552)

Та же гонка у записи `answer`: снять вопрос можно, только пока на него не ответили, и
снятие читает «ответа ещё нет» обычным `SELECT`. Пауза ставится после этого чтения
(`EntryRepository.first_answer_no`), а второй транзакцией приходит обычный ответ или второе
снятие. Зелёным тест делает `lock_changes` в `append_entry` **до** проверок по базе: без
неё B подшивается целиком, пока A стоит на паузе, и снятие встаёт вторым ответом.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.authors import TRACKER, label_author
from app.domain.case import CLOSING_WITHOUT_ANSWER, EntryType, answer_outcome
from app.domain.links import LinkKind
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import links as links_service
from app.services import tasks as tasks_service
from app.services.auth import TRACKER_ACTOR, Actor

#: Сколько тест ждёт, прежде чем решить, что вторая транзакция действительно встала в
#: очередь. На исправном коде она стоит на блокировке, на сломанном — успевает всё.
SETTLE = 0.5

PROJECT_KEY = "MUTRACE"

#: Кто переводит в гонке. Не сам трекер: в `in_progress` задачу берёт только её
#: исполнитель (TRK#109), а у трекера подписи нет. Метка — чтобы не заводить
#: участника ради гонки, которая проверяет очередь изменений, а не реестр.
RACER = Actor(author=label_author("racer"))


@dataclass(frozen=True, slots=True)
class Trio:
    """Три задачи гонки: переводимая, её будущий ребёнок и её будущий блокер."""

    subject: uuid.UUID
    child: uuid.UUID
    blocker: uuid.UUID


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий поверх движка прогона: каждая коммитит по-настоящему."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def trio(committing_sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[Trio]:
    """Закоммиченные задачи и уборка за собой.

    Задачи собираются прямо моделями, а не полным циклом через сценарии: переводимая
    нужна в `in_progress` и без проверок (тогда закрытие не упирается в вердикты), а
    проверяется здесь не таблица переходов, а гонка. Одну запись ей всё же подшивают
    руками: без записи о входе в работу закрытие отказало бы раньше, чем дошло до
    фактов гонки — граница «этого захода» считается от неё. Сводку подшивает само
    закрытие. Уборка записей идёт с выключенным триггером неизменяемости — единственное
    законное место, где его выключают (`docs/notes/db.md`).
    """
    async with committing_sessions() as session:
        project = Project(key=PROJECT_KEY, title="Гонка изменений", **created_by_columns(TRACKER))
        session.add(project)
        await session.flush()
        subject = Task(
            key=f"{PROJECT_KEY}-1",
            project=project,
            title="Переводимая задача",
            description="Её и переводят в гонке",
            status=TaskStatus.IN_PROGRESS,
            assignee=RACER.author.signature,
            **created_by_columns(TRACKER),
        )
        child = Task(
            key=f"{PROJECT_KEY}-2",
            project=project,
            title="Ребёнок",
            description="Появляется во время перехода родителя",
            status=TaskStatus.OPEN,
            **created_by_columns(TRACKER),
        )
        blocker = Task(
            key=f"{PROJECT_KEY}-3",
            project=project,
            title="Блокер",
            description="Появляется во время входа в работу",
            status=TaskStatus.OPEN,
            **created_by_columns(TRACKER),
        )
        session.add_all([subject, child, blocker])
        await session.flush()
        session.add_all(
            [
                Entry(
                    task_id=subject.id,
                    no=1,
                    type=EntryType.STATUS_CHANGED,
                    title="Status changed: open -> in_progress",
                    payload={"from": "open", "to": "in_progress", "reason": None},
                    **created_by_columns(TRACKER),
                ),
            ]
        )
        await session.commit()
        ids = Trio(subject=subject.id, child=child.id, blocker=blocker.id)
        project_id = project.id

    try:
        yield ids
    finally:
        task_ids = [ids.subject, ids.child, ids.blocker]
        async with committing_sessions() as session:
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(
                text("DELETE FROM entries WHERE task_id = ANY(:ids)"), {"ids": task_ids}
            )
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            # Связи сносятся отдельно: внешние ключи на задачу объявлены без каскада.
            await session.execute(
                text("DELETE FROM links WHERE source_id = ANY(:ids) OR target_id = ANY(:ids)"),
                {"ids": task_ids},
            )
            await session.execute(text("DELETE FROM tasks WHERE id = ANY(:ids)"), {"ids": task_ids})
            await session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
            await session.commit()


def pause_after(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    read: asyncio.Event,
    resume: asyncio.Event,
) -> None:
    """Заставляет факт перехода посчитаться честно и остановиться сразу после этого.

    Подменяется функция сценария связей, потому что именно она и есть чтение факта.
    Поведение не меняется — добавляется только пауза, поэтому подмена не превращает
    проверку в проверку самой себя.
    """
    original: Callable[..., object] = getattr(links_service, name)

    async def paused(session: AsyncSession, task: Task) -> object:
        fact = await original(session, task)
        read.set()
        await resume.wait()
        return fact

    monkeypatch.setattr(links_service, name, paused)


async def _transition(
    sessions: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    to: TaskStatus,
) -> str | None:
    """Переход в своей транзакции. Возвращает код отказа или `None`, если прошёл."""
    async with sessions() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        try:
            await tasks_service.transition_task(session, task, actor=RACER, to=to)
        except AppError as error:
            return error.code
        await session.commit()
        return None


async def _close(sessions: async_sessionmaker[AsyncSession], task_id: uuid.UUID) -> str | None:
    """Закрытие в своей транзакции. Возвращает код отказа или `None`, если прошло."""
    async with sessions() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        try:
            await tasks_service.close_task(
                session,
                task,
                actor=TRACKER_ACTOR,
                summary=case_service.SummaryFiling(
                    done="Выход готов",
                    remaining="Ничего",
                    blockers="Нет",
                    next_step="Шагов нет, задача закрыта",
                    unmeasured="Гонка проверяется прогоном, отдельной обзорной проверки на неё нет",
                ),
            )
        except AppError as error:
            return error.code
        await session.commit()
        return None


async def _add_link(
    sessions: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    other_id: uuid.UUID,
    kind: LinkKind,
) -> str | None:
    """Постановка связи в своей транзакции. Задачи читаются **до** вызова сценария.

    Так же это делают роутер и инструмент MCP: ключи разрешаются в объекты снаружи, и
    сценарий получает снимок, сделанный до очереди. Именно этот снимок и обязан
    перечитаться под блокировкой.
    """
    async with sessions() as session:
        task = await session.get(Task, task_id)
        other = await session.get(Task, other_id)
        assert task is not None
        assert other is not None
        try:
            await links_service.add_link(session, task, other, actor=TRACKER_ACTOR, kind=kind)
        except AppError as error:
            return error.code
        await session.commit()
        return None


async def _status(sessions: async_sessionmaker[AsyncSession], task_id: uuid.UUID) -> TaskStatus:
    async with sessions() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task.status


async def _seq_of(
    sessions: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    type: EntryType,
) -> int | None:
    """Сквозной номер последней записи такого типа в задаче."""
    async with sessions() as session:
        statement = (
            select(Entry.seq)
            .where(Entry.task_id == task_id, Entry.type == type)
            .order_by(Entry.seq.desc())
            .limit(1)
        )
        return await session.scalar(statement)


async def test_closing_a_parent_and_giving_it_a_child_cannot_interleave(
    committing_sessions: async_sessionmaker[AsyncSession],
    trio: Trio,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Обзорная проверка 1: закрытого родителя с открытым ребёнком не бывает.

    Исходов ровно два, и оба законны: либо переход прошёл, а связь получила
    `task_closed`, либо связь встала первой, а переход отказал по незакрытым детям.
    Третьего — «прошли оба» — не существует.
    """
    read = asyncio.Event()
    resume = asyncio.Event()
    pause_after(monkeypatch, "unclosed_children", read=read, resume=resume)

    closing = asyncio.create_task(_close(committing_sessions, trio.subject))
    await asyncio.wait_for(read.wait(), timeout=10)
    linking = asyncio.create_task(
        _add_link(committing_sessions, trio.child, trio.subject, LinkKind.CHILD)
    )
    # Пауза не для планировщика, а для проверки: за это время постановка связи либо
    # встала в очередь, либо (на сломанном коде) успела пройти целиком.
    await asyncio.sleep(SETTLE)
    resume.set()
    transition_refusal, link_refusal = await asyncio.gather(closing, linking)

    assert (transition_refusal, link_refusal) in {
        (None, "task_closed"),
        ("task_has_unclosed_children", None),
    }, f"переход: {transition_refusal}, связь: {link_refusal}"

    status = await _status(committing_sessions, trio.subject)
    children = await _seq_of(committing_sessions, trio.child, EntryType.LINK_ADDED)
    assert not (status is TaskStatus.DONE and children is not None), (
        "родитель закрыт, но ребёнок к нему всё-таки привязался"
    )


async def test_taking_a_task_into_work_and_blocking_it_cannot_interleave(
    committing_sessions: async_sessionmaker[AsyncSession],
    trio: Trio,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Обзорная проверка 2: задачи в `in_progress` поверх открытого блокера не бывает.

    Порядок виден по журналу: если переход прошёл, его запись обязана стоять **раньше**
    записи о связи. Обратный порядок и означает то самое чередование — блокер
    зафиксирован, а вход в работу его не увидел.
    """
    async with committing_sessions() as session:
        subject = await session.get(Task, trio.subject)
        assert subject is not None
        subject.status = TaskStatus.OPEN
        await session.commit()

    read = asyncio.Event()
    resume = asyncio.Event()
    pause_after(monkeypatch, "open_blockers", read=read, resume=resume)

    taking = asyncio.create_task(
        _transition(committing_sessions, trio.subject, TaskStatus.IN_PROGRESS)
    )
    await asyncio.wait_for(read.wait(), timeout=10)
    linking = asyncio.create_task(
        _add_link(committing_sessions, trio.subject, trio.blocker, LinkKind.BLOCKED_BY)
    )
    await asyncio.sleep(SETTLE)
    resume.set()
    transition_refusal, link_refusal = await asyncio.gather(taking, linking)

    assert link_refusal is None, f"связь не должна была отказать: {link_refusal}"
    if transition_refusal == "task_blocked":
        return

    assert transition_refusal is None, f"неожиданный отказ перехода: {transition_refusal}"
    entered = await _seq_of(committing_sessions, trio.subject, EntryType.STATUS_CHANGED)
    linked = await _seq_of(committing_sessions, trio.subject, EntryType.LINK_ADDED)
    assert entered is not None
    assert linked is not None
    assert entered < linked, (
        "блокер зафиксирован раньше входа в работу, но переход этого не заметил: "
        f"status_changed={entered}, link_added={linked}"
    )


# --- Снятие вопроса против ответа (TRK-552) -------------------------------------------

QUESTION_PROJECT_KEY = "QRACE"

#: Номер вопроса в деле гоночной задачи: он подшит первой и единственной записью.
QUESTION_NO = 1


@pytest.fixture
async def asked(committing_sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[uuid.UUID]:
    """Закоммиченная задача с одним открытым вопросом и уборка за собой."""
    async with committing_sessions() as session:
        project = Project(
            key=QUESTION_PROJECT_KEY, title="Гонка ответа", **created_by_columns(TRACKER)
        )
        session.add(project)
        await session.flush()
        task = Task(
            key=f"{QUESTION_PROJECT_KEY}-1",
            project=project,
            title="Задача под вопросом",
            description="Вопрос снимают и одновременно отвечают",
            status=TaskStatus.IN_PROGRESS,
            **created_by_columns(TRACKER),
        )
        session.add(task)
        await session.flush()
        session.add(
            Entry(
                task_id=task.id,
                no=QUESTION_NO,
                type=EntryType.QUESTION,
                title="Какой ключ канонический?",
                payload={"addressees": ["owner"], "blocking": True},
                **created_by_columns(TRACKER),
            )
        )
        await session.commit()
        task_id = task.id
        project_id = project.id

    try:
        yield task_id
    finally:
        async with committing_sessions() as session:
            await session.execute(text("ALTER TABLE entries DISABLE TRIGGER entries_immutable"))
            await session.execute(text("DELETE FROM entries WHERE task_id = :id"), {"id": task_id})
            await session.execute(text("ALTER TABLE entries ENABLE TRIGGER entries_immutable"))
            await session.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
            await session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
            await session.commit()


def pause_after_the_answer_check(
    monkeypatch: pytest.MonkeyPatch, *, read: asyncio.Event, resume: asyncio.Event
) -> None:
    """Первое чтение «есть ли ответ» считается честно и останавливается после себя.

    Только первое: второе снятие в гонке читает тот же факт, и стоять на паузе ему не
    за чем — его либо держит очередь, либо (на сломанном коде) не держит ничто.
    """
    original = EntryRepository.first_answer_no
    paused = False

    async def first_answer_no(
        self: EntryRepository, task_id: uuid.UUID, question_no: int
    ) -> int | None:
        nonlocal paused
        fact = await original(self, task_id, question_no)
        if not paused:
            paused = True
            read.set()
            await resume.wait()
        return fact

    monkeypatch.setattr(EntryRepository, "first_answer_no", first_answer_no)


async def _answer(
    sessions: async_sessionmaker[AsyncSession], task_id: uuid.UUID, *, outcome: str | None
) -> str | None:
    """Ответ или снятие в своей транзакции. Возвращает код отказа или `None`."""
    async with sessions() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        try:
            await case_service.answer(
                session,
                task,
                actor=RACER,
                question_no=QUESTION_NO,
                outcome=outcome,
                body="Устарел" if outcome is not None else "Ответ по существу",
            )
        except AppError as error:
            return error.code
        await session.commit()
        return None


async def _answers(sessions: async_sessionmaker[AsyncSession], task_id: uuid.UUID) -> list[str]:
    """Исходы всех ответов на вопрос в порядке подшивки."""
    async with sessions() as session:
        statement = (
            select(Entry.payload)
            .where(Entry.task_id == task_id, Entry.type == EntryType.ANSWER)
            .order_by(Entry.no)
        )
        return [answer_outcome(payload).value for payload in await session.scalars(statement)]


async def _race(
    sessions: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    *,
    second: str | None,
) -> tuple[str | None, str | None]:
    """Снятие стоит на паузе после проверки, второй вызов приходит в это окно."""
    read = asyncio.Event()
    resume = asyncio.Event()
    pause_after_the_answer_check(monkeypatch, read=read, resume=resume)

    withdrawing = asyncio.create_task(_answer(sessions, task_id, outcome="withdrawn"))
    await asyncio.wait_for(read.wait(), timeout=10)
    answering = asyncio.create_task(_answer(sessions, task_id, outcome=second))
    await asyncio.sleep(SETTLE)
    resume.set()
    first_refusal, second_refusal = await asyncio.gather(withdrawing, answering)
    return first_refusal, second_refusal


async def test_withdrawing_a_question_and_answering_it_cannot_interleave(
    committing_sessions: async_sessionmaker[AsyncSession],
    asked: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверка 1 (з) TRK-552: снятия поверх ответа не бывает.

    Обычный ответ, пришедший в окно снятия, встаёт за ним в очередь и подшивается
    дополнением. На сломанном коде он успевает первым, и снятие ложится вторым ответом —
    то есть отвеченный вопрос оказывается снятым.
    """
    withdrawal_refusal, answer_refusal = await _race(
        committing_sessions, asked, monkeypatch, second=None
    )

    assert (withdrawal_refusal, answer_refusal) == (None, None)
    outcomes = await _answers(committing_sessions, asked)
    assert outcomes == ["withdrawn", "answered"], f"снятие подшито не первым ответом: {outcomes}"


async def test_two_withdrawals_of_one_question_cannot_both_be_first(
    committing_sessions: async_sessionmaker[AsyncSession],
    asked: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверка 1 (з) TRK-552: двух «первых» исходов у одного вопроса не бывает."""
    first_refusal, second_refusal = await _race(
        committing_sessions, asked, monkeypatch, second="withdrawn"
    )

    assert (first_refusal, second_refusal) == (None, "entry_fields_invalid")
    outcomes = await _answers(committing_sessions, asked)
    closing = [outcome for outcome in outcomes if outcome in CLOSING_WITHOUT_ANSWER]
    assert closing == ["withdrawn"], f"снятий вопроса больше одного: {outcomes}"
