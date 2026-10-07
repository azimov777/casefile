"""Сценарии обсуждения: завести, прочитать, перечислить, привязать и отвязать задачу,
закрыть с итогом (решение проекта `TRK#51`).

Обсуждение — сущность проекта со своим делом. Его записи подшивает дело
(`app/services/case.py`, `append_discussion_entry`), а здесь — то, что меняет карточку и
привязки, со служебными записями в той же транзакции: `created` при заведении,
`attached`/`detached` в делах обеих сторон, итог и `closed` при закрытии.

## Привязка — это зависимость

Привязать задачу — сказать, что она зависит от итога (`TRK#51`, п. 3): пока в обсуждении
есть вопрос без ответа, задачу не взять в работу, а пока обсуждение не закрыто, задачу не
закрыть и не отменить (`app/domain/tasks.py`, проверки перехода). Трекер при этом ничего
не делает сам: не закрывает обсуждение, не отвязывает задачи и никого не будит.

## Закрытое заморожено

Закрытие — одно действие: итог и `closed` одной транзакцией, а при вопросе без ответа —
отказ `discussion_has_open_questions`. Дальше любая запись, привязка, отвязка и повторное
закрытие отвечают `discussion_closed` из одной точки — `app/services/freeze.py`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.discussion import Discussion, DiscussionTask
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.pagination import Page
from app.db.repositories import DiscussionRepository
from app.db.repositories.discussions import DiscussionRow
from app.domain.case import EntryContext, EntryType, build_entry, format_entry_ref
from app.domain.discussions import (
    MAX_TASKS_ON_CREATE,
    DiscussionOrder,
    DiscussionStatus,
    DiscussionTurn,
    parse_discussion_address,
)
from app.domain.errors import (
    DiscussionHasOpenQuestionsError,
    DiscussionNotFoundError,
    DiscussionTaskExistsError,
    DiscussionTaskNotFoundError,
    EntryFieldsInvalidError,
    TaskClosedError,
)
from app.domain.fields import FieldProblems
from app.domain.tasks import is_closed
from app.services import case as case_service
from app.services import freeze
from app.services import projects as projects_service
from app.services.auth import Actor

#: Чем можно завести обсуждение: запиской или вопросом (`TRK#51`, пункты 6 и 8).
OPENING_ENTRY_TYPES: frozenset[EntryType] = frozenset({EntryType.NOTE, EntryType.QUESTION})


@dataclass(frozen=True, slots=True)
class DiscussionDetail:
    """Обсуждение целиком для экрана: карточка, признаки, привязки и последний итог."""

    discussion: Discussion
    turn: DiscussionTurn | None
    open_questions: int
    attachments: list[DiscussionTask]
    conclusion: Entry | None


@dataclass(frozen=True, slots=True)
class DiscussionClosure:
    """Результат закрытия: обсуждение и подшитые записи — итог и `closed`."""

    discussion: Discussion
    entries: tuple[Entry, ...]


# --- Чтение ---------------------------------------------------------------------------


async def get_discussion(session: AsyncSession, address: str) -> Discussion:
    """Обсуждение по адресу `TRK~7`; адрес не по форме — `invalid_discussion_address`,
    неизвестный проект — `project_not_found`, номер — `discussion_not_found`."""
    parsed = parse_discussion_address(address)
    project = await projects_service.get_project(session, parsed.project_key)
    found = await DiscussionRepository(session).get(project.id, parsed.number)
    if found is None:
        raise DiscussionNotFoundError(details={"key": str(parsed)})
    return found


async def read_discussion(
    session: AsyncSession, discussion: Discussion, *, actor: Actor
) -> DiscussionDetail:
    """Карточка с чьим ходом, числом открытых вопросов, привязанными задачами и итогом."""
    repository = DiscussionRepository(session)
    row = await repository.row(discussion)
    return DiscussionDetail(
        discussion=discussion,
        turn=row.turn,
        open_questions=row.open_questions,
        attachments=await repository.attachments(discussion.id),
        conclusion=await case_service.last_conclusion(session, discussion, actor=actor),
    )


async def list_discussions(
    session: AsyncSession,
    *,
    actor: Actor,
    project: Project | None = None,
    status: DiscussionStatus | None = None,
    turn: DiscussionTurn | None = None,
    task: Task | None = None,
    order: DiscussionOrder = DiscussionOrder.OLDEST,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[DiscussionRow]:
    """Обсуждения с отбором по проекту, статусу, чьему ходу и привязанной задаче.

    Входящая человека — `status=open, turn=human`; обсуждения задачи — `task`; обсуждение
    без привязанных задач с ходом за агентом находится только так (`TRK#51`, п. 4).
    Обсуждения архивных проектов — только с названным `project`, как вопросы и задачи.
    """
    return await DiscussionRepository(session).page(
        project_id=None if project is None else project.id,
        status=status,
        turn=turn,
        task_id=None if task is None else task.id,
        order=order,
        limit=limit,
        cursor=cursor,
    )


async def count_waiting_on_humans(session: AsyncSession) -> int:
    """Сколько незакрытых обсуждений ждут человека — число для значка входящей."""
    return await DiscussionRepository(session).count_waiting_on_humans()


# --- Заведение ------------------------------------------------------------------------


async def create_discussion(
    session: AsyncSession,
    *,
    actor: Actor,
    project: Project,
    title: Any,
    opening: Any,
    body: Any = "",
    refs: Any = (),
    addressees: Any = None,
    tasks: Sequence[Task] = (),
) -> Discussion:
    """Заводит обсуждение первой записью — запиской или вопросом — и привязывает задачи
    тем же действием (`TRK#51`, пункты 1, 3 и 6).

    Название обсуждения и заголовок первой записи — одна строка: обсуждение и есть узкий
    вопрос, и у вопроса, которым его завели, другого названия нет. Отсюда и проверка
    названия — той же формой, что заголовок записи (`entry_fields_invalid`, поле
    `title`).

    Порядок: форма первой записи — до базы; очередь изменений и заморозка — проекта и
    задач; закрытая задача — `task_closed`; номер — последним из проверок; дальше
    подшивка: `created`, первая запись, привязки. Отказ любой подшивки откатывает всё
    действие, и номер, посчитанный `max + 1`, не сгорает.
    """
    payload = {"addressees": addressees} if opening == EntryType.QUESTION else None
    if opening not in OPENING_ENTRY_TYPES:
        problems = FieldProblems()
        problems.add(
            "type",
            "not_allowed",
            allowed=sorted(item.value for item in OPENING_ENTRY_TYPES),
            got=str(opening),
        )
        problems.raise_as(EntryFieldsInvalidError, key=project.key)
    draft = build_entry(
        EntryContext(task_key=project.key, checks=(), discussion=True),
        type=opening,
        title=title,
        body=body,
        payload=payload,
        refs=refs,
    )
    attached = _distinct(tasks)
    if len(attached) > MAX_TASKS_ON_CREATE:
        problems = FieldProblems()
        problems.add("tasks", "too_many", max=MAX_TASKS_ON_CREATE, got=len(attached))
        problems.raise_as(EntryFieldsInvalidError, key=project.key)

    await freeze.lock_unfrozen(session, *attached, project=project)
    for task in attached:
        _ensure_task_open(task)

    repository = DiscussionRepository(session)
    number = await repository.next_number(project.id)
    # Проект — объектом, а не только внешним ключом: адрес собирается из `project.key`,
    # а у только что созданной строки связь сама не подгрузится (`docs/notes/db.md`).
    discussion = await repository.add(
        Discussion(
            project=project,
            project_id=project.id,
            number=number,
            title=draft.title,
            status=DiscussionStatus.OPEN,
            **created_by_columns(actor.author),
        )
    )
    action_id = uuid.uuid4()
    await case_service.record_discussion_created(
        session, discussion, actor=actor, action_id=action_id
    )
    await case_service.append_discussion_entry(
        session,
        discussion,
        actor=actor,
        type=draft.type,
        title=draft.title,
        body=draft.body,
        payload=payload,
        refs=draft.refs,
        action_id=action_id,
    )
    for task in attached:
        await _attach(session, discussion, task, actor=actor, action_id=action_id)
    return discussion


# --- Привязка ---------------------------------------------------------------------------


async def attach_task(
    session: AsyncSession, discussion: Discussion, task: Task, *, actor: Actor
) -> DiscussionTask:
    """Привязывает задачу к обсуждению: задача зависит от его итога (`TRK#51`, п. 3).

    Отказы: архивный проект любой стороны — `project_archived`; закрытое обсуждение —
    `discussion_closed`; закрытая задача — `task_closed`; повтор — `discussion_task_exists`.
    `attached` ложится в дела обеих сторон одним действием.
    """
    await freeze.lock_unfrozen(session, task, discussion=discussion)
    _ensure_task_open(task)
    return await _attach(session, discussion, task, actor=actor, action_id=uuid.uuid4())


async def detach_task(
    session: AsyncSession, discussion: Discussion, task: Task, *, actor: Actor
) -> None:
    """Снимает привязку: задача больше не ждёт итога этого обсуждения.

    Отказы: архивный проект любой стороны — `project_archived`; закрытое обсуждение —
    `discussion_closed` (у закрытого привязки не меняются); привязки нет —
    `discussion_task_not_found`. `detached` ложится в дела обеих сторон одним действием.
    """
    await freeze.lock_unfrozen(session, task, discussion=discussion)
    repository = DiscussionRepository(session)
    attachment = await repository.attachment(discussion.id, task.id)
    if attachment is None:
        raise DiscussionTaskNotFoundError(
            details={"discussion": discussion.address, "task": task.key}
        )
    await repository.remove_attachment(attachment)
    action_id = uuid.uuid4()
    await _record_on_both_sides(
        session, discussion, task, actor=actor, attached=False, action_id=action_id
    )


# --- Закрытие ---------------------------------------------------------------------------


async def close_discussion(
    session: AsyncSession,
    discussion: Discussion,
    *,
    actor: Actor,
    decided: Any,
    superseded: Any,
    open: Any,
    body: Any = "",
    refs: Any = (),
) -> DiscussionClosure:
    """Закрывает обсуждение с итогом — одной транзакцией (`TRK#51`, п. 7).

    Порядок: форма итога — до базы (`entry_fields_invalid`, пустая часть в том числе);
    очередь изменений и заморозка — архив проекта, уже закрытое (`discussion_closed`);
    вопрос без ответа — `discussion_has_open_questions` с адресами вопросов. Дальше итог,
    `closed` и статус. Закрывает тот, кто вызвал; трекер сам не закрывает никогда.
    """
    parts = {"decided": decided, "superseded": superseded, "open": open}
    build_entry(
        EntryContext(task_key=discussion.address, checks=(), discussion=True),
        type=EntryType.CONCLUSION,
        body=body,
        payload=parts,
        refs=refs,
    )
    await freeze.lock_unfrozen(session, discussion=discussion)
    # Под очередью перечитать: обсуждение разрешено из адреса до неё, и статус в объекте
    # мог устареть.
    await session.refresh(discussion)
    address = discussion.address
    open_questions = await case_service.discussion_open_question_nos(session, discussion)
    if open_questions:
        raise DiscussionHasOpenQuestionsError(
            details={
                "key": address,
                "questions": [format_entry_ref(address, no) for no in open_questions],
            }
        )
    action_id = uuid.uuid4()
    conclusion = await case_service.add_conclusion(
        session,
        discussion,
        actor=actor,
        decided=decided,
        superseded=superseded,
        open=open,
        body=body,
        refs=refs,
        action_id=action_id,
    )
    closed = await case_service.record_discussion_closed(
        session, discussion, actor=actor, conclusion_no=conclusion.no, action_id=action_id
    )
    discussion.status = DiscussionStatus.CLOSED
    discussion.closed_at = closed.created_at
    await session.flush()
    return DiscussionClosure(discussion=discussion, entries=(conclusion, closed))


# --- Внутреннее -------------------------------------------------------------------------


def _distinct(tasks: Sequence[Task]) -> list[Task]:
    """Задачи без повторов в порядке первого упоминания: одна задача — одна привязка."""
    seen: set[uuid.UUID] = set()
    unique: list[Task] = []
    for task in tasks:
        if task.id not in seen:
            seen.add(task.id)
            unique.append(task)
    return unique


def _ensure_task_open(task: Task) -> None:
    """Закрытую задачу не привязать (`TRK#51`, п. 3): от итога она уже не зависит."""
    if is_closed(task.status):
        raise TaskClosedError(details={"key": task.key, "status": task.status.value})


async def _attach(
    session: AsyncSession,
    discussion: Discussion,
    task: Task,
    *,
    actor: Actor,
    action_id: uuid.UUID,
) -> DiscussionTask:
    """Строка привязки и `attached` в делах обеих сторон; вызывать под очередью изменений."""
    repository = DiscussionRepository(session)
    if await repository.attachment(discussion.id, task.id) is not None:
        raise DiscussionTaskExistsError(
            details={"discussion": discussion.address, "task": task.key}
        )
    attachment = await repository.add_attachment(
        DiscussionTask(
            discussion_id=discussion.id,
            task_id=task.id,
            task=task,
            **created_by_columns(actor.author),
        )
    )
    await _record_on_both_sides(
        session, discussion, task, actor=actor, attached=True, action_id=action_id
    )
    return attachment


async def _record_on_both_sides(
    session: AsyncSession,
    discussion: Discussion,
    task: Task,
    *,
    actor: Actor,
    attached: bool,
    action_id: uuid.UUID,
) -> None:
    """`attached`/`detached` в дело обсуждения, затем в дело задачи — одним действием.

    Порядок постоянный — сначала обсуждение, потом задача, — как у связей
    (`app/services/links.py`): строки владельцев блокируются под выдачу номера в одном
    порядке во всех сценариях.
    """
    for owner in (discussion, task):
        await case_service.record_attachment(
            session,
            owner,
            actor=actor,
            attached=attached,
            task_key=task.key,
            discussion=discussion.address,
            action_id=action_id,
        )
