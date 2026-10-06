"""Схемы направлений проекта (`CONCEPT.md`, 3.7)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.api.schemas.projects import AttributeRead, DirectionRefRead
from app.db.models.direction import Direction
from app.domain.directions import (
    DIRECTION_KEY_PATTERN,
    MAX_DIRECTION_DESCRIPTION_LENGTH,
    MAX_DIRECTION_REASON_LENGTH,
)

_TITLE_MAX = 255
_DESCRIPTION_EXAMPLE = "Каталоги, публикации и день запуска"
# Без `max_length`: длину проверяет домен, и длинное описание отвечает предметным
# `direction_description_too_long` одинаково в REST и в MCP, а не общим `validation_error`.
_DESCRIPTION_RULE = (
    f'Short "what this is", up to {MAX_DIRECTION_DESCRIPTION_LENGTH} characters after '
    "trimming; a longer one answers `direction_description_too_long`"
)
_ADDRESS_DESCRIPTION = (
    "Address of the direction: the project key and the direction key, `TRK/promotion`. "
    "References to its case entries are `TRK/promotion#3`"
)


class DirectionRead(BaseModel):
    """Направление в ответе: карточка."""

    id: uuid.UUID
    project_key: str = Field(
        examples=["TRK"], description="Key of the project the direction lives in; never changes"
    )
    key: str = Field(
        examples=["promotion"],
        description="Direction key inside its project, lower-case; never changes",
    )
    address: str = Field(examples=["TRK/promotion"], description=_ADDRESS_DESCRIPTION)
    title: str = Field(examples=["Популяризация"])
    description: str = Field(
        examples=[_DESCRIPTION_EXAMPLE],
        description=(
            f'Short "what this is", up to {MAX_DIRECTION_DESCRIPTION_LENGTH} characters; may '
            "be empty"
        ),
    )
    archived_at: datetime | None = Field(
        examples=[None],
        description=(
            "When the direction was archived; `null` while it is active. An archived "
            "direction is frozen: every change of its card, attributes and case answers "
            "`409 direction_archived`, except `restore`. Reading works as usual"
        ),
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime


class DirectionDetailRead(DirectionRead):
    """Одно направление с нынешними значениями атрибутов.

    Отдельная модель по той же причине, что у проекта (`ProjectDetailRead`): список
    направлений атрибутов не показывает.
    """

    attributes: list[AttributeRead] = Field(
        description=(
            "Current attribute values, ordered by name ignoring case. Every change is an "
            "entry of the direction's case: `attribute_created`, `attribute_changed`, "
            "`attribute_removed`"
        )
    )


def direction_read(direction: Direction) -> DirectionRead:
    """Карточка направления: ключ проекта и адрес собираются из связи с проектом."""
    return DirectionRead(
        id=direction.id,
        project_key=direction.project.key,
        key=direction.key,
        address=direction.address,
        title=direction.title,
        description=direction.description,
        archived_at=direction.archived_at,
        created_by=AuthorRead.model_validate(direction.created_by),
        created_at=direction.created_at,
        updated_at=direction.updated_at,
    )


def direction_ref(direction: Direction) -> DirectionRefRead:
    """Направление строкой: адрес и название."""
    return DirectionRefRead(address=direction.address, title=direction.title)


class DirectionCreate(BaseModel):
    """Создание направления в проекте из пути.

    Ключ принимается в любом регистре и хранится в нижнем; уникален внутри проекта без
    учёта регистра и дальше неизменяем.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        examples=["promotion"],
        description=(
            "Direction key: lower-case Latin letters, digits and hyphens, starting and ending "
            "with a letter or a digit (`invalid_direction_key` otherwise; the pattern is "
            f"`{DIRECTION_KEY_PATTERN}` after lower-casing). Stored lower-case, never changes; "
            "a key taken in the project, in any case, answers `409 direction_key_taken`"
        ),
    )
    title: str = Field(min_length=1, max_length=_TITLE_MAX, examples=["Популяризация"])
    description: str = Field(
        default="", examples=[_DESCRIPTION_EXAMPLE], description=_DESCRIPTION_RULE
    )


class DirectionUpdate(BaseModel):
    """Частичное обновление: применяется только переданное. Ключа и проекта здесь нет —
    они неизменяемы, и схема отвергает лишнее поле, а не игнорирует его молча."""

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(min_length=1, max_length=_TITLE_MAX, examples=["Популяризация"])
    description: str = unset_field(examples=[_DESCRIPTION_EXAMPLE], description=_DESCRIPTION_RULE)


class DirectionArchiving(BaseModel):
    """Архивирование или восстановление направления: причина обязательна в обе стороны."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        max_length=MAX_DIRECTION_REASON_LENGTH,
        examples=["Направление закрыто: работа перешла в коммерцию"],
        description=(
            "Why the direction is archived or restored; a blank one answers "
            "`422 direction_reason_required`. Filed in the `archived` or `restored` entry of "
            "the direction's case"
        ),
    )
