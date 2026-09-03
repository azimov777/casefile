"""Схемы участников.

Из них же собирается OpenAPI, поэтому описания и примеры пишутся здесь, а не в роутере.
Все описания — на английском: это служебный слой контракта.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.domain.participants import PARTICIPANT_NAME_PATTERN, ParticipantKind

_DESCRIPTION_MAX = 1000


class ParticipantRead(BaseModel):
    """Участник в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ParticipantKind
    name: str = Field(examples=["release_bot"])
    description: str = Field(examples=["Релизный бот, ведёт задачи выкладки"])
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


class ParticipantUpdate(BaseModel):
    """Частичное обновление: применяется только переданное.

    Меняется одно описание. Имя стоит подписью в уже подшитых записях дела, а род
    объясняет читателю, кто говорит, — переписывать их задним числом значит переписывать
    историю, поэтому этих полей здесь нет вовсе, и лишнее поле схема отвергает.

    У описания нет осмысленного `null`, поэтому поле объявлено не-nullable: передать
    `null` схема не даст. Молча отбросить его было бы хуже отказа — клиент получил бы
    `200` и уверенность, что поле изменено.
    """

    model_config = ConfigDict(extra="forbid")

    description: str = unset_field(
        max_length=_DESCRIPTION_MAX,
        examples=["Релизный бот, ведёт задачи выкладки"],
    )
