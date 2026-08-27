"""Схемы справочников: статусы, типы задач, резолюции.

Адресация записи повторяет договорённость о полях: глобальная запись адресуется голым
ключом (`open`), локальная — с префиксом очереди (`TRK.open`). Поэтому в ответе есть и
`key` (что это за запись), и `ref` (как её запросить), и `queue` (чья она).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.domain.catalogs import (
    CATALOG_KEY_PATTERN,
    MAX_CATALOG_KEY_LENGTH,
    StatusCategory,
)
from app.services.catalogs import CatalogEntry, format_entry_ref

CatalogKeyField = Field(
    pattern=CATALOG_KEY_PATTERN,
    max_length=MAX_CATALOG_KEY_LENGTH,
    description="Latin lowercase key, unique within its scope",
)
CatalogNameField = Field(min_length=1, max_length=255)
# Шаблона здесь нет намеренно: поле адресует уже существующую очередь, а адресация
# в проекте мягкая — ключ приводится к каноническому виду в домене. Строгий шаблон
# стоит там, где ключ создаётся (`key` ниже): придумать кривой ключ нельзя.
QueueScopeField = Field(
    default=None,
    description="Queue key for a queue-local entry; omit for a global one",
)


class CatalogEntryRead(BaseModel):
    """Общая часть записи любого справочника."""

    id: uuid.UUID
    key: str = Field(examples=["open"], description="Key, unique within the scope")
    ref: str = Field(
        examples=["TRK.open"],
        description=(
            "Addressable reference: bare key for a global entry, `QUEUE.key` for a queue-local one"
        ),
    )
    queue: str | None = Field(
        default=None,
        examples=["TRK"],
        description="Owning queue key; null means the entry is global",
    )
    name: str = Field(examples=["Открыт"])
    is_active: bool = Field(
        description="Disabled entries stay in history but disappear from the queue configuration"
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def _base(cls, entry: CatalogEntry) -> dict[str, object]:
        """Общие поля записи. Ссылка собирается из самой записи, а не из контекста запроса."""
        return {
            "id": entry.id,
            "key": entry.key,
            "ref": format_entry_ref(entry),
            "queue": entry.queue.key if entry.queue_id is not None else None,
            "name": entry.name,
            "is_active": entry.is_active,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }


class StatusRead(CatalogEntryRead):
    """Статус задачи."""

    category: StatusCategory = Field(
        description="Machine meaning of the status; boards, progress and automation rely on it"
    )

    @classmethod
    def of(cls, entry: CatalogEntry) -> StatusRead:
        return cls(**cls._base(entry), category=entry.category)


class IssueTypeRead(CatalogEntryRead):
    """Тип задачи."""

    icon: str = Field(default="", examples=["bug"], description="Icon identifier for the frontend")

    @classmethod
    def of(cls, entry: CatalogEntry) -> IssueTypeRead:
        return cls(**cls._base(entry), icon=entry.icon)


class ResolutionRead(CatalogEntryRead):
    """Резолюция: чем закончилась задача."""

    @classmethod
    def of(cls, entry: CatalogEntry) -> ResolutionRead:
        return cls(**cls._base(entry))


class StatusCreate(BaseModel):
    """Создание статуса. Категория обязательна: без неё статус невидим для досок и автоматики."""

    model_config = ConfigDict(extra="forbid")

    key: str = CatalogKeyField
    name: str = CatalogNameField
    category: StatusCategory = Field(examples=[StatusCategory.IN_PROGRESS])
    queue: str | None = QueueScopeField


class StatusUpdate(BaseModel):
    """Частичное обновление статуса: применяются только переданные поля."""

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=255)
    is_active: bool = unset_field(description="Disable the status instead of deleting it")
    category: StatusCategory = unset_field(
        description="Rejected while issues sit in this status: it would redefine what `done` means"
    )


class IssueTypeCreate(BaseModel):
    """Создание типа задачи."""

    model_config = ConfigDict(extra="forbid")

    key: str = CatalogKeyField
    name: str = CatalogNameField
    icon: str = Field(default="", max_length=64, examples=["bug"])
    queue: str | None = QueueScopeField


class IssueTypeUpdate(BaseModel):
    """Частичное обновление типа задачи."""

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=255)
    is_active: bool = unset_field()
    icon: str = unset_field(max_length=64)


class ResolutionCreate(BaseModel):
    """Создание резолюции."""

    model_config = ConfigDict(extra="forbid")

    key: str = CatalogKeyField
    name: str = CatalogNameField
    queue: str | None = QueueScopeField


class ResolutionUpdate(BaseModel):
    """Частичное обновление резолюции."""

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=255)
    is_active: bool = unset_field()


class MoveIssuesRequest(BaseModel):
    """Перенос задач из одного статуса в другой — шаг перед удалением непустого статуса."""

    model_config = ConfigDict(extra="forbid")

    target_status: str = Field(
        examples=["TRK.backlog"],
        description="Reference of the status to move issues into",
    )
    queue: str | None = Field(
        default=None,
        description=(
            "Limit the move to a single queue; omit to move issues of every queue, "
            "which requires a global target status"
        ),
    )


class MoveIssuesResult(BaseModel):
    """Итог переноса: сколько задач переехало и куда."""

    source_status: str = Field(examples=["open"])
    target_status: str = Field(examples=["TRK.backlog"])
    moved: int = Field(description="Number of issues actually moved")
