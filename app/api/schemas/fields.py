"""Схемы реестра полей.

Адресация поля повторяет договорённость справочников: глобальное поле адресуется голым
ключом (`severity`), локальное — с префиксом очереди (`TRK.severity`). Поэтому в ответе
есть и `key` (что это за поле), и `ref` (как его запросить), и `queue` (чьё оно).

`default_value` и значения задачи — единственные места контракта со свободной формой,
и обе разрешены соглашениями явно. Форма не произвольная: она описана в
`app/domain/fields.py` и зависит от типа поля. Тип в схеме — `JsonValue`, а не `Any`:
так в OpenAPI попадает настоящий JSON-тип, а не «объект неизвестной формы».
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.api.schemas.common import unset_field
from app.db.models.field import Field as FieldModel
from app.domain.fields import (
    FIELD_KEY_PATTERN,
    MAX_ENUM_OPTIONS,
    MAX_FIELD_KEY_LENGTH,
    FieldOption,
    FieldValueType,
)
from app.services.catalogs import format_entry_ref
from app.services.fields import field_ref

FieldKeyField = Field(
    pattern=FIELD_KEY_PATTERN,
    max_length=MAX_FIELD_KEY_LENGTH,
    examples=["severity"],
    description="Latin lowercase key, unique within its scope and immutable once created",
)
FieldNameField = Field(min_length=1, max_length=255, examples=["Серьёзность"])
# Шаблона здесь нет намеренно: поле адресует уже существующую очередь, а адресация
# в проекте мягкая — ключ приводится к каноническому виду в домене.
QueueScopeField = Field(
    default=None,
    examples=["TRK"],
    description="Queue key for a queue-local field; omit for a global one",
)
DefaultValueDescription = (
    "Value applied when the issue does not carry this field; stored in the same shape "
    "as the value itself, so a multiple field takes an array"
)
IssueTypesDescription = (
    "Issue type references the field applies to; an empty list means every issue type"
)


class FieldOptionSchema(BaseModel):
    """Вариант перечисления: машинный ключ и отображаемое название.

    В задаче хранится ключ, а не название: название переименовывают, ключ — нет.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=FIELD_KEY_PATTERN,
        max_length=MAX_FIELD_KEY_LENGTH,
        examples=["critical"],
    )
    name: str = Field(min_length=1, max_length=255, examples=["Критическая"])


class FieldRead(BaseModel):
    """Поле реестра в ответе."""

    id: uuid.UUID
    key: str = Field(examples=["severity"], description="Key, unique within the scope")
    ref: str = Field(
        examples=["TRK.severity"],
        description=(
            "Addressable reference and the key under which the value is stored in "
            "`issue.values`: bare key for a global field, `QUEUE.key` for a queue-local one"
        ),
    )
    queue: str | None = Field(
        default=None,
        examples=["TRK"],
        description="Owning queue key; null means the field is global",
    )
    name: str = Field(examples=["Серьёзность"])
    value_type: FieldValueType = Field(description="Determines both validation and JSONB shape")
    is_multiple: bool = Field(description="Multiple fields store an array of values")
    is_required: bool = Field(description="An issue cannot be saved without this field")
    is_hidden: bool = Field(
        description=(
            "Hidden fields keep their data and history but disappear from the queue "
            "configuration and accept no new values"
        )
    )
    options: list[FieldOptionSchema] = Field(
        default_factory=list,
        description="Allowed values of an enum field, in display order",
    )
    default_value: JsonValue = Field(default=None, description=DefaultValueDescription)
    display_order: int = Field(description="Display position within the queue configuration")
    issue_types: list[str] = Field(
        default_factory=list,
        examples=[["bug"]],
        description=IssueTypesDescription,
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, field: FieldModel) -> FieldRead:
        """Ссылка собирается из самой записи, а не из контекста запроса."""
        return cls(
            id=field.id,
            key=field.key,
            ref=field_ref(field),
            queue=field.queue.key if field.queue_id is not None else None,
            name=field.name,
            value_type=field.value_type,
            is_multiple=field.is_multiple,
            is_required=field.is_required,
            is_hidden=field.is_hidden,
            options=[FieldOptionSchema(**option) for option in field.options],
            default_value=field.default_value,
            display_order=field.display_order,
            issue_types=[format_entry_ref(entry) for entry in field.issue_types],
            created_at=field.created_at,
            updated_at=field.updated_at,
        )


class FieldCreate(BaseModel):
    """Создание поля.

    Тип и множественность выбираются здесь и у поля с данными потом не меняются:
    уже записанные значения задним числом стали бы значить другое.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = FieldKeyField
    name: str = FieldNameField
    value_type: FieldValueType = Field(examples=[FieldValueType.ENUM])
    queue: str | None = QueueScopeField
    is_multiple: bool = Field(default=False)
    is_required: bool = Field(default=False)
    options: list[FieldOptionSchema] = Field(
        default_factory=list,
        max_length=MAX_ENUM_OPTIONS,
        description="Required for an enum field and rejected for every other type",
    )
    default_value: JsonValue = Field(default=None, description=DefaultValueDescription)
    display_order: int = Field(default=0)
    issue_types: list[str] | None = Field(
        default=None,
        examples=[["bug"]],
        description=IssueTypesDescription,
    )


class FieldUpdate(BaseModel):
    """Частичное обновление поля: применяются только переданные поля.

    Ключа здесь нет намеренно — он неизменяем: под ним лежат значения в задачах,
    и переименование порвало бы все ссылки разом.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=255)
    is_required: bool = unset_field()
    is_hidden: bool = unset_field(
        description="Soft delete: the only way to retire a field that already has values"
    )
    value_type: FieldValueType = unset_field(
        description="Rejected while issues carry values of this field"
    )
    is_multiple: bool = unset_field(
        description="Rejected while issues carry values of this field: the JSONB shape changes"
    )
    options: list[FieldOptionSchema] = unset_field(
        max_length=MAX_ENUM_OPTIONS,
        description="Replaces the whole option set; an option still in use cannot be dropped",
    )
    default_value: JsonValue = unset_field(
        description=f"{DefaultValueDescription}. Pass null to drop the default"
    )
    display_order: int = unset_field()
    issue_types: list[str] = unset_field(
        description=f"{IssueTypesDescription}. Replaces the whole set"
    )

    def changes(self) -> dict[str, Any]:
        """Переданные поля в терминах сценария.

        Варианты перечисления превращаются в доменные объекты здесь: сценарий не
        должен разбирать словари, пришедшие из HTTP, — его вызывает ещё и MCP.
        """
        changed = self.model_dump(exclude_unset=True)
        if "options" in changed:
            changed["options"] = [
                FieldOption(key=option["key"], name=option["name"]) for option in changed["options"]
            ]
        return changed
