"""Конфигурация приложения: читается из переменных окружения и валидируется Pydantic."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения.

    Источники по возрастанию приоритета: значения по умолчанию, файл `.env`,
    переменные окружения. Все переменные окружения — с префиксом `TRACKER_`.
    """

    model_config = SettingsConfigDict(
        env_prefix="TRACKER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8000

    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://tracker:tracker@localhost:5432/tracker",
        description="Main database URL; the driver must be asynchronous (asyncpg)",
    )
    test_database_url: PostgresDsn | None = Field(
        default=None,
        description="Test database URL; defaults to the main one with the `_test` suffix",
    )
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # --- MCP-сервер для агентов ------------------------------------------------------
    # Отдельный процесс и отдельный порт: инструменты агента живут не в том же сервисе,
    # что REST фронтенда, и клиент MCP подключается прямо к нему.
    mcp_host: str = Field(
        default="0.0.0.0",
        description="Address the MCP server binds to; the container needs 0.0.0.0",
    )
    mcp_port: int = Field(default=8100, description="Port of the MCP server")
    mcp_path: str = Field(
        default="/mcp",
        description="Path of the streamable HTTP endpoint the MCP client connects to",
    )

    # NoDecode отключает разбор значения как JSON: без него pydantic-settings падает
    # на строке «a,b» ещё до валидатора, потому что ждёт от списка JSON-массив.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"],
        description="Origins allowed for the browser frontend",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Позволяет задавать список через запятую: `TRACKER_CORS_ORIGINS=a,b`."""
        if isinstance(value, str) and not value.startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def effective_test_database_url(self) -> str:
        """Адрес тестовой БД. По умолчанию — основная база с суффиксом `_test`."""
        if self.test_database_url is not None:
            return str(self.test_database_url)
        url = str(self.database_url)
        base, _, database = url.rpartition("/")
        return f"{base}/{database}_test"


@lru_cache
def get_settings() -> Settings:
    """Настройки приложения, единый экземпляр на процесс."""
    return Settings()
