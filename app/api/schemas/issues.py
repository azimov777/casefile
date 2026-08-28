"""Схемы задач.

Связанные объекты приезжают ссылками, а не вложенными записями: очередь — ключом
(`TRK`), статус, тип и резолюция — ссылками справочника (`open`, `TRK.open`), акторы —
ключами. Полные записи отдаёт конфигурация очереди и список акторов, и дублировать их в
каждой задаче значило бы рассылать одно и то же несколькими способами.

`values` — одно из двух мест контракта со свободной формой, разрешённых соглашениями
(второе — `details` ошибки). Форма не произвольная: она описана в `app/domain/fields.py`
и зависит от типа поля. Тип в схеме — `JsonValue`, а не `Any`: иначе весь блок приедет
на фронт как `Record<string, unknown>` и генерация клиента потеряет смысл.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.api.schemas.common import unset_field
from app.db.models.issue import Issue
from app.domain.issues import (
    MAX_SUMMARY_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    IssuePriority,
)
from app.services.catalogs import format_entry_ref

SummaryField = Field(
    min_length=1,
    max_length=MAX_SUMMARY_LENGTH,
    examples=["Починить выдачу ключей задач"],
    description="Single line: it is shown in lists, on board cards and in notifications",
)
DescriptionExample = "Ключ выдаётся до валидации и сгорает на неудачном запросе"
DescriptionText = "Empty string when there is no description"
CatalogRefDescription = (
    "Catalog reference: bare key for a global entry, `QUEUE.key` for a queue-local one"
)
DeadlineDescription = "ISO 8601 with a UTC offset; a value without a timezone is rejected"
TagsField = Field(
    max_length=MAX_TAGS,
    examples=[["release", "backend"]],
    description=(
        f"Flat labels, at most {MAX_TAGS} of {MAX_TAG_LENGTH} characters each. Order is "
        "kept, duplicates are dropped case-insensitively"
    ),
)
ProjectDescription = (
    "Key of the project the issue belongs to; null when it belongs to none. An issue is in "
    "at most one project, and the project may collect issues from several queues"
)
ValuesDescription = (
    "Custom field values keyed by field reference (`severity`, `TRK.severity`). The shape "
    "of each value depends on the field type and is documented in the field registry"
)


class IssueRead(BaseModel):
    """Задача в ответе."""

    id: uuid.UUID
    key: str = Field(examples=["TRK-123"], description="Immutable and never reused")
    queue: str = Field(examples=["TRK"], description="Key of the owning queue")
    issue_type: str = Field(examples=["bug"], description=CatalogRefDescription)
    status: str = Field(examples=["open"], description=CatalogRefDescription)
    resolution: str | None = Field(
        default=None,
        examples=["done"],
        description=f"{CatalogRefDescription}. Null while the issue is not resolved",
    )
    priority: IssuePriority = Field(examples=[IssuePriority.NORMAL])
    summary: str = SummaryField
    description: str = Field(examples=[DescriptionExample], description=DescriptionText)
    author: str = Field(examples=["alice"], description="Key of the actor who created the issue")
    assignee: str | None = Field(
        default=None,
        examples=["alice"],
        description="Key of the assigned actor; null when nobody is assigned",
    )
    followers: list[str] = Field(
        default_factory=list,
        examples=[["alice", "release_bot"]],
        description="Keys of the actors watching the issue, sorted",
    )
    deadline: datetime | None = Field(default=None, description=DeadlineDescription)
    tags: list[str] = TagsField
    project: str | None = Field(
        default=None,
        examples=["alpha"],
        description=ProjectDescription,
    )
    values: dict[str, JsonValue] = Field(default_factory=dict, description=ValuesDescription)
    version: int = Field(
        description="Grows with every actual change; send it back to detect a lost update"
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, issue: Issue) -> IssueRead:
        """Ссылки собираются из самих записей, а не из контекста запроса."""
        return cls(
            id=issue.id,
            key=issue.key,
            queue=issue.queue.key,
            issue_type=format_entry_ref(issue.issue_type),
            status=format_entry_ref(issue.status),
            resolution=None if issue.resolution is None else format_entry_ref(issue.resolution),
            priority=issue.priority,
            summary=issue.summary,
            description=issue.description,
            author=issue.author.key,
            assignee=None if issue.assignee is None else issue.assignee.key,
            followers=[follower.key for follower in issue.followers],
            deadline=issue.deadline,
            tags=list(issue.tags),
            project=None if issue.project is None else issue.project.key,
            values=issue.values,
            version=issue.version,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
        )


class IssueCreate(BaseModel):
    """Создание задачи.

    Ключа здесь нет: его выдаёт счётчик очереди, и придумать его клиент не может.
    Тип и статус берутся из настроек очереди, если не переданы.
    """

    model_config = ConfigDict(extra="forbid")

    queue: str = Field(examples=["TRK"], description="Key of the queue to create the issue in")
    summary: str = SummaryField
    description: str = Field(
        default="",
        examples=[DescriptionExample],
        description=DescriptionText,
    )
    issue_type: str | None = Field(
        default=None,
        examples=["bug"],
        description=f"{CatalogRefDescription}. Defaults to the queue default",
    )
    status: str | None = Field(
        default=None,
        examples=["open"],
        description=f"{CatalogRefDescription}. Defaults to the queue default",
    )
    resolution: str | None = Field(
        default=None,
        examples=["done"],
        description=f"{CatalogRefDescription}. Rarely set at creation",
    )
    priority: IssuePriority = Field(default=IssuePriority.NORMAL)
    author: str | None = Field(
        default=None,
        description="Author actor key; defaults to the actor behind the token",
    )
    assignee: str | None = Field(default=None, examples=["alice"])
    followers: list[str] = Field(default_factory=list, examples=[["release_bot"]])
    deadline: datetime | None = Field(default=None, description=DeadlineDescription)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    project: str | None = Field(default=None, examples=["alpha"], description=ProjectDescription)
    values: dict[str, JsonValue] = Field(default_factory=dict, description=ValuesDescription)


class IssueUpdate(BaseModel):
    """Частичное обновление задачи: применяются только переданные поля.

    Три поля объявлены как `T | None` — `resolution`, `assignee` и `deadline`. У них
    `null` осмыслен и означает «очистить»; у остальных полей `null` смысла не имеет, и
    схема его не пропустит. Различать «не передано» и «передано как null» обязательно:
    иначе частичное обновление либо не даст снять исполнителя, либо будет затирать его
    при каждом изменении названия.

    Ключа и очереди здесь нет: ключ неизменяем, а перенос задачи между очередями в v1
    не делается. Наблюдатели меняются своими эндпоинтами — добавление и удаление по
    одному не должны зависеть от того, кого клиент видел в списке.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = unset_field(min_length=1, max_length=MAX_SUMMARY_LENGTH)
    description: str = unset_field(description="Pass an empty string to clear the description")
    issue_type: str = unset_field(description=CatalogRefDescription)
    status: str = unset_field(description=CatalogRefDescription)
    resolution: str | None = unset_field(
        description=f"{CatalogRefDescription}. Pass null to clear the resolution"
    )
    priority: IssuePriority = unset_field()
    assignee: str | None = unset_field(description="Actor key, or null to unassign")
    deadline: datetime | None = unset_field(
        description=f"{DeadlineDescription}. Pass null to drop the deadline"
    )
    tags: list[str] = unset_field(max_length=MAX_TAGS, description="Replaces the whole set")
    project: str | None = unset_field(
        description=f"{ProjectDescription}. Pass null to take the issue out of its project"
    )
    values: dict[str, JsonValue] = unset_field(
        description=(
            f"{ValuesDescription}. Partial: a null value clears the field, a key that is "
            "not sent leaves it alone"
        )
    )
    version: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Version the client last saw. Sent back it turns a lost update into a "
            "`version_conflict` instead of a silent overwrite; omit it to skip the check"
        ),
    )


class IssueAssign(BaseModel):
    """Назначение исполнителя. `null` снимает его."""

    model_config = ConfigDict(extra="forbid")

    assignee: str | None = Field(examples=["alice"], description="Actor key, or null to unassign")
    version: int | None = Field(
        default=None,
        ge=1,
        description="Version the client last saw; omit it to skip the check",
    )


class IssueFollowerAdd(BaseModel):
    """Добавление наблюдателя."""

    model_config = ConfigDict(extra="forbid")

    actor: str = Field(examples=["release_bot"], description="Key of the actor to start watching")
