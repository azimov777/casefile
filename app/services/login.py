"""Вход владельца по паролю: сеансы браузера и ограничение перебора.

Замок на одну дверь (`docs/CONCEPT.md`, 5.4). Пароль открывает выдачу ключа интерфейса
браузеру: nginx интерфейса отдаёт `/config.json` только тому, чей сеанс здесь жив
(`ui/docker/nginx.conf.template`, `auth_request`). REST и MCP сеанса не знают — они
по-прежнему требуют токен на каждом запросе.

## Состояние живёт в памяти процесса, и это решение, а не упрощение

Сеансы и окна неудачных попыток — поля объекта, который `create_app` кладёт в
`app.state`. Таблицы в базе нет (`TRK-90#9`): выход удаляет сеанс здесь же, а перезапуск
API гасит все сеансы разом — владелец входит заново, и это же даёт «выйти везде» при
смене пароля (новый хеш в `.env` требует `up -d`, и процесс пересоздаётся).

Следствие, которое обязан знать тот, кто тронет команду службы `api`: у установки
**один** процесс API. Реплики или `uvicorn --workers N` разнесли бы сеансы по процессам,
и вход «то работает, то нет» выглядел бы как поломка куки. Тот же довод у счётчика
потоков ленты (`app/services/journal.py`, `StreamSlots`): потолок на процесс.

## Перебор ограничен дважды: на адрес клиента и потолком установки

Неудачи считаются в окне на адрес клиента и в общем окне установки с потолком выше
(`TRK-98#7`). Кто исчерпал своё окно, получает отказ, не заняв места ни в одном окне, —
поэтому один перебирающий адрес не запирает владельца, входящего с другого, а перебор со
многих адресов упирается в общий потолок. Адрес клиента определяет HTTP-слой
(`app/api/client_address.py`): здесь он уже ключ, и написать его себе клиент не может.

Памяти счётчики адресов берут не больше потолка: строка адреса живёт, пока у него есть
неудача в окне или идущая попытка, а каждая из них занимает место общего окна
(`TRK-98#8`).
"""

import asyncio
import hashlib
import ipaddress
import math
import secrets
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.domain.errors import PasswordAttemptsExceededError, PasswordLoginOffError
from app.domain.passwords import PasswordHash, PasswordHashError, verify_password

#: Энтропия секрета сеанса: 256 бит, как у токена (`app/domain/tokens.py`). Перебрать
#: такой секрет нельзя, поэтому хранится его быстрый хеш, а не сам секрет.
SESSION_SECRET_BYTES = 32

#: Сколько неудачных попыток входа (вместе с идущими прямо сейчас) допускается за окно с
#: одного адреса клиента. Владелец, дважды опечатавшийся, не упирается ни во что (`TRK-90#8`).
ATTEMPT_LIMIT_PER_ADDRESS = 5
#: Потолок тех же попыток на всю установку, со всех адресов вместе. Держит перебор со
#: многих адресов: 20 в минуту — 28 800 в сутки, случайный пароль от 12 символов так не
#: перебрать. Четыре окна адреса: одиночный перебирающий до владельца не достаёт, а четыре
#: адреса разом — достают, и это названная цена (`TRK-98#7`).
ATTEMPT_LIMIT_TOTAL = 20
ATTEMPT_WINDOW = timedelta(seconds=60)

#: Сколько адреса IPv6 считается одним клиентом. Одна машина обычно владеет целой `/64` и
#: меняет адреса в ней свободно: окно на отдельный адрес IPv6 она обходила бы даром.
IPV6_CLIENT_PREFIX = 64
#: Ключ клиента, чей адрес неизвестен: все такие делят одно окно.
UNKNOWN_CLIENT = "unknown"

type Clock = Callable[[], datetime]
type ClientAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type AttemptScope = Literal["address", "installation"]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class OpenedSession:
    """Новый сеанс: секрет для куки (живёт только в ответе) и срок."""

    secret: str
    expires_at: datetime


@dataclass(slots=True)
class _ClientAttempts:
    """Окно одного адреса: его неудачи по порядку и попытки, идущие прямо сейчас."""

    failures: deque[datetime] = field(default_factory=deque)
    in_flight: int = 0


def client_key(address: ClientAddress | None) -> str:
    """Ключ окна попыток: адрес IPv4, сеть `/64` для IPv6, общий ключ для неизвестного."""
    if address is None:
        return UNKNOWN_CLIENT
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/{IPV6_CLIENT_PREFIX}", strict=False))
    return str(address)


class PasswordLogin:
    """Сеансы входа по паролю и окна неудачных попыток одного процесса API."""

    def __init__(
        self,
        *,
        password_hash: PasswordHash | None,
        session_ttl: timedelta,
        clock: Clock = _now,
        limit_per_address: int = ATTEMPT_LIMIT_PER_ADDRESS,
        limit_total: int = ATTEMPT_LIMIT_TOTAL,
        attempt_window: timedelta = ATTEMPT_WINDOW,
    ) -> None:
        self._hash = password_hash
        self._ttl = session_ttl
        self._clock = clock
        self._limit_per_address = limit_per_address
        self._limit_total = limit_total
        self._window = attempt_window
        #: Хеш секрета сеанса → срок. Самих секретов здесь нет: снимок памяти процесса
        #: не должен давать готовую куку.
        self._sessions: dict[str, datetime] = {}
        #: Все неудачи окна по порядку, с ключом адреса: выходя из окна, неудача снимается
        #: и из окна своего адреса — тем же шагом, без обхода словаря адресов.
        self._failures: deque[tuple[datetime, str]] = deque()
        self._in_flight = 0
        #: Окна адресов. Строка есть, только пока у адреса есть неудача в окне или идущая
        #: попытка, — а каждая занимает место общего окна, поэтому строк не больше
        #: `limit_total`.
        self._clients: dict[str, _ClientAttempts] = {}

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

    async def open(self, password: str, client: ClientAddress | None) -> OpenedSession:
        """Проверяет пароль, пришедший с адреса `client`, и заводит сеанс.

        Место занимается **до** проверки — в окне адреса и в общем, — и идущие попытки
        считаются наравне с неудачными: иначе сотня одновременных запросов прошла бы
        проверку раньше, чем первая неудача попала в счётчик. Сверх любого из окон пароль
        не проверяется вовсе — даже верный: ограничение, которое пропускает угаданный
        пароль, ничего не ограничивает.
        """
        stored = self._require_hash()
        key = client_key(client)
        attempts = self._reserve_attempt(key)
        # Попытка без исхода (отменённая, упавшая) считается неудачей: верен ли был пароль,
        # неизвестно, а бесплатная попытка была бы обходом окна.
        matches = False
        try:
            # scrypt держит процессор десятые доли секунды: в потоке, чтобы цикл событий
            # API в это время обслуживал остальных.
            matches = await asyncio.to_thread(verify_password, password, stored)
        finally:
            self._finish_attempt(key, attempts, failed=not matches)
        if not matches:
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

    def _reserve_attempt(self, key: str) -> _ClientAttempts:
        """Занимает место попытки в окне адреса и в общем — или отказывает `429`.

        Окно адреса проверяется первым: исчерпавший своё узнаёт о своём, а не о чужом. Отказ
        не занимает места нигде и строки адреса не заводит — поток отказов памяти не ест.
        """
        now = self._clock()
        self._forget_old_failures(now)
        attempts = self._clients.get(key)
        if attempts is not None and (
            len(attempts.failures) + attempts.in_flight >= self._limit_per_address
        ):
            oldest = attempts.failures[0] if attempts.failures else None
            raise self._exceeded("address", self._limit_per_address, oldest, now)
        if len(self._failures) + self._in_flight >= self._limit_total:
            oldest = self._failures[0][0] if self._failures else None
            raise self._exceeded("installation", self._limit_total, oldest, now)
        if attempts is None:
            attempts = self._clients[key] = _ClientAttempts()
        attempts.in_flight += 1
        self._in_flight += 1
        return attempts

    def _finish_attempt(self, key: str, attempts: _ClientAttempts, *, failed: bool) -> None:
        """Освобождает место идущей попытки; неудача остаётся в обоих окнах до выхода из них."""
        attempts.in_flight -= 1
        self._in_flight -= 1
        if failed:
            at = self._clock()
            self._failures.append((at, key))
            attempts.failures.append(at)
        elif not attempts.failures and not attempts.in_flight:
            del self._clients[key]

    def _forget_old_failures(self, now: datetime) -> None:
        """Снимает неудачи, вышедшие из окна, — из общего и из окна их адреса.

        Обе очереди пополняются одной записью в один момент, поэтому старшая неудача общего
        окна — это и старшая неудача своего адреса. Адрес без неудач и идущих попыток
        забывается сразу.
        """
        while self._failures and self._failures[0][0] <= now - self._window:
            _, key = self._failures.popleft()
            attempts = self._clients[key]
            attempts.failures.popleft()
            if not attempts.failures and not attempts.in_flight:
                del self._clients[key]

    def _exceeded(
        self, scope: AttemptScope, limit: int, oldest: datetime | None, now: datetime
    ) -> PasswordAttemptsExceededError:
        # Место освободится, когда из окна выйдет старшая неудача. Пока занято только
        # идущими попытками, ждать их исхода — доли секунды: просим повторить через одну.
        free_at = oldest + self._window if oldest is not None else now
        retry_after = max(1, math.ceil((free_at - now).total_seconds()))
        return PasswordAttemptsExceededError(
            details={
                "retry_after": retry_after,
                "limit": limit,
                "window_seconds": int(self._window.total_seconds()),
                "scope": scope,
            }
        )

    def _forget_expired(self, now: datetime) -> None:
        """Убирает истёкшие сеансы. Зовётся на входе: без фоновых процессов память
        растёт только с числом входов, а каждый вход требует пароля."""
        for fingerprint in [key for key, until in self._sessions.items() if until <= now]:
            del self._sessions[fingerprint]


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
