"""Схемы акторов и токенов доступа.

Из них же собирается OpenAPI, поэтому описания и примеры пишутся здесь, а не в роутере.
Все описания — на английском: это служебный слой контракта.
"""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.actors import ACTOR_KEY_PATTERN, ActorType


class ActorRead(BaseModel):
    """Актор в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: ActorType
    key: str = Field(examples=["release_bot"])
    display_name: str = Field(examples=["Релизный бот"])
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ActorCreate(BaseModel):
    """Создание актора. Тип `system` отклоняется: системный актор создаётся миграцией."""

    model_config = ConfigDict(extra="forbid")

    type: ActorType = Field(examples=[ActorType.AGENT])
    key: str = Field(
        pattern=ACTOR_KEY_PATTERN,
        examples=["release_bot"],
        description="Latin lowercase key, unique across the installation",
    )
    display_name: str = Field(min_length=1, max_length=255, examples=["Релизный бот"])


class ActorUpdate(BaseModel):
    """Частичное обновление: применяются только переданные поля."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = Field(
        default=None,
        description="Deactivated actor keeps its history but can no longer authenticate",
    )

    @model_validator(mode="after")
    def _reject_explicit_null(self) -> Self:
        """Явный `null` — ошибка, а не «поле не передано».

        Ни у имени, ни у признака активности нет осмысленного `null`, поэтому склеить
        эти два случая было бы молчаливым сбоем: клиент получил бы 200 и уверенность,
        что поле изменено. Отличать «не передано» от «передано как null» по-настоящему
        придётся в задаче 05 — там `null` у полей задачи означает «очистить».

        `None` в объявлении остаётся только как значение «не передано»; сюда оно
        попадает уже отфильтрованным по `model_fields_set`.
        """
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if nulled:
            raise ValueError(f"fields cannot be null: {', '.join(nulled)}")
        return self


class ApiTokenRead(BaseModel):
    """Токен без секрета: секрет показывается один раз при выпуске и больше нигде."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str = Field(examples=["laptop"])
    created_at: datetime
    last_used_at: datetime | None = Field(
        default=None,
        description="Updated at most once a minute to keep reads from becoming writes",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="Set when the token is revoked; the record stays for the audit trail",
    )


class ApiTokenCreate(BaseModel):
    """Выпуск токена: имя нужно, чтобы потом понять, какой из них отзывать."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255, examples=["release-bot on ci"])


class ApiTokenIssued(ApiTokenRead):
    """Ответ на выпуск токена: единственное место, где секрет виден целиком."""

    secret: str = Field(
        examples=["trk_0oUCtWtA6d9v0j0N1cMBAxk2wKAKopWzvbf_wQ8sDLc"],
        description="Full token value, shown once and never stored in plain text",
    )
