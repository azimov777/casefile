"""Схемы входа по почте и паролю (`docs/CONCEPT.md`, 5.4)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.accounts import AccountRead
from app.domain.accounts import MAX_EMAIL_LENGTH
from app.domain.passwords import MAX_PASSWORD_LENGTH


class SessionLogin(BaseModel):
    """Вход учётной записью: почта и пароль."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        min_length=1,
        max_length=MAX_EMAIL_LENGTH,
        examples=["alice@example.com"],
        description="Email of the account; matching ignores case",
    )
    password: str = Field(
        min_length=1,
        max_length=MAX_PASSWORD_LENGTH,
        description="Password of the account, as typed. It is never stored or logged",
    )


class SessionRead(BaseModel):
    """Живой сеанс: токен вкладки, его срок и учётная запись за ним."""

    token: str = Field(
        examples=["trk_0oUCtWtA6d9v0j0N1cMBAxk2wKAKopWzvbf_wQ8sDLc"],
        description=(
            "Secret of the session token: a `main` token of the account's participant, "
            "sent as `Authorization: Bearer` on every REST request. The same secret rides "
            "in the `HttpOnly` cookie; this is how the tab gets it again after a reload"
        ),
    )
    expires_at: datetime = Field(
        description=(
            "When the session and its token end, counted from the sign-in "
            "(`TRACKER_SESSION_HOURS`). They end earlier on sign-out, on a password change "
            "or reset, and when the account is disabled"
        ),
    )
    account: AccountRead = Field(description="The account signed in")
