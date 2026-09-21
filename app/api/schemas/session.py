"""Схемы входа владельца по паролю (`docs/CONCEPT.md`, 5.4)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.passwords import MAX_PASSWORD_LENGTH


class PasswordLogin(BaseModel):
    """Вход по паролю установки. Имени нет: пароль у установки один — владельца."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(
        min_length=1,
        max_length=MAX_PASSWORD_LENGTH,
        description=(
            "The owner password of this installation, as typed. It is checked against "
            "`TRACKER_PASSWORD_HASH` and never stored or logged"
        ),
    )


class SessionRead(BaseModel):
    """Живой сеанс браузера. Секрета здесь нет: он едет только в куке `HttpOnly`."""

    expires_at: datetime = Field(
        description=(
            "When the session ends, counted from the login (`TRACKER_SESSION_HOURS`). It "
            "also ends earlier on logout and when the API process restarts"
        ),
    )
