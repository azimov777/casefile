"""Вход владельца по паролю: сеансы браузера и ограничение перебора.

Замок на одну дверь (`docs/CONCEPT.md`, 5.4). Пароль открывает выдачу ключа интерфейса
браузеру: nginx интерфейса отдаёт `/config.json` только тому, чей сеанс здесь жив
(`ui/docker/nginx.conf.template`, `auth_request`). REST и MCP сеанса не знают — они
по-прежнему требуют токен на каждом запросе.

## Состояние живёт в памяти процесса, и это решение, а не упрощение

Сеансы и счётчик неудачных попыток — поля объекта, который `create_app` кладёт в
`app.state`. Таблицы в базе нет (`TRK-90#9`): выход удаляет сеанс здесь же, а перезапуск
API гасит все сеансы разом — владелец входит заново, и это же даёт «выйти везде» при
смене пароля (новый хеш в `.env` требует `up -d`, и процесс пересоздаётся).

Следствие, которое обязан знать тот, кто тронет команду службы `api`: у установки
**один** процесс API. Реплики или `uvicorn --workers N` разнесли бы сеансы по процессам,
и вход «то работает, то нет» выглядел бы как поломка куки. Тот же довод у счётчика
потоков ленты (`app/services/journal.py`, `StreamSlots`): потолок на процесс.
"""

import asyncio
import hashlib
import math
import secrets
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.domain.errors import PasswordAttemptsExceededError, PasswordLoginOffError
from app.domain.passwords import PasswordHash, PasswordHashError, verify_password

#: Энтропия секрета сеанса: 256 бит, как у токена (`app/domain/tokens.py`). Перебрать
#: такой секрет нельзя, поэтому хранится его быстрый хеш, а не сам секрет.
SESSION_SECRET_BYTES = 32

#: Сколько неудачных попыток входа (вместе с идущими прямо сейчас) допускается за окно.
#: Пять в минуту — 7200 в сутки: случайный пароль от 12 символов так не перебрать, а
#: владелец, дважды опечатавшийся, не упирается ни во что (`TRK-90#8`).
ATTEMPT_LIMIT = 5
ATTEMPT_WINDOW = timedelta(seconds=60)

type Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class OpenedSession:
    """Новый сеанс: секрет для куки (живёт только в ответе) и срок."""

    secret: str
    expires_at: datetime


class PasswordLogin:
    """Сеансы входа по паролю и окно неудачных попыток одного процесса API."""

    def __init__(
        self,
        *,
        password_hash: PasswordHash | None,
        session_ttl: timedelta,
        clock: Clock = _now,
        attempt_limit: int = ATTEMPT_LIMIT,
        attempt_window: timedelta = ATTEMPT_WINDOW,
    ) -> None:
        self._hash = password_hash
        self._ttl = session_ttl
        self._clock = clock
        self._limit = attempt_limit
        self._window = attempt_window
        #: Хеш секрета сеанса → срок. Самих секретов здесь нет: снимок памяти процесса
        #: не должен давать готовую куку.
        self._sessions: dict[str, datetime] = {}
        self._failures: deque[datetime] = deque()
        self._in_flight = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> PasswordLogin:
        """Вход по настройкам установки. Испорченный хеш — отказ здесь, при сборке API.

        Молча принятый, он запер бы владельца снаружи: пароль «не подходит», и никакой
        подсказки почему. Сообщение называет правило и команду, но не значение: его
        печатают в журнал подъёма контура.
        """
        stored = None
        if settings.password_hash is not None:
            try:
                stored = PasswordHash.parse(settings.password_hash.get_secret_value())
            except PasswordHashError as exc:
                raise PasswordHashError(
                    f"TRACKER_PASSWORD_HASH is not a password hash: {exc}"
                ) from None
        return cls(password_hash=stored, session_ttl=timedelta(hours=settings.session_hours))

    @property
    def enabled(self) -> bool:
        """Задан ли на установке пароль владельца."""
        return self._hash is not None

    async def open(self, password: str) -> OpenedSession:
        """Проверяет пароль и заводит сеанс.

        Место в окне занимается **до** проверки, и идущие попытки считаются наравне с
        неудачными: иначе сотня одновременных запросов прошла бы проверку раньше, чем
        первая неудача попала в счётчик. Сверх окна пароль не проверяется вовсе — даже
        верный: ограничение, которое пропускает угаданный пароль, ничего не ограничивает.
        """
        stored = self._require_hash()
        self._reserve_attempt()
        try:
            # scrypt держит процессор десятые доли секунды: в потоке, чтобы цикл событий
            # API в это время обслуживал остальных.
            matches = await asyncio.to_thread(verify_password, password, stored)
        finally:
            self._in_flight -= 1
        if not matches:
            self._failures.append(self._clock())
            raise UnauthorizedError(
                message="Password does not match",
                details={"reason": "wrong_password"},
            )

        now = self._clock()
        self._forget_expired(now)
        secret = secrets.token_urlsafe(SESSION_SECRET_BYTES)
        expires_at = now + self._ttl
        self._sessions[_fingerprint(secret)] = expires_at
        return OpenedSession(secret=secret, expires_at=expires_at)

    def check(self, secret: str | None) -> datetime:
        """Срок живого сеанса или отказ `unauthorized` с причиной в `details.reason`."""
        self._require_hash()
        if not secret:
            raise UnauthorizedError(
                message="No live session", details={"reason": "missing_session"}
            )
        fingerprint = _fingerprint(secret)
        expires_at = self._sessions.get(fingerprint)
        if expires_at is None:
            raise UnauthorizedError(
                message="No live session", details={"reason": "unknown_session"}
            )
        if expires_at <= self._clock():
            del self._sessions[fingerprint]
            raise UnauthorizedError(
                message="No live session", details={"reason": "session_expired"}
            )
        return expires_at

    def close(self, secret: str | None) -> None:
        """Гасит сеанс, если он есть. Повтор и чужой секрет — не ошибка: выход идемпотентен."""
        self._require_hash()
        if secret:
            self._sessions.pop(_fingerprint(secret), None)

    def _require_hash(self) -> PasswordHash:
        if self._hash is None:
            raise PasswordLoginOffError()
        return self._hash

    def _reserve_attempt(self) -> None:
        now = self._clock()
        while self._failures and self._failures[0] <= now - self._window:
            self._failures.popleft()
        if len(self._failures) + self._in_flight >= self._limit:
            # Место освободится, когда из окна выйдет старшая неудача. Пока занято только
            # идущими попытками, ждать их исхода — доли секунды: просим повторить через одну.
            free_at = self._failures[0] + self._window if self._failures else now
            retry_after = max(1, math.ceil((free_at - now).total_seconds()))
            raise PasswordAttemptsExceededError(
                details={
                    "retry_after": retry_after,
                    "limit": self._limit,
                    "window_seconds": int(self._window.total_seconds()),
                }
            )
        self._in_flight += 1

    def _forget_expired(self, now: datetime) -> None:
        """Убирает истёкшие сеансы. Зовётся на входе: без фоновых процессов память
        растёт только с числом входов, а каждый вход требует пароля."""
        for fingerprint in [key for key, until in self._sessions.items() if until <= now]:
            del self._sessions[fingerprint]


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
