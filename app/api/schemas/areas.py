"""Схемы областей проекта (`CONCEPT.md`, 3.7)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.api.schemas.projects import AreaRefRead, AttributeRead
from app.db.models.area import Area
from app.domain.areas import (
    AREA_KEY_PATTERN,
    MAX_AREA_DESCRIPTION_LENGTH,
    MAX_AREA_REASON_LENGTH,
)

_TITLE_MAX = 255
_DESCRIPTION_EXAMPLE = "Каталоги, публикации и день запуска"
# Без `max_length`: длину проверяет домен, и длинное описание отвечает предметным
# `area_description_too_long` одинаково в REST и в MCP, а не общим `validation_error`.
_DESCRIPTION_RULE = (
    f'Short "what this is", up to {MAX_AREA_DESCRIPTION_LENGTH} characters after '
    "trimming; a longer one answers `area_description_too_long`"
)
_ADDRESS_DESCRIPTION = (
    "Address of the area: the project key and the area key, `TRK/promotion`. "
    "References to its case entries are `TRK/promotion#3`"
)


class AreaRead(BaseModel):
    """Область в ответе: карточка."""

    id: uuid.UUID
    project_key: str = Field(
        examples=["TRK"], description="Key of the project the area lives in; never changes"
    )
    key: str = Field(
        examples=["promotion"],
        description="Area key inside its project, lower-case; never changes",
    )
    address: str = Field(examples=["TRK/promotion"], description=_ADDRESS_DESCRIPTION)
    title: str = Field(examples=["Популяризация"])
    description: str = Field(
        examples=[_DESCRIPTION_EXAMPLE],
        description=(
            f'Short "what this is", up to {MAX_AREA_DESCRIPTION_LENGTH} characters; may be empty'
        ),
    )
    archived_at: datetime | None = Field(
        examples=[None],
        description=(
            "When the area was archived; `null` while it is active. An archived "
            "area is frozen: every change of its card, attributes and case answers "
            "`409 area_archived`, except `restore`. Reading works as usual"
        ),
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime


class AreaDetailRead(AreaRead):
    """Одна область с нынешними значениями атрибутов.

    Отдельная модель по той же причине, что у проекта (`ProjectDetailRead`): список
    областей атрибутов не показывает.
    """

    attributes: list[AttributeRead] = Field(
        description=(
            "Current attribute values, ordered by name ignoring case. Every change is an "
            "entry of the area's case: `attribute_created`, `attribute_changed`, "
            "`attribute_removed`"
        )
    )


def area_read(area: Area) -> AreaRead:
    """Карточка области: ключ проекта и адрес собираются из связи с проектом."""
    return AreaRead(
        id=area.id,
        project_key=area.project.key,
        key=area.key,
        address=area.address,
        title=area.title,
        description=area.description,
        archived_at=area.archived_at,
        created_by=AuthorRead.model_validate(area.created_by),
        created_at=area.created_at,
        updated_at=area.updated_at,
    )


def area_ref(area: Area) -> AreaRefRead:
    """Область строкой: адрес и название."""
    return AreaRefRead(address=area.address, title=area.title)


class AreaCreate(BaseModel):
    """Создание области в проекте из пути.

    Ключ принимается в любом регистре и хранится в нижнем; уникален внутри проекта без
    учёта регистра и дальше неизменяем.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        examples=["promotion"],
        description=(
            "Area key: lower-case Latin letters, digits and hyphens, starting and ending "
            "with a letter or a digit (`invalid_area_key` otherwise; the pattern is "
            f"`{AREA_KEY_PATTERN}` after lower-casing). Stored lower-case, never changes; "
            "a key taken in the project, in any case, answers `409 area_key_taken`"
        ),
    )
    title: str = Field(min_length=1, max_length=_TITLE_MAX, examples=["Популяризация"])
    description: str = Field(
        default="", examples=[_DESCRIPTION_EXAMPLE], description=_DESCRIPTION_RULE
    )


class AreaUpdate(BaseModel):
    """Частичное обновление: применяется только переданное. Ключа и проекта здесь нет —
    они неизменяемы, и схема отвергает лишнее поле, а не игнорирует его молча."""

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(min_length=1, max_length=_TITLE_MAX, examples=["Популяризация"])
    description: str = unset_field(examples=[_DESCRIPTION_EXAMPLE], description=_DESCRIPTION_RULE)


class AreaArchiving(BaseModel):
    """Архивирование или восстановление области: причина обязательна в обе стороны."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        max_length=MAX_AREA_REASON_LENGTH,
        examples=["Область закрыта: работа перешла в коммерцию"],
        description=(
            "Why the area is archived or restored; a blank one answers "
            "`422 area_reason_required`. Filed in the `archived` or `restored` entry of "
            "the area's case"
        ),
    )
