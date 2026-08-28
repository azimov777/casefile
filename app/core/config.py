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

    # --- Воркер шины событий -----------------------------------------------------
    # Настройки, а не константы в коде: паузу повтора и потолок попыток приходится
    # подбирать под конкретную установку (медленный вебхук, недоступный внешний сервис),
    # и делать это перевыкладкой образа неправильно.
    outbox_poll_interval: float = Field(
        default=1.0,
        gt=0,
        description="Seconds the events worker sleeps when the outbox is empty",
    )
    outbox_max_attempts: int = Field(
        default=5,
        ge=1,
        description="Delivery attempts before an event is marked as failed",
    )
    outbox_retry_delay: float = Field(
        default=10.0,
        gt=0,
        description="Base delay before the next delivery attempt; doubles with every attempt",
    )
    outbox_max_retry_delay: float = Field(
        default=600.0,
        gt=0,
        description="Upper bound for the growing retry delay",
    )

    # --- Движок автоматики -------------------------------------------------------
    # Все четыре — защита от зацикливания и от волн событий, и все четыре настройки, а
    # не константы: подобрать потолки можно только на живом наборе правил, а менять их
    # перевыкладкой образа в тот момент, когда контур уже гоняет сам себя, поздно.
    automation_max_chain_depth: int = Field(
        default=3,
        ge=0,
        description=(
            "How deep a rule-to-rule chain may go. 0 disables automation reacting to "
            "its own changes entirely"
        ),
    )
    automation_rate_limit: int = Field(
        default=10,
        ge=1,
        description="Successful runs of one rule on one issue allowed inside the window",
    )
    automation_rate_window: float = Field(
        default=60.0,
        gt=0,
        description="Seconds the automation rate limit looks back",
    )
    automation_tick_interval: float = Field(
        default=30.0,
        gt=0,
        description="Seconds the scheduler sleeps between looking for due rules",
    )
    automation_batch_size: int = Field(
        default=200,
        ge=1,
        description="Issues one scheduled rule processes per tick; the rest wait for the next",
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
