"""Схемы токенов доступа."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.authors import AuthorRead
from app.domain.participants import PARTICIPANT_NAME_PATTERN
from app.domain.tokens import TokenScope


class TokenRead(BaseModel):
    """Токен без секрета: секрет показывается один раз при выпуске и больше нигде."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str = Field(examples=["release-bot on ci"])
    scope: TokenScope = Field(examples=[TokenScope.TASK])
    participant: str | None = Field(
        default=None,
        examples=["release_bot"],
        description=(
            "Name of the participant this token belongs to; null makes it a shared agent "
            "token, which must carry the X-Actor-Label header on every request"
        ),
    )
    created_by: AuthorRead
    created_at: datetime
    last_used_at: datetime | None = Field(
        default=None,
        description="Updated at most once a minute to keep reads from becoming writes",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="Set when the token is revoked; the record stays for the audit trail",
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Set only on a browser session token, issued by `POST /api/v1/session`: after "
            "this moment it answers `401 unauthorized` with `details.reason: token_expired`. "
            "Null means the token lives until it is revoked"
        ),
    )

    @field_validator("participant", mode="before")
    @classmethod
    def _participant_name(cls, value: object) -> object:
        """В ответе стоит имя участника, а не вложенный объект.

        Разворачивать связь незачем: у списка токенов один вопрос — чей это доступ, — а
        карточка участника доступна отдельным маршрутом. Отдавать здесь `null` вместо
        отсутствующего объекта заодно делает общий агентский токен видимым с первого
        взгляда.
        """
        return getattr(value, "name", value)


class TokenCreate(BaseModel):
    """Выпуск токена.

    Без `participant` получается **общий агентский** токен: он не называет автора сам, и
    каждый запрос с ним обязан нести заголовок `X-Actor-Label` с меткой временного
    агента. Так работают агенты, которых незачем заводить в реестре.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        examples=["release-bot on ci"],
        description="Free-form note to tell tokens apart when revoking one",
    )
    scope: TokenScope = Field(
        default=TokenScope.TASK,
        examples=[TokenScope.TASK],
        description="`task` opens the working cycle, `main` adds writes to registries",
    )
    participant: str | None = Field(
        default=None,
        pattern=PARTICIPANT_NAME_PATTERN,
        examples=["release_bot"],
        description="Participant this token speaks for; omit it to issue a shared agent token",
    )


class TokenIssued(TokenRead):
    """Ответ на выпуск токена: единственное место, где секрет виден целиком."""

    secret: str = Field(
        examples=["trk_0oUCtWtA6d9v0j0N1cMBAxk2wKAKopWzvbf_wQ8sDLc"],
        description="Full token value, shown once and never stored in plain text",
    )


class CurrentTokenRead(BaseModel):
    """Токен, которым сделан запрос: чем узнать его в списке и что он открывает.

    Не `TokenRead`: имя, автор выпуска и последнее использование первому кадру не нужны,
    а список токенов отдаёт их по тому же `id`. Секрета и хеша здесь нет, как и там.
    """

    id: uuid.UUID = Field(
        description=(
            "Identifier of the token this request was made with, the same `id` that "
            "`GET /api/v1/tokens` lists: this is how a client finds its own key there"
        ),
    )
    scope: TokenScope = Field(
        examples=[TokenScope.TASK],
        description=(
            "Scope of that token, the only right in the tracker: `task` opens the working "
            "cycle, `main` adds writes to projects, participants and tokens. A write beyond "
            "it answers `403 permission_denied`"
        ),
    )
