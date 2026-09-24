"""Схемы проектов."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.domain.attributes import MAX_ATTRIBUTE_REASON_LENGTH, MAX_ATTRIBUTE_VALUE_LENGTH
from app.domain.projects import PROJECT_KEY_PATTERN

_TITLE_MAX = 255
_DESCRIPTION_MAX = 20_000


class ProjectRead(BaseModel):
    """Проект в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str = Field(examples=["TRK"])
    title: str = Field(examples=["Трекер"])
    description: str = Field(
        examples=["Бэкенд трекера. Код в `app/`, соглашения в `docs/CONVENTIONS.md`"],
        description="Markdown context shared by every task of the project",
    )
    last_task_number: int = Field(
        examples=[42],
        description="Last task number handed out; numbers are never reused",
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    """Создание проекта.

    Ключ принимается в любом регистре и хранится в верхнем: он идёт в ключ каждой задачи
    (`TRK-42`) и там обязан читаться как ключ. Уникальность — без учёта регистра.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=PROJECT_KEY_PATTERN,
        examples=["TRK"],
        description="Latin key, stored uppercase, immutable: it is part of every task key",
    )
    title: str = Field(min_length=1, max_length=_TITLE_MAX, examples=["Трекер"])
    description: str = Field(
        default="",
        max_length=_DESCRIPTION_MAX,
        examples=["Бэкенд трекера. Код в `app/`, соглашения в `docs/CONVENTIONS.md`"],
    )


class ProjectUpdate(BaseModel):
    """Частичное обновление: применяется только переданное.

    Поля `key` здесь нет и не будет: ключ вшит в ключ каждой задачи проекта, и правка
    задним числом порвала бы все уже записанные ссылки. Схема отвергает лишнее поле, а
    не игнорирует его молча — иначе клиент получил бы `200` на изменение, которого не
    было.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(min_length=1, max_length=_TITLE_MAX, examples=["Трекер"])
    description: str = unset_field(
        max_length=_DESCRIPTION_MAX,
        examples=["Бэкенд трекера. Код в `app/`, соглашения в `docs/CONVENTIONS.md`"],
    )


class AttributeRead(BaseModel):
    """Атрибут проекта: нынешнее значение. История — записями дела проекта."""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(
        examples=["repo"],
        description="Name as it was first set; matching ignores case",
    )
    value: str = Field(
        examples=["https://github.com/azimov777/casefile"],
        description="Plain text, not interpreted by the tracker",
    )
    created_at: datetime
    updated_at: datetime


class ProjectDetailRead(ProjectRead):
    """Один проект с нынешними значениями атрибутов.

    Отдельная модель, а не поле `ProjectRead`: список проектов и первый экран атрибутов
    не показывают, и запрос атрибутов на каждый проект списка стоил бы им без пользы.
    """

    attributes: list[AttributeRead] = Field(
        description=(
            "Current attribute values, ordered by name ignoring case. Every change is an "
            "entry of the project's case: `attribute_created`, `attribute_changed`, "
            "`attribute_removed`"
        )
    )


class AttributeSet(BaseModel):
    """Значение атрибута: заводит его или меняет нынешнее."""

    model_config = ConfigDict(extra="forbid")

    # Без `max_length`: длину проверяет домен, и длинное значение отвечает предметным
    # `attribute_value_too_long` одинаково в REST и в MCP, а не общим `validation_error`.
    value: str = Field(
        examples=["https://github.com/azimov777/casefile"],
        description=(
            f"Plain text up to {MAX_ATTRIBUTE_VALUE_LENGTH} characters, stored as sent; a "
            "longer one answers `attribute_value_too_long`. A value equal to the current "
            "one changes nothing and files no entry"
        ),
    )
    reason: str | None = Field(
        default=None,
        max_length=MAX_ATTRIBUTE_REASON_LENGTH,
        examples=["Репозиторий переехал в организацию"],
        description=(
            "Why the value changes. Required when the attribute already exists with "
            "another value (`attribute_reason_required`); optional when it is created"
        ),
    )


class AttributeRemoval(BaseModel):
    """Снятие атрибута: причина обязательна."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        max_length=MAX_ATTRIBUTE_REASON_LENGTH,
        examples=["Проект больше не публикуется в реестре"],
        description=(
            "Why the attribute is removed; a blank one answers `attribute_reason_required`. "
            "Recorded in the `attribute_removed` entry together with the last value"
        ),
    )
