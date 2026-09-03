"""Схемы задач.

Из них же собирается OpenAPI, поэтому описания и примеры пишутся здесь, а не в роутере.
Границы длины повторяют домен (`app/domain/tasks.py`): в схеме они ради документации и
раннего отсева, настоящую проверку делает домен — одинаково для REST и MCP.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.api.schemas.entries import EntryHeadingRead, QuestionEntryRead, SummaryEntryRead
from app.api.schemas.links import TaskLinkRead
from app.domain.tasks import (
    MAX_ASSIGNEE_LENGTH,
    MAX_CHECKS,
    MAX_TAGS,
    MAX_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    TaskPriority,
    TaskStatus,
)

_TITLE_EXAMPLE = "Починить выдачу ключей задач"
_DESCRIPTION_EXAMPLE = "Ключ выдаётся до валидации и сгорает на неудачном запросе"
_SECTION_DESCRIPTION = "Markdown section; editable only in `backlog`"
_CHECKS_DESCRIPTION = (
    "Ordered list of review checks, numbered from 1 by position; each one must be "
    "written so that it can fail. Editable only in `backlog`"
)
_ASSIGNEE_DESCRIPTION = (
    "Participant name or temporary agent label; free text the tracker never validates "
    "against the registry"
)
_TAGS_DESCRIPTION = "Flat labels; order is kept, duplicates are dropped case-insensitively"
_CHECKS_EXAMPLE = ["docker compose run --rm test: the whole suite is green"]


class TaskQueueRead(BaseModel):
    """Очередь в карточке задачи: ключ и название. Описание запрашивается отдельно."""

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(examples=["TRK"])
    title: str = Field(examples=["Трекер"])


class TaskRead(BaseModel):
    """Задача в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str = Field(examples=["TRK-42"], description="Immutable and never reused")
    queue: TaskQueueRead
    title: str = Field(examples=[_TITLE_EXAMPLE])
    description: str = Field(examples=[_DESCRIPTION_EXAMPLE])
    goal: str = Field(examples=["Ключи не сгорают на отклонённых запросах"])
    context: str = Field(examples=["Номер выдаёт `queues.next_task_number`"])
    constraints: str = Field(examples=["Счётчик очереди не переписывать"])
    output: str = Field(examples=["Тест на несгоревший номер"])
    checks: list[str] = Field(examples=[_CHECKS_EXAMPLE], description=_CHECKS_DESCRIPTION)
    status: TaskStatus = Field(examples=[TaskStatus.BACKLOG])
    assignee: str | None = Field(examples=["release_bot"], description=_ASSIGNEE_DESCRIPTION)
    tags: list[str] = Field(examples=[["backend"]], description=_TAGS_DESCRIPTION)
    priority: TaskPriority = Field(examples=[TaskPriority.NORMAL])
    version: int = Field(
        examples=[3],
        description="Grows with every actual change; send it back to detect a lost update",
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime


class TaskFeaturesRead(BaseModel):
    """Вычисляемые признаки задачи (`CONCEPT.md`, 4.3).

    Не хранятся колонками, а считаются из дела и связей: колонка была бы вторым местом,
    где живёт правда, и разошлась бы с делом при первом же откате.
    """

    blocked: bool = Field(
        examples=[False],
        description=(
            "Whether the task has a `blocked_by` link to a task that is neither `done` "
            "nor `cancelled`. Entering `in_progress` is refused while it is true"
        ),
    )
    open_questions: int = Field(examples=[2], description="Questions with no answer")
    open_blocking_questions: int = Field(
        examples=[1], description="Of those, the ones marked `blocking`"
    )
    last_summary_at: datetime | None = Field(
        default=None,
        description="When the latest summary was filed; null if the case has none",
    )


class TaskPackageRead(BaseModel):
    """Пакет преемника (`CONCEPT.md`, 4.2).

    Всё, что нужно агенту с чистым контекстом, одним вызовом. Полно хранится, по
    оглавлению читается: карточка, связи, признаки, последняя сводка и открытые вопросы
    приходят целиком, остальные записи — строками описи, а их тела запрашиваются
    точечно.
    """

    task: TaskRead
    links: list[TaskLinkRead] = Field(
        description=(
            "Links on both sides, each named from this task's point of view, with the "
            "status of the task on the other side"
        )
    )
    features: TaskFeaturesRead
    summary: SummaryEntryRead | None = Field(
        default=None,
        description=(
            "The latest summary in full: what was done, what is left, what is in the "
            "way, what is next. Null until the case has one"
        ),
    )
    questions: list[QuestionEntryRead] = Field(
        description="Every question with no answer yet, in full"
    )
    transitions: list[TaskStatus] = Field(
        examples=[[TaskStatus.OPEN, TaskStatus.CANCELLED]],
        description=(
            "Targets allowed by the transition table from the current status. Transition "
            "validations (sections, summary, verdicts, blockers) are checked on the move"
        ),
    )
    index: list[EntryHeadingRead] = Field(
        description="Case index: heading of every entry, in order; bodies are read separately"
    )


class TaskCreate(BaseModel):
    """Создание задачи. Статуса нет: новая задача рождается в `backlog`.

    Ключа тоже нет — его выдаёт счётчик очереди. Разделы можно оставить пустыми и
    дописать в `backlog`; перед `open` они обязаны быть заполнены.
    """

    model_config = ConfigDict(extra="forbid")

    queue: str = Field(examples=["TRK"], description="Queue key; matching ignores case")
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH, examples=[_TITLE_EXAMPLE])
    description: str = Field(
        min_length=1, max_length=MAX_TEXT_LENGTH, examples=[_DESCRIPTION_EXAMPLE]
    )
    goal: str = Field(default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    context: str = Field(default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    constraints: str = Field(
        default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION
    )
    output: str = Field(default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    checks: list[str] = Field(
        default_factory=list,
        max_length=MAX_CHECKS,
        examples=[_CHECKS_EXAMPLE],
        description=_CHECKS_DESCRIPTION,
    )
    assignee: str | None = Field(
        default=None,
        max_length=MAX_ASSIGNEE_LENGTH,
        examples=["release_bot"],
        description=_ASSIGNEE_DESCRIPTION,
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=MAX_TAGS,
        examples=[["backend"]],
        description=_TAGS_DESCRIPTION,
    )
    priority: TaskPriority = Field(default=TaskPriority.NORMAL)


class TaskUpdate(BaseModel):
    """Частичное обновление: применяется только переданное.

    `assignee` объявлен как `str | None`: `null` осмыслен и снимает исполнителя. У
    остальных полей `null` смысла не имеет, и схема его не пропустит. Статуса здесь нет
    — он меняется переходом; ключа нет — он неизменяем. Лишнее поле схема отвергает, а
    не игнорирует: клиент должен узнать, что изменения не произошло, из ответа.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(min_length=1, max_length=MAX_TITLE_LENGTH, examples=[_TITLE_EXAMPLE])
    description: str = unset_field(
        min_length=1, max_length=MAX_TEXT_LENGTH, examples=[_DESCRIPTION_EXAMPLE]
    )
    goal: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    context: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    constraints: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    output: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    checks: list[str] = unset_field(
        max_length=MAX_CHECKS,
        examples=[_CHECKS_EXAMPLE],
        description=f"{_CHECKS_DESCRIPTION}. Replaces the whole list",
    )
    assignee: str | None = unset_field(
        max_length=MAX_ASSIGNEE_LENGTH,
        examples=["release_bot"],
        description=f"{_ASSIGNEE_DESCRIPTION}. Pass null to unassign",
    )
    tags: list[str] = unset_field(
        max_length=MAX_TAGS,
        examples=[["backend"]],
        description=f"{_TAGS_DESCRIPTION}. Replaces the whole set",
    )
    priority: TaskPriority = unset_field(examples=[TaskPriority.HIGH])
    version: int | None = Field(
        default=None,
        ge=1,
        examples=[3],
        description=(
            "Version the client last saw. Sent back it turns a lost update into a "
            "`version_conflict` instead of a silent overwrite; omit it to skip the check"
        ),
    )


class TaskTransition(BaseModel):
    """Перевод статуса по таблице переходов."""

    model_config = ConfigDict(extra="forbid")

    to: TaskStatus = Field(examples=[TaskStatus.OPEN], description="Target status")
    reason: str | None = Field(
        default=None,
        max_length=MAX_TEXT_LENGTH,
        examples=["Нужны уточнения по разделу context"],
        description=(
            "Why the task moves. Required for any step back along the chain and for "
            "`cancelled`; optional otherwise. Recorded in the `status_changed` entry"
        ),
    )
    version: int | None = Field(
        default=None,
        ge=1,
        examples=[3],
        description="Version the client last saw; omit it to skip the check",
    )
