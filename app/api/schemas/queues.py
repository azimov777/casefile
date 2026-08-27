"""Схемы очередей и их конфигурации.

Справочники в ответах очереди адресуются ссылками (`open`, `TRK.open`), а не вложенными
объектами: полные записи отдаёт конфигурация очереди, и дублировать их в каждом ответе
значило бы рассылать одно и то же несколькими способами.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.catalogs import IssueTypeRead, ResolutionRead, StatusRead
from app.api.schemas.common import unset_field
from app.db.models.queue import Queue
from app.domain.queues import MAX_QUEUE_KEY_LENGTH, QUEUE_KEY_PATTERN
from app.services.catalogs import format_entry_ref
from app.services.queues import QueueConfig

CatalogRefField = Field(
    examples=["open"],
    description="Catalog reference: bare key for a global entry, `QUEUE.key` for a queue-local one",
)


class QueueRead(BaseModel):
    """Очередь в ответе."""

    id: uuid.UUID
    key: str = Field(examples=["TRK"], description="Immutable: issue keys are built from it")
    name: str = Field(examples=["Трекер"])
    description: str = Field(default="", description="Empty string when there is no description")
    owner: str = Field(examples=["owner"], description="Key of the owning actor")
    default_issue_type: str = CatalogRefField
    default_status: str = CatalogRefField
    last_issue_number: int = Field(
        description="Number of the last issue key handed out; the next issue gets this plus one"
    )
    is_archived: bool = Field(
        description="Archived queues keep everything but accept no new issues"
    )
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, queue: Queue) -> QueueRead:
        return cls(
            id=queue.id,
            key=queue.key,
            name=queue.name,
            description=queue.description,
            owner=queue.owner.key,
            default_issue_type=format_entry_ref(queue.default_issue_type),
            default_status=format_entry_ref(queue.default_status),
            last_issue_number=queue.last_issue_number,
            is_archived=queue.is_archived,
            archived_at=queue.archived_at,
            created_at=queue.created_at,
            updated_at=queue.updated_at,
        )


class QueueCreate(BaseModel):
    """Создание очереди.

    Всё, кроме ключа и названия, необязательно: не переданное берётся из глобальных
    справочников, чтобы в очереди сразу можно было завести задачу.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=QUEUE_KEY_PATTERN,
        max_length=MAX_QUEUE_KEY_LENGTH,
        examples=["TRK"],
        description="Uppercase latin key, unique and immutable once created",
    )
    name: str = Field(min_length=1, max_length=255, examples=["Трекер"])
    description: str = Field(default="", examples=["Задачи по разработке трекера"])
    owner: str | None = Field(
        default=None,
        description="Owner actor key; defaults to the actor behind the token",
    )
    issue_types: list[str] | None = Field(
        default=None,
        examples=[["task", "bug"]],
        description="Global issue type keys allowed in the queue; defaults to every active one",
    )
    default_issue_type: str | None = Field(default=None, examples=["task"])
    default_status: str | None = Field(default=None, examples=["open"])


class QueueUpdate(BaseModel):
    """Частичное обновление очереди: применяются только переданные поля.

    Ключа здесь нет намеренно — он неизменяем: на нём построены ключи уже заведённых
    задач.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=255)
    description: str = unset_field(description="Pass an empty string to clear the description")
    owner: str = unset_field(description="Key of an existing actor")
    default_issue_type: str = unset_field(description="Must be allowed in this queue")
    default_status: str = unset_field(description="Must be global or local to this queue")


class QueueIssueTypesUpdate(BaseModel):
    """Замена набора типов задач очереди целиком."""

    model_config = ConfigDict(extra="forbid")

    issue_types: list[str] = Field(
        min_length=1,
        examples=[["task", "bug", "TRK.incident"]],
        description="Complete set of issue type references allowed in the queue",
    )


class QueueFieldStub(BaseModel):
    """Заглушка локального поля очереди.

    Реестра полей ещё нет — он появится в задаче 04, которая заменит эту модель
    настоящей. Ключ в конфигурации присутствует уже сейчас и всегда содержит пустой
    список: клиент, написанный сегодня, не должен переписываться завтра только потому,
    что в ответе появилось новое поле.
    """

    key: str
    name: str


class QueueWorkflowStub(BaseModel):
    """Заглушка воркфлоу очереди. Задача 07 заменит модель настоящим графом переходов."""

    issue_type: str
    name: str


class QueueConfigRead(BaseModel):
    """Конфигурация очереди целиком — всё, что нужно, чтобы завести в ней задачу.

    Один запрос вместо четырёх: это основной источник данных для формы создания задачи
    во фронтенде и для агента, который впервые видит очередь. Записи только активные.
    """

    queue: QueueRead
    issue_types: list[IssueTypeRead] = Field(description="Issue types allowed in this queue")
    statuses: list[StatusRead] = Field(description="Global statuses plus the queue's own")
    resolutions: list[ResolutionRead] = Field(description="Global resolutions plus the queue's own")
    fields: list[QueueFieldStub] = Field(
        default_factory=list,
        description="Always empty until the field registry lands (task 04)",
    )
    workflows: list[QueueWorkflowStub] = Field(
        default_factory=list,
        description="Always empty until workflows land (task 07)",
    )

    @classmethod
    def of(cls, config: QueueConfig) -> QueueConfigRead:
        return cls(
            queue=QueueRead.of(config.queue),
            issue_types=[IssueTypeRead.of(entry) for entry in config.issue_types],
            statuses=[StatusRead.of(entry) for entry in config.statuses],
            resolutions=[ResolutionRead.of(entry) for entry in config.resolutions],
        )
