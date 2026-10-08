"""Выборки и вставки по обсуждениям и привязкам задач (решение проекта `TRK#51`).

## Чей ход и открытые вопросы — запросом, одно определение

Признак «чей ход» и число открытых вопросов обсуждения не хранятся, а считаются из его
дела при каждом чтении (`turn_of`, `open_question_count_of`): колонка была бы вторым
местом, где живёт правда, и разошлась бы с делом в первый же откат. Карточка, строка
списка и отбор `turn` берут одно и то же выражение, поэтому двойника на Python нет.

Вопрос открыт, пока в **том же** обсуждении нет `answer` с его номером, — то же правило,
что у вопроса задачи (`app/db/repositories/entries.py`, `_unanswered`), только владелец
другой (`unanswered_in_discussion`).
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, case, func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.discussion import Discussion, DiscussionTask
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.pagination import (
    InvalidCursorError,
    Page,
    decode_sort_cursor,
    encode_sort_cursor,
    resolve_limit,
)
from app.db.repositories.projects import in_active_project
from app.domain.authors import AuthorKind
from app.domain.case import AGENT_ENTRY_TYPES, EntryType
from app.domain.discussions import (
    FIRST_DISCUSSION_NUMBER,
    DiscussionOrder,
    DiscussionStatus,
    DiscussionTurn,
    format_discussion_address,
)


@dataclass(frozen=True, slots=True)
class DiscussionRow:
    """Обсуждение вместе с тем, что считается из его дела при чтении."""

    discussion: Discussion
    turn: DiscussionTurn | None
    open_questions: int


class DiscussionRepository:
    """Доступ к таблицам `discussions` и `discussion_tasks`. Проект обсуждения приезжает
    тем же запросом (`Discussion.project`, `lazy="joined"`): без его ключа нет адреса."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: uuid.UUID, number: int) -> Discussion | None:
        """Обсуждение проекта по номеру."""
        statement = select(Discussion).where(
            Discussion.project_id == project_id, Discussion.number == number
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def get_by_address(self, project_key: str, number: int) -> Discussion | None:
        """Обсуждение по адресу из канонических частей — для ссылок `TRK~7` и `TRK~7#3`."""
        statement = (
            select(Discussion)
            .join(Project, Project.id == Discussion.project_id)
            .where(Project.key == project_key, Discussion.number == number)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def next_number(self, project_id: uuid.UUID) -> int:
        """Следующий номер обсуждения в проекте: `max(number) + 1` под блокировкой строки
        проекта.

        Тем же способом, что номер записи (`EntryRepository.allocate_project_no`), а не
        счётчиком на проекте: откат не сжигает номер, и колонка на проекте не нужна. Звать
        после очереди изменений (`app/db/locks.py`): обратный порядок захвата даёт
        взаимную блокировку.
        """
        lock = select(Project.id).where(Project.id == project_id).with_for_update()
        if await self._session.scalar(lock) is None:
            raise RuntimeError(f"Project {project_id} disappeared while numbering a discussion")
        highest = select(
            func.coalesce(func.max(Discussion.number), FIRST_DISCUSSION_NUMBER - 1)
        ).where(Discussion.project_id == project_id)
        return int(await self._session.scalar(highest)) + 1

    async def lock(self, discussion_id: uuid.UUID) -> None:
        """Строка обсуждения под блокировкой до конца транзакции — номер записи его дела
        выдаётся под ней (`EntryRepository.allocate_discussion_no`)."""
        statement = select(Discussion.id).where(Discussion.id == discussion_id).with_for_update()
        if await self._session.scalar(statement) is None:
            raise RuntimeError(f"Discussion {discussion_id} disappeared while locking it")

    async def add(self, discussion: Discussion) -> Discussion:
        self._session.add(discussion)
        await self._session.flush()
        return discussion

    async def first_closed(self, discussion_ids: Collection[uuid.UUID]) -> tuple[str, int] | None:
        """Ключ проекта и номер первого закрытого среди названных — для заморозки.

        Колонки, а не объект, как у `AreaRepository.first_archived`: запрос под очередью
        изменений видит состояние после зафиксировавшихся соседей и не трогает объекты в
        карте сессии.
        """
        if not discussion_ids:
            return None
        statement = (
            select(Project.key, Discussion.number)
            .join(Project, Project.id == Discussion.project_id)
            .where(
                Discussion.id.in_(discussion_ids),
                Discussion.status == DiscussionStatus.CLOSED,
            )
            .order_by(Project.key, Discussion.number)
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else (row[0], row[1])

    # --- Привязки -----------------------------------------------------------------

    async def attachment(
        self, discussion_id: uuid.UUID, task_id: uuid.UUID
    ) -> DiscussionTask | None:
        statement = select(DiscussionTask).where(
            DiscussionTask.discussion_id == discussion_id, DiscussionTask.task_id == task_id
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def add_attachment(self, attachment: DiscussionTask) -> DiscussionTask:
        self._session.add(attachment)
        await self._session.flush()
        return attachment

    async def remove_attachment(self, attachment: DiscussionTask) -> None:
        """Снимает привязку: история остаётся записями `detached` в делах обеих сторон."""
        await self._session.delete(attachment)
        await self._session.flush()

    async def attachments(self, discussion_id: uuid.UUID) -> list[DiscussionTask]:
        """Привязанные задачи обсуждения в порядке привязки."""
        statement = (
            select(DiscussionTask)
            .where(DiscussionTask.discussion_id == discussion_id)
            .order_by(DiscussionTask.created_at, DiscussionTask.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def unclosed_of_task(self, task_id: uuid.UUID) -> list[str]:
        """Адреса незакрытых обсуждений, к которым привязана задача, по адресу.

        Факт перехода задачи в `done` и `cancelled` (`task_has_open_discussions`): читается
        под очередью изменений, как остальные факты перехода.
        """
        statement = (
            select(Project.key, Discussion.number)
            .join(DiscussionTask, DiscussionTask.discussion_id == Discussion.id)
            .join(Project, Project.id == Discussion.project_id)
            .where(
                DiscussionTask.task_id == task_id,
                Discussion.status == DiscussionStatus.OPEN,
            )
            .order_by(Project.key, Discussion.number)
        )
        return [
            format_discussion_address(key, number)
            for key, number in await self._session.execute(statement)
        ]

    # --- Чтение с признаками -------------------------------------------------------

    async def row(self, discussion: Discussion) -> DiscussionRow:
        """Признаки одного обсуждения тем же выражением, что у списка."""
        statement = select(
            turn_of(Discussion).label("turn"),
            open_question_count_of(Discussion).label("open_questions"),
        ).where(Discussion.id == discussion.id)
        found = (await self._session.execute(statement)).one()
        return DiscussionRow(
            discussion=discussion,
            turn=_turn(found.turn),
            open_questions=int(found.open_questions),
        )

    async def of_task(self, task_id: uuid.UUID) -> list[DiscussionRow]:
        """Обсуждения, к которым задача привязана сейчас, открытые и закрытые, с признаками
        — по адресу. Для пакета преемника, поэтому без страниц и без отбора по архиву:
        у задачи их единицы, и задача архивного проекта читается со своими обсуждениями
        так же, как со своими связями."""
        statement = (
            select(
                Discussion,
                turn_of(Discussion).label("turn"),
                open_question_count_of(Discussion).label("open_questions"),
            )
            .join(DiscussionTask, DiscussionTask.discussion_id == Discussion.id)
            .join(Project, Project.id == Discussion.project_id)
            .where(DiscussionTask.task_id == task_id)
            .order_by(Project.key, Discussion.number)
        )
        return [
            DiscussionRow(
                discussion=item.Discussion,
                turn=_turn(item.turn),
                open_questions=int(item.open_questions),
            )
            for item in await self._session.execute(statement)
        ]

    async def page(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: DiscussionStatus | None = None,
        turn: DiscussionTurn | None = None,
        task_id: uuid.UUID | None = None,
        order: DiscussionOrder = DiscussionOrder.OLDEST,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[DiscussionRow]:
        """Страница обсуждений с отбором и признаками каждого.

        Порядок — время заведения, номер и идентификатор: номер различает обсуждения одной
        транзакции (`now()` в ней один, `TRK/db#35`), идентификатор — обсуждения
        разных проектов с одним временем. Курсор несёт порядок, в котором выдан: с курсором
        другого порядка страница пришла бы не та — `invalid_cursor`, как у вопросов.

        Обсуждения архивных проектов не попадают сюда, пока проект не назван
        (TRK#99, так же у вопросов и задач).
        """
        size = resolve_limit(limit)
        turn_column = turn_of(Discussion)
        statement = select(
            Discussion,
            turn_column.label("turn"),
            open_question_count_of(Discussion).label("open_questions"),
        )
        if project_id is not None:
            statement = statement.where(Discussion.project_id == project_id)
        else:
            statement = statement.where(in_active_project(Discussion.project_id))
        if status is not None:
            statement = statement.where(Discussion.status == status)
        if turn is not None:
            statement = statement.where(turn_column == turn.value)
        if task_id is not None:
            attached = aliased(DiscussionTask)
            statement = statement.where(
                select(1)
                .where(attached.discussion_id == Discussion.id, attached.task_id == task_id)
                .exists()
            )
        newest = order is DiscussionOrder.NEWEST
        position = tuple_(Discussion.created_at, Discussion.number, Discussion.id)
        if cursor is not None:
            (created_at, number, cursor_order), item_id = decode_sort_cursor(cursor, arity=3)
            if cursor_order != order.value:
                raise InvalidCursorError(
                    details={"cursor": cursor, "reason": "sort_mismatch", "expected": order.value}
                )
            boundary = (created_at, number, item_id)
            statement = statement.where(position < boundary if newest else position > boundary)
        ordering = (Discussion.created_at, Discussion.number, Discussion.id)
        statement = statement.order_by(
            *(column.desc() for column in ordering) if newest else ordering
        ).limit(size + 1)
        rows = [
            DiscussionRow(
                discussion=item.Discussion,
                turn=_turn(item.turn),
                open_questions=int(item.open_questions),
            )
            for item in await self._session.execute(statement)
        ]
        if len(rows) <= size:
            return Page(items=rows, next_cursor=None)
        page = rows[:size]
        last = page[-1].discussion
        return Page(
            items=page,
            next_cursor=encode_sort_cursor([last.created_at, last.number, order.value], last.id),
        )

    async def count_waiting_on_humans(self) -> int:
        """Сколько незакрытых обсуждений ждут человека (`turn: human`) в живых проектах —
        число для значка входящей на первом экране. Условие то же, что у отбора списка."""
        statement = (
            select(func.count())
            .select_from(Discussion)
            .where(
                Discussion.status == DiscussionStatus.OPEN,
                turn_of(Discussion) == DiscussionTurn.HUMAN.value,
                in_active_project(Discussion.project_id),
            )
        )
        return await self._session.scalar(statement) or 0


def _turn(value: Any) -> DiscussionTurn | None:
    return None if value is None else DiscussionTurn(value)


# --- Выражения признаков -------------------------------------------------------------


def unanswered_in_discussion(statement: Select[Any]) -> Select[Any]:
    """Оставляет вопросы, на которые в том же обсуждении нет ни одной записи `answer`.

    Двойник `_unanswered` дела задачи (`app/db/repositories/entries.py`) с другим
    владельцем: первый ответ любого исхода закрывает вопрос, остальные дополняют.
    """
    answer = aliased(Entry)
    return statement.where(
        ~select(1)
        .where(
            answer.discussion_id == Entry.discussion_id,
            answer.type == EntryType.ANSWER,
            answer.payload["question_no"].as_integer() == Entry.no,
        )
        .exists()
    )


def open_question_count_of(discussion: Any) -> ColumnElement[int]:
    """Число вопросов обсуждения без ответа — скалярным подзапросом по строке внешней
    выборки (`discussion` — модель или её псевдоним во внешнем запросе)."""
    return (
        unanswered_in_discussion(
            select(func.count())
            .select_from(Entry)
            .where(Entry.discussion_id == discussion.id, Entry.type == EntryType.QUESTION)
        )
        .correlate(discussion)
        .scalar_subquery()
    )


def turn_of(discussion: Any) -> ColumnElement[str | None]:
    """Чей ход в обсуждении — `human`, `agent` или `NULL` (решение `TRK#51`, п. 4).

    - `human` — в деле есть вопрос без ответа;
    - `agent` — вопросов без ответа нет, но после последнего итога есть ответ или запись
      человека (запись агента или человека, подписанная родом `human`; служебные — нет);
    - `NULL` — иначе, и всегда у закрытого: закрытие подшивает итог последним.

    «После последнего итога» выражено как «нет итога с номером больше», а не сравнением
    с `max(no)` вложенным подзапросом: так каждый подзапрос ссылается только на соседний
    уровень, и корреляция не зависит от глубины вложения.
    """
    question = aliased(Entry)
    answer = aliased(Entry)
    reply = aliased(Entry)
    later = aliased(Entry)
    has_open_question = (
        select(1)
        .where(
            question.discussion_id == discussion.id,
            question.type == EntryType.QUESTION,
            ~select(1)
            .where(
                answer.discussion_id == question.discussion_id,
                answer.type == EntryType.ANSWER,
                answer.payload["question_no"].as_integer() == question.no,
            )
            .exists(),
        )
        .correlate(discussion)
        .exists()
    )
    # Сам итог ответом не считается, даже подписанный человеком (токен владельца в MCP):
    # иначе итог оказывался бы «записью человека после последнего итога» — самого себя.
    human_or_answer_since_conclusion = (
        select(1)
        .where(
            reply.discussion_id == discussion.id,
            (reply.type == EntryType.ANSWER)
            | (
                (reply.created_by_kind == AuthorKind.HUMAN)
                & reply.type.in_(sorted(AGENT_ENTRY_TYPES - {EntryType.CONCLUSION}))
            ),
            ~select(1)
            .where(
                later.discussion_id == reply.discussion_id,
                later.type == EntryType.CONCLUSION,
                later.no > reply.no,
            )
            .exists(),
        )
        .correlate(discussion)
        .exists()
    )
    return case(
        (discussion.status == DiscussionStatus.CLOSED, literal(None)),
        (has_open_question, literal(DiscussionTurn.HUMAN.value)),
        (human_or_answer_since_conclusion, literal(DiscussionTurn.AGENT.value)),
        else_=literal(None),
    )


def open_discussion_question_count(task_id: Any) -> Select[tuple[int]]:
    """Вопросы без ответа в незакрытых обсуждениях, к которым привязана задача, — запрос,
    годный и как подзапрос по строке выдачи задач (`task_id` — колонка внешнего запроса).

    Вторая половина признаков `open_questions` и `open_blocking_questions` задачи
    (`TRK#51`, п. 4): любой вопрос обсуждения держит, признака `blocking` у него нет.
    Питоновский двойник — `EntryRepository.open_discussion_questions_of_task`, из которого
    считает карточка; сверяет обе формы тест на одних данных.
    """
    attached = aliased(DiscussionTask)
    owner = aliased(Discussion)
    return unanswered_in_discussion(
        select(func.count())
        .select_from(Entry)
        .join(attached, attached.discussion_id == Entry.discussion_id)
        .join(owner, owner.id == Entry.discussion_id)
        .where(
            attached.task_id == task_id,
            owner.status == DiscussionStatus.OPEN,
            Entry.type == EntryType.QUESTION,
        )
    )


def discussion_ids_of_tasks(task_ids: Sequence[uuid.UUID]) -> Select[tuple[uuid.UUID]]:
    """Обсуждения, к которым привязана хоть одна из задач, — для отбора ленты по задачам."""
    return select(DiscussionTask.discussion_id).where(DiscussionTask.task_id.in_(list(task_ids)))
