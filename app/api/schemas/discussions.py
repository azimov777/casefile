"""Схемы обсуждения (решение проекта `TRK#51`)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.entries import ConclusionEntryRead, QuestionEntryRead, entry_read
from app.db.models.discussion import DiscussionTask
from app.domain.case import MAX_ENTRY_BODY_LENGTH, MAX_REFS
from app.domain.discussions import (
    MAX_DISCUSSION_TITLE_LENGTH,
    MAX_TASKS_ON_CREATE,
    DiscussionStatus,
    DiscussionTurn,
)
from app.domain.tasks import TaskStatus
from app.services.discussions import DiscussionDetail, DiscussionRow, TaskDiscussion

_ADDRESS_DESCRIPTION = (
    "Address of the discussion: the project key and its number, `TRK~7`. References to its "
    "case entries are `TRK~7#3`"
)
_TURN_DESCRIPTION = (
    "Whose move it is, computed on read: `human` — a question has no answer yet; `agent` — "
    "no open questions, but an answer or a person's entry came after the latest conclusion; "
    "`null` — neither, and always on a closed discussion"
)
_TITLE_EXAMPLE = "Обсуждение — своя сущность или ярлык над записями задач?"


class DiscussionTaskRead(BaseModel):
    """Привязанная задача: ключ, название, статус и кто привязал."""

    key: str = Field(examples=["TRK-42"])
    title: str = Field(examples=["Бэкенд обсуждения"])
    status: TaskStatus = Field(examples=[TaskStatus.OPEN])
    attached_by: AuthorRead
    attached_at: datetime


def discussion_task_read(attachment: DiscussionTask) -> DiscussionTaskRead:
    """Привязка строкой: задача берётся из связи (`DiscussionTask.task`, `joined`)."""
    return DiscussionTaskRead(
        key=attachment.task.key,
        title=attachment.task.title,
        status=attachment.task.status,
        attached_by=AuthorRead.model_validate(attachment.created_by),
        attached_at=attachment.created_at,
    )


class DiscussionRead(BaseModel):
    """Обсуждение в ответе: карточка и признаки, посчитанные при чтении."""

    id: uuid.UUID
    project_key: str = Field(examples=["TRK"], description="Key of the project; never changes")
    number: int = Field(examples=[7], description="Number inside the project, from 1")
    address: str = Field(examples=["TRK~7"], description=_ADDRESS_DESCRIPTION)
    title: str = Field(
        examples=[_TITLE_EXAMPLE],
        description="The narrow question itself, one line; the title of the first entry",
    )
    status: DiscussionStatus = Field(
        examples=[DiscussionStatus.OPEN],
        description=(
            "`open` or `closed`. A closed discussion never reopens and is frozen: any entry, "
            "attaching or detaching answers `409 discussion_closed`"
        ),
    )
    turn: DiscussionTurn | None = Field(
        examples=[DiscussionTurn.HUMAN], description=_TURN_DESCRIPTION
    )
    open_questions: int = Field(
        examples=[1], description="Questions of the discussion with no answer yet"
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = Field(
        examples=[None], description="When the discussion was closed; `null` while open"
    )


def discussion_read(row: DiscussionRow) -> DiscussionRead:
    """Карточка с признаками: ключ проекта и адрес собираются из связи с проектом."""
    discussion = row.discussion
    return DiscussionRead(
        id=discussion.id,
        project_key=discussion.project.key,
        number=discussion.number,
        address=discussion.address,
        title=discussion.title,
        status=discussion.status,
        turn=row.turn,
        open_questions=row.open_questions,
        created_by=AuthorRead.model_validate(discussion.created_by),
        created_at=discussion.created_at,
        updated_at=discussion.updated_at,
        closed_at=discussion.closed_at,
    )


class TaskDiscussionRead(BaseModel):
    """Обсуждение в пакете преемника задачи (решение `TRK#51`, п. 5): карточка без
    служебных полей, чей ход, открытые вопросы и последний итог целиком."""

    address: str = Field(examples=["TRK~7"], description=_ADDRESS_DESCRIPTION)
    title: str = Field(examples=[_TITLE_EXAMPLE], description="The narrow question itself")
    status: DiscussionStatus = Field(examples=[DiscussionStatus.OPEN])
    turn: DiscussionTurn | None = Field(
        examples=[DiscussionTurn.HUMAN], description=_TURN_DESCRIPTION
    )
    open_questions: list[QuestionEntryRead] = Field(
        description=(
            "Questions of the discussion with no answer yet, in full; each one keeps the "
            "task out of `in_progress` until it is answered"
        )
    )
    conclusion: ConclusionEntryRead | None = Field(
        description=(
            "The latest conclusion in full — decided, superseded, still open; it sets the "
            "work of the task together with its sections. `null` until the first one"
        )
    )


def task_discussion_read(item: TaskDiscussion) -> TaskDiscussionRead:
    """Обсуждение в пакете задачи: записи собирает тот же `entry_read`, что любую запись."""
    address = item.discussion.address
    questions = [entry_read(question, discussion=address) for question in item.open_questions]
    conclusion = (
        None if item.conclusion is None else entry_read(item.conclusion, discussion=address)
    )
    assert all(isinstance(question, QuestionEntryRead) for question in questions)
    assert conclusion is None or isinstance(conclusion, ConclusionEntryRead)
    return TaskDiscussionRead(
        address=address,
        title=item.discussion.title,
        status=item.discussion.status,
        turn=item.turn,
        open_questions=questions,  # type: ignore[arg-type]
        conclusion=conclusion,
    )


class DiscussionDetailRead(DiscussionRead):
    """Одно обсуждение для его экрана: привязанные задачи и последний итог сверху."""

    tasks: list[DiscussionTaskRead] = Field(
        description=(
            "Tasks attached to the discussion, in the order they were attached. Attaching "
            "says a task depends on the outcome: it cannot go into work while a question "
            "here has no answer, nor be closed or cancelled while the discussion is open"
        )
    )
    conclusion: ConclusionEntryRead | None = Field(
        description=(
            "The latest conclusion — what is decided, superseded and still open; it "
            "outranks the earlier ones. `null` until the first conclusion is filed"
        )
    )


def discussion_detail_read(detail: DiscussionDetail) -> DiscussionDetailRead:
    """Экран обсуждения из сценария чтения: тот же сборщик карточки, что у списка."""
    discussion = detail.discussion
    card = discussion_read(
        DiscussionRow(discussion=discussion, turn=detail.turn, open_questions=detail.open_questions)
    )
    conclusion = (
        None
        if detail.conclusion is None
        else entry_read(detail.conclusion, discussion=discussion.address)
    )
    assert conclusion is None or isinstance(conclusion, ConclusionEntryRead)
    return DiscussionDetailRead(
        **card.model_dump(),
        tasks=[discussion_task_read(item) for item in detail.attachments],
        conclusion=conclusion,
    )


class DiscussionCreate(BaseModel):
    """Новое обсуждение запиской — «Новое обсуждение» интерфейса (решение `TRK#51`, п. 8).

    Название — сам узкий вопрос одной строкой; оно же заголовок первой записи дела,
    заметки с телом `body`. Задачи из `tasks` привязываются тем же действием. Завести
    обсуждение вопросом может агент — через MCP (TRK-671).
    """

    model_config = ConfigDict(extra="forbid")

    project: str = Field(examples=["TRK"], description="Project key; matching ignores case")
    title: str = Field(
        min_length=1,
        max_length=MAX_DISCUSSION_TITLE_LENGTH,
        examples=[_TITLE_EXAMPLE],
        description=(
            "The narrow question, one line. A line break or a blank title answers "
            "`422 entry_fields_invalid` (field `title`)"
        ),
    )
    body: str = Field(
        default="",
        max_length=MAX_ENTRY_BODY_LENGTH,
        examples=["Контекст: вопросы растекаются по задачам…"],
        description="Markdown body of the first entry, a note: the context of the question",
    )
    refs: list[str] = Field(
        default_factory=list,
        max_length=MAX_REFS,
        examples=[["TRK-667#8"]],
        description="References of the first entry, as in any case entry",
    )
    tasks: list[str] = Field(
        default_factory=list,
        max_length=MAX_TASKS_ON_CREATE,
        examples=[["TRK-42"]],
        description=(
            "Keys of the tasks that depend on the outcome, attached by the same action. A "
            "closed task answers `409 task_closed`"
        ),
    )


class DiscussionTaskAttach(BaseModel):
    """Привязка задачи к обсуждению."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(examples=["TRK-42"], description="Key of the task; matching ignores case")
