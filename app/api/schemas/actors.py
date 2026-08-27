"""Схемы акторов и токенов доступа.

Из них же собирается OpenAPI, поэтому описания и примеры пишутся здесь, а не в роутере.
Все описания — на английском: это служебный слой контракта.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
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
    """Частичное обновление: применяются только переданные поля.

    Ни у имени, ни у признака активности нет осмысленного `null`, поэтому оба поля
    объявлены не-nullable: передать `null` схема не даст. Молча отбросить его было бы
    хуже отказа — клиент получил бы 200 и уверенность, что поле изменено.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str = unset_field(min_length=1, max_length=255, examples=["Релизный бот"])
    is_active: bool = unset_field(
        description="Deactivated actor keeps its history but can no longer authenticate",
    )


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
