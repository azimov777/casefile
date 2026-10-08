"""Последний выпуск Casefile: отстаёт ли эта установка (TRK-416).

Интерфейс показывает внизу боковой панели «Доступен выпуск vX.Y.Z (у вас vA.B.C)».
Во внешний мир за этим ходит API, а не браузер: вкладка ходит только в свой бэкенд, и
адрес GitHub в ней появляться не должен.

## Раз в час, на запросе, а не фоновым процессом

Фоновых процессов у трекера нет (TRK/docker#5), поэтому «раз в час»
здесь — срок ответа в кэше: первый запрос после старта и первый после истечения срока
идут в GitHub, остальные берут запомненное. Одновременные запросы на пустом кэше ждут
один поход, а не делают по своему. Сбой запоминается на `FAILURE_RETRY` — короче часа,
чтобы старт установки раньше сети не прятал плашку на целый час, и дольше мгновения,
чтобы лежащая сеть не превращала каждый запрос интерфейса в ожидание тайм-аута.

Кэш — поле объекта, который `create_app` кладёт в `app.state`, как окна попыток входа
(`app/services/login.py`): у второго процесса API был бы свой, и в GitHub ходил бы
каждый.

## Когда в GitHub не ходят вовсе

- `TRACKER_RELEASE_CHECK=false` — владелец выключил проверку;
- установка не `production`: версия дев-контура и тестов не из тега выпуска, и
  сравнивать её с выпуском незачем. Отличить изнутри контейнера образ выпуска от образа
  `latest` с main нечем, но у `latest` версия в `pyproject.toml` — последний выпуск,
  и сравнение там тоже честное.

Сбой сети, отказ GitHub и неразобранный ответ — это «обновления нет», а не ошибка
интерфейсу: плашка — подсказка, а не часть работы. Сбой при этом пишется в журнал
процесса, чтобы молчание плашки было объяснимо.
"""

import asyncio
import json
import time
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app import __version__
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.releases import RELEASES_REPOSITORY, Release, is_newer, parse_version
from app.services.auth import Actor

logger = get_logger("releases")

#: Сколько живёт в кэше прочитанный выпуск.
CHECK_INTERVAL = 3600.0
#: Сколько живёт в кэше сбой: следующий поход — не раньше.
FAILURE_RETRY = 600.0
#: Сколько ждать GitHub. Запрос интерфейса ждёт столько же на пустом кэше.
FETCH_TIMEOUT = 5.0

LATEST_RELEASE_API = f"https://api.github.com/repos/{RELEASES_REPOSITORY}/releases/latest"

#: Чтение последнего выпуска: выпуск или `None`, если его не удалось прочитать.
type FetchLatest = Callable[[], Awaitable[Release | None]]
type Clock = Callable[[], float]


def _read_latest_release_blocking() -> Release | None:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"casefile/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        body = json.load(response)
    tag = body.get("tag_name") if isinstance(body, dict) else None
    if not isinstance(tag, str) or parse_version(tag) is None:
        logger.warning("Latest release tag is not a version: %r", tag)
        return None
    # Адрес страницы строится из тега, а не берётся из ответа: в интерфейс уходит ссылка,
    # и вести она может только на выпуски этого репозитория.
    return Release(
        version=tag.removeprefix("v"),
        url=f"https://github.com/{RELEASES_REPOSITORY}/releases/tag/{tag}",
    )


async def read_latest_release() -> Release | None:
    """Последний выпуск с GitHub; сбой любого рода — `None` и строка в журнале."""
    try:
        return await asyncio.to_thread(_read_latest_release_blocking)
    # Сеть, HTTP, JSON, тайм-аут: для плашки всё одно — выпуск не прочитан.
    except Exception as exc:
        logger.warning("Could not read the latest release: %s", exc)
        return None


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """Версия установки и последний выпуск, если он известен."""

    version: str
    #: Последний выпуск. `None` — проверка выключена, не положена или не удалась.
    latest: Release | None
    update_available: bool


class ReleaseWatch:
    """Последний выпуск с кэшем на процесс API."""

    def __init__(
        self,
        *,
        enabled: bool,
        fetch: FetchLatest | None = None,
        clock: Clock = time.monotonic,
        version: str = __version__,
    ) -> None:
        self._enabled = enabled
        # Функция модуля берётся при сборке, а не умолчанием параметра: тест подменяет её
        # на модуле до `create_app`, и в GitHub не ходит.
        self._fetch = fetch if fetch is not None else read_latest_release
        self._clock = clock
        self._version = version
        self._lock = asyncio.Lock()
        self._latest: Release | None = None
        self._expires_at: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> ReleaseWatch:
        """Проверка по настройкам: только `production` и только не выключенная."""
        return cls(enabled=settings.release_check and settings.environment == "production")

    async def read(self) -> ReleaseState:
        """Версия и последний выпуск; в GitHub — только если срок кэша вышел."""
        latest = await self._latest_release() if self._enabled else None
        return ReleaseState(
            version=self._version,
            latest=latest,
            update_available=latest is not None and is_newer(latest, self._version),
        )

    async def _latest_release(self) -> Release | None:
        async with self._lock:
            now = self._clock()
            if self._expires_at is None or now >= self._expires_at:
                self._latest = await self._fetch()
                ttl = CHECK_INTERVAL if self._latest is not None else FAILURE_RETRY
                self._expires_at = self._clock() + ttl
            return self._latest


async def read_release(*, actor: Actor, watch: ReleaseWatch) -> ReleaseState:
    """Отстаёт ли установка от последнего выпуска. Открыто любому набору: секрета нет."""
    return await watch.read()
