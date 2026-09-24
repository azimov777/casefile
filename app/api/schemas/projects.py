"""Схемы проектов."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
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
