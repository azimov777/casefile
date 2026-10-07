"""Схемы участников.

Из них же собирается OpenAPI, поэтому описания и примеры пишутся здесь, а не в роутере.
Все описания — на английском: это служебный слой контракта.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.domain.participants import PARTICIPANT_NAME_PATTERN, ParticipantKind

_DESCRIPTION_MAX = 1000


class ParticipantRead(BaseModel):
    """Участник в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ParticipantKind
    name: str = Field(examples=["release_bot"])
    description: str = Field(examples=["Релизный бот, ведёт задачи выкладки"])
    owner: str | None = Field(
        default=None,
        validation_alias="owner_name",
        description=(
            "Name of the human this agent belongs to; null for humans, shared agents "
            "and local agents without an owner"
        ),
        examples=["alice"],
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime


class ParticipantCreate(BaseModel):
    """Регистрация участника.

    Имя принимается в любом регистре и хранится в нижнем: имена уникальны без учёта
    регистра, и шаблон «только нижний регистр» отвечал бы на попытку занять `Alice` при
    существующем `alice` разговором о форме строки вместо ответа «имя занято».
    """

    model_config = ConfigDict(extra="forbid")

    kind: ParticipantKind = Field(examples=[ParticipantKind.AGENT])
    name: str = Field(
        pattern=PARTICIPANT_NAME_PATTERN,
        examples=["release_bot"],
        description="Latin snake_case name; stored lowercase and unique case-insensitively",
    )
    description: str = Field(
        default="",
        max_length=_DESCRIPTION_MAX,
        examples=["Релизный бот, ведёт задачи выкладки"],
        description="Short note on who this is: it is all the reader of a case knows about them",
    )
