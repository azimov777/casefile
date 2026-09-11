"""Конфигурация приложения: читается из переменных окружения и валидируется Pydantic."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения.

    Источники по возрастанию приоритета: значения по умолчанию и переменные окружения.
    Все переменные окружения — с префиксом `TRACKER_`.

    Файл `.env` приложение не ищет само, хотя pydantic-settings это умеет: его
    доставляет контейнеру Compose (`env_file:` в обоих контурах), и источник у настроек
    остаётся один. Пока файл читали ещё и отсюда, работало это только в дев-контуре —
    там репозиторий смонтирован томом и файл случайно оказывался как `/app/.env`, —
    а в прод-образе `.env` нет вовсе (`.dockerignore`), и правка файла на проде не
    меняла ничего (`docs/notes/docker.md`).
    """

    model_config = SettingsConfigDict(
        env_prefix="TRACKER_",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    debug: bool = False

    # Адреса и порта HTTP-сервера здесь нет: uvicorn запускается командой сервиса Compose
    # (`--host 0.0.0.0 --port 8000`), а наружу порт публикуется переменной `TRACKER_PORT`
    # в самом `docker-compose.yml`. Поле в настройках было бы третьим местом, где написан
    # порт, и первым, которое разойдётся с остальными. У MCP-сервера иначе: там процесс
    # поднимает сервер сам и адрес с портом читает отсюда.

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

    # --- Лента журнала ----------------------------------------------------------------
    # Потолок самого ожидания живёт не здесь, а в домене (`app/domain/journal.py`,
    # `MAX_WAIT_SECONDS`): он часть контракта — уезжает в схему параметра и в `details`
    # отказа, — а не настройка установки. Здесь только то, что владелец вправе крутить
    # под своё железо и своих клиентов.
    journal_wait_poll_interval: float = Field(
        default=5.0,
        gt=0,
        description=(
            "Seconds between the fallback journal checks made while waiting; waits are "
            "woken by PostgreSQL notifications and this is only the safety net for a "
            "listener whose connection died"
        ),
    )
    journal_stream_heartbeat_interval: float = Field(
        default=15.0,
        gt=0,
        description=(
            "Seconds between heartbeat comments in a journal stream. They keep proxies "
            "from closing an idle stream and let the server notice a client that went away"
        ),
    )
    journal_stream_max_connections: int = Field(
        default=50,
        ge=1,
        description=(
            "Open journal streams one process serves at once. Each takes a database "
            "connection while it reads the tail, so the pool bounds this from above"
        ),
    )

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
    # Три поля выше — привязка процесса: где MCP слушает внутри контейнера. Это поле —
    # адрес снаружи, по которому к нему подключается клиент; из него интерфейс собирает
    # конфигурацию агента (`GET /api/v1/installation`). Совпадают они только у локальной
    # установки, поэтому умолчание выводится из привязки (`effective_mcp_public_url`), а
    # за прокси, на другой машине или с TLS владелец задаёт адрес целиком. По заголовкам
    # запроса адрес не угадывается намеренно: запрос пришёл на адрес интерфейса, а не
    # MCP, и заголовки пишет клиент (`docs/CONCEPT.md`, 5.1; решение TRK-65#9).
    mcp_public_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Address MCP clients connect to from outside, reported to the interface by "
            "`GET /api/v1/installation`. Unset or empty means the local default "
            "`http://localhost:<mcp_port><mcp_path>`; set it when clients reach MCP by "
            "another scheme, host, port or path: a proxy, TLS, another machine"
        ),
    )
    mcp_page_size: int = Field(
        default=25,
        ge=1,
        description=(
            "Default page size of the MCP listings that return one. Smaller than the "
            "REST default on purpose: a page of the human interface is scrolled, a page "
            "of a tool call is read into the agent context and paid for in tokens"
        ),
    )
    mcp_text_limit: int = Field(
        default=2000,
        ge=200,
        description=(
            "Characters of a long text (the task description, one of its five sections) "
            "that `search_tasks` returns before clipping it. The clip is always reported "
            "next to the value, and the whole task is one `get_task` away. Nothing else "
            "is clipped: an entry body is asked for by number and has nowhere else to be "
            "read from"
        ),
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

    @field_validator("mcp_public_url", mode="before")
    @classmethod
    def _unset_public_url(cls, value: object) -> object:
        """Пустая строка значит «не задано», а не «неверный адрес».

        Compose передаёт переменную всегда — подстановкой `${TRACKER_MCP_PUBLIC_URL:-}` в
        `x-app-environment`, — и у установки, где её никто не задавал, она приезжает
        пустой. Без этого шага такой контур не поднялся бы вовсе: пустая строка не URL.
        Общий `env_ignore_empty=True` вместо него не годится: он поменял бы смысл пустого
        значения у соседей — `TRACKER_CORS_ORIGINS=` значит пустой список, а не умолчание.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mcp_public_url")
    @classmethod
    def _public_url_without_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        """Адрес с `user:password@` отклоняется: он уезжает каждому держателю ключа.

        Интерфейс показывает адрес любым ключом, даже набора `task`, и вкладывает его в
        каждый фрагмент конфигурации клиента. Пароль в адресе стал бы общим для всех,
        кто видит интерфейс; авторизация MCP идёт заголовком, а не адресом.
        """
        if value is not None and (value.username or value.password):
            raise ValueError("must not carry credentials: every token holder sees this address")
        return value

    @property
    def effective_mcp_public_url(self) -> str:
        """Адрес MCP для клиента снаружи: заданный целиком или локальный по привязке.

        Умолчание — `localhost` на порту и пути самого процесса: оба контура публикуют
        MCP на тот же порт хоста (`TRACKER_MCP_PORT` стоит по обе стороны проброса), так
        что для клиента на этой же машине адрес верен. Сдвинули порт — сдвинулся и адрес.
        """
        if self.mcp_public_url is not None:
            return str(self.mcp_public_url)
        return f"http://localhost:{self.mcp_port}{self.mcp_path}"

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
