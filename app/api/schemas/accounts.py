"""Схемы учётных записей (`docs/CONCEPT.md`, 3.1 и 5.4)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.domain.accounts import MAX_EMAIL_LENGTH
from app.domain.participants import PARTICIPANT_NAME_PATTERN
from app.domain.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

_DESCRIPTION_MAX = 1000

_EMAIL_DESCRIPTION = (
    "Email the person signs in with; stored lowercase and unique case-insensitively. It "
    "is only a sign-in name: the tracker sends no mail and does not confirm addresses"
)
_NEW_PASSWORD_DESCRIPTION = (
    f"New password, {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters. Omit it "
    "and the tracker generates one and returns it once in `password`"
)


class AccountRead(BaseModel):
    """Учётная запись в ответе. Хеша пароля здесь нет — есть только признак, задан ли он."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str = Field(examples=["alice@example.com"], description=_EMAIL_DESCRIPTION)
    participant: str = Field(
        examples=["alice"],
        description=(
            "Name of the human participant this account signs in as: the name that "
            "signs every entry the person makes"
        ),
    )
    is_admin: bool = Field(
        description=(
            "Administrator flag: opens managing accounts and nothing else. It gives no "
            "rights on tasks: everyone signed in sees everything"
        ),
    )
    has_password: bool = Field(
        description=(
            "Whether a password is set. False on the account the installation creates for "
            "itself (`owner@localhost`): on the own machine its key arrives without a sign-in"
        ),
    )
    disabled_at: datetime | None = Field(
        default=None,
        description=(
            "When the account was disabled: it cannot sign in and all its tokens are "
            "revoked. The participant and its signatures stay. Null means active"
        ),
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime

    @field_validator("participant", mode="before")
    @classmethod
    def _participant_name(cls, value: object) -> object:
        """Имя участника, а не вложенный объект: карточка участника — свой маршрут."""
        return getattr(value, "name", value)


class AccountCreate(BaseModel):
    """Заведение учётной записи администратором.

    Участник с именем `name` уже есть — учётная запись достаётся ему, если он человек и
    своей у него ещё нет. Нет — заводится новый участник-человек.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        min_length=3,
        max_length=MAX_EMAIL_LENGTH,
        examples=["alice@example.com"],
        description=_EMAIL_DESCRIPTION,
    )
    name: str = Field(
        pattern=PARTICIPANT_NAME_PATTERN,
        examples=["alice"],
        description=(
            "Participant name: an existing human without an account, or a new one. Latin "
            "snake_case, stored lowercase; it signs every entry the person makes"
        ),
    )
    description: str = Field(
        default="",
        max_length=_DESCRIPTION_MAX,
        examples=["Разработчик интерфейса"],
        description="Description of a new participant; ignored for an existing one",
    )
    is_admin: bool = Field(default=False, description="Make the account an administrator")
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_PASSWORD_LENGTH,
        description=_NEW_PASSWORD_DESCRIPTION,
    )


class AccountWithPasswordRead(AccountRead):
    """Ответ на заведение и на сброс пароля: единственное место, где виден пароль."""

    password: str | None = Field(
        default=None,
        examples=["Zb2yE1hQy0nK4c9oVw3uTg7a"],
        description=(
            "The password the tracker generated, shown once and stored nowhere in plain "
            "text. Null when the administrator typed the password in the request"
        ),
    )


class AccountUpdate(BaseModel):
    """Частичное изменение учётной записи: применяется только переданное.

    `null` ни у одного поля смысла не имеет, и схема его не пропустит.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = unset_field(
        min_length=3,
        max_length=MAX_EMAIL_LENGTH,
        examples=["alice@example.com"],
        description=_EMAIL_DESCRIPTION,
    )
    is_admin: bool = unset_field(
        description=(
            "Grant or take the administrator flag. The last active administrator cannot "
            "lose it: `409 last_admin`"
        ),
    )
    disabled: bool = unset_field(
        description=(
            "`true` disables the account: it cannot sign in and every token of its "
            "participant is revoked. `false` enables it again; revoked tokens stay revoked"
        ),
    )


class PasswordReset(BaseModel):
    """Сброс пароля администратором: прежний не спрашивается."""

    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_PASSWORD_LENGTH,
        description=_NEW_PASSWORD_DESCRIPTION,
    )


class PasswordChange(BaseModel):
    """Смена своего пароля: прежний обязателен, если он задан."""

    model_config = ConfigDict(extra="forbid")

    current_password: str | None = Field(
        default=None,
        max_length=MAX_PASSWORD_LENGTH,
        description=(
            "The password in force now. Required when the account has one; an account "
            "without a password (`has_password: false`) sets its first one without it"
        ),
    )
    new_password: str = Field(
        min_length=1,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"New password, {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters",
    )
