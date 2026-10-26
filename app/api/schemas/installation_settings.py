"""Схемы настроек установки: список с источниками и правка одной настройки (TRK-744)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.domain.installation_settings import SettingKind
from app.services.installation_settings import SettingSource


class InstallationSettingRead(BaseModel):
    """Одна настройка установки: правила, что в базе, что действует и кто менял.

    Значения — текстом в каноническом виде: число (`168`), `true`/`false`, срок ISO 8601
    секундами (`PT2592000S`). Так же значение принимает правка.
    """

    name: str = Field(examples=["mcp_page_size"], description="Setting name from the registry")
    env_var: str = Field(
        examples=["TRACKER_MCP_PAGE_SIZE"],
        description="Environment variable that gives the default when the database is empty",
    )
    kind: SettingKind = Field(description="Value type: `integer`, `boolean` or `duration`")
    value: str | None = Field(
        examples=["10"],
        description=(
            "What an administrator stored in the database. Null when nothing is stored "
            "or the setting was returned to the environment"
        ),
    )
    effective_value: str = Field(
        examples=["10"], description="The value in force now, whatever its source"
    )
    source: SettingSource = Field(
        description="Where `effective_value` comes from: `database`, `environment` or `default`"
    )
    default_value: str = Field(
        examples=["25"],
        description=(
            "The value in force when the database holds nothing: the environment variable "
            "if it is set and valid, otherwise the code default"
        ),
    )
    default_source: SettingSource = Field(
        description="Where `default_value` comes from: `environment` or `default`"
    )
    minimum: int | None = Field(
        examples=[1],
        description="Lowest allowed value, inclusive; seconds for a duration; null for a boolean",
    )
    maximum: int | None = Field(
        examples=[200],
        description="Highest allowed value, inclusive; seconds for a duration; null for a boolean",
    )
    updated_by: AuthorRead | None = Field(
        description="Who changed the setting last; null if nobody has"
    )
    updated_at: datetime | None = Field(
        description="When the setting was changed last; null if nobody has"
    )


class InstallationSettingUpdate(BaseModel):
    """Тело правки: новое значение; пустое или `null` возвращает «брать из окружения»."""

    # Лишнее поле — отказ, а не молча отброшенное значение (`tests/test_openapi.py`).
    model_config = ConfigDict(extra="forbid")

    value: str | int | bool | None = Field(
        examples=["10", 10, ""],
        description=(
            "New value. A number, a boolean or a string in the canonical form; an empty "
            "string or null returns the setting to the environment variable or the code default"
        ),
    )
