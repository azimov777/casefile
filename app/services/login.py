"""Вход по почте и паролю: сеанс браузера и ограничение перебора.

Учётная запись входит почтой и паролем (`docs/CONCEPT.md`, 5.4), и вход выпускает
участнику этой учётной записи **токен сеанса** — токен набора `main` со сроком. Секрет
токена едет в куку `HttpOnly` (`app/api/routes/session.py`), а `GET /api/v1/session` по
куке отдаёт вкладке тот же токен. REST и MCP сеанса не знают — они знают токены, и
другого способа аутентификации рядом с токеном нет.

## Сеансы живут в базе, окна попыток — в памяти процесса

Сеанс — строка `tokens` со сроком (`expires_at`): перезапуск API его не гасит, выход
отзывает сам токен, и вкладка теряет доступ сразу, а не на перезагрузке. Отдельной
таблицы сеансов нет намеренно: хеш секрета, отзыв и участник у токена уже есть
(решение TRK-113#9).

Окна неудачных попыток — поля объекта, который `create_app` кладёт в `app.state`: это
ограничение скорости, а не состояние, которое жалко потерять. Следствие для того, кто
тронет команду службы `api`: реплики или `uvicorn --workers N` разнесли бы окна по
процессам и умножили бы разрешённое число попыток на число процессов.

## Перебор ограничен трижды: на адрес клиента, на почту и потолком установки

Неудачи считаются в окне на адрес клиента, в окне на почту и в общем окне установки с
потолком выше обоих. Окно почты заводится на **любую** присланную почту, заведённую или
нет: иначе разный ответ выдавал бы, какие адреса есть на установке. По той же причине
неизвестная почта проверяется против пустышки той же стоимости (`_UNKNOWN_ACCOUNT`), а
не отвечает сразу. Кто исчерпал своё окно, получает отказ, не заняв места ни в одном, —
поэтому один перебирающий адрес не запирает человека, входящего с другого, а перебор
одной почты со многих адресов упирается в окно этой почты и не трогает остальных.

Общий потолок — защита процессора и памяти: попытка scrypt стоит десятые доли секунды
и десятки мебибайт (`app/domain/passwords.py`). Строк окон не больше потолка: строка
живёт, пока у неё есть неудача в окне или идущая попытка, а каждая занимает место общего
окна (`TRK-98#8`). Адрес клиента определяет HTTP-слой (`app/api/client_address.py`):
здесь он уже ключ, и написать его себе клиент не может.
"""

import asyncio
import ipaddress
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.db.models.account import Account
from app.db.models.author import created_by_columns
from app.db.models.token import Token
from app.db.repositories import AccountRepository, TokenRepository
from app.domain.accounts import normalize_email
from app.domain.errors import PasswordAttemptsExceededError
from app.domain.passwords import PasswordHash, hash_password, verify_password
from app.domain.tokens import TokenScope, generate_token, hash_token

#: Имя токена сеанса в списке токенов: по нему человек отличает вкладки от ключей агентов.
SESSION_TOKEN_NAME = "browser-session"

#: Сколько неудачных попыток входа (вместе с идущими прямо сейчас) допускается за окно с
#: одного адреса клиента. Человек, дважды опечатавшийся, не упирается ни во что (`TRK-90#8`).
ATTEMPT_LIMIT_PER_ADDRESS = 5
#: То же на одну почту, со всех адресов вместе: держит перебор пароля одного человека,
#: разнесённый по многим машинам, и не трогает остальных людей установки.
ATTEMPT_LIMIT_PER_ACCOUNT = 5
#: Потолок тех же попыток на всю установку, со всех адресов и почт вместе. Не окно входа,
#: а защита процессора и памяти: сотня попыток scrypt в минуту — это секунды процессора
#: и не больше сотни строк окон. Выше окна одного человека в двадцать раз: чтобы в него
#: упереться, нужен перебор, разнесённый и по адресам, и по почтам (`TRK-113#10`).
ATTEMPT_LIMIT_TOTAL = 100
ATTEMPT_WINDOW = timedelta(seconds=60)

#: Сколько адреса IPv6 считается одним клиентом. Одна машина обычно владеет целой `/64` и
#: меняет адреса в ней свободно: окно на отдельный адрес IPv6 она обходила бы даром.
IPV6_CLIENT_PREFIX = 64
#: Ключ клиента, чей адрес неизвестен: все такие делят одно окно.
UNKNOWN_CLIENT = "unknown"

type Clock = Callable[[], datetime]
type ClientAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type AttemptScope = Literal["address", "account", "installation"]
type KeyedScope = Literal["address", "account"]


def _now() -> datetime:
    return datetime.now(UTC)


@cache
def _unknown_account_hash() -> PasswordHash:
    """Пустышка для почты, которой нет или у которой нет пароля.

    Проверка идёт против неё той же стоимостью, что против настоящего хеша: иначе
    неизвестная почта отвечала бы на десятые доли секунды быстрее, и по времени ответа
    читалось бы, какие адреса заведены. Считается один раз на процесс, при первой нужде.
    """
    return hash_password(generate_token())


@dataclass(frozen=True, slots=True)
class LiveSession:
    """Живой сеанс: токен со сроком, его секрет и учётная запись за ним.

    Секрет здесь есть всегда: при входе он только что выпущен, при чтении пришёл в куке.
    Отдавать его вкладке — смысл сеанса: это её ключ к REST (`docs/CONCEPT.md`, 5.4).
    """

    secret: str
    token: Token
    account: Account

    @property
    def expires_at(self) -> datetime:
        assert self.token.expires_at is not None  # токен сеанса всегда со сроком
        return self.token.expires_at


@dataclass(slots=True)
class _KeyAttempts:
    """Окно одного ключа (адреса или почты): неудачи по порядку и попытки прямо сейчас."""

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
    """Вход по почте и паролю: окна неудачных попыток процесса и срок сеанса."""

    def __init__(
        self,
        *,
        session_ttl: timedelta,
        clock: Clock = _now,
        limit_per_address: int = ATTEMPT_LIMIT_PER_ADDRESS,
        limit_per_account: int = ATTEMPT_LIMIT_PER_ACCOUNT,
        limit_total: int = ATTEMPT_LIMIT_TOTAL,
        attempt_window: timedelta = ATTEMPT_WINDOW,
    ) -> None:
        self._ttl = session_ttl
        self._clock = clock
        self._limits: dict[KeyedScope, int] = {
            "address": limit_per_address,
            "account": limit_per_account,
        }
        self._limit_total = limit_total
        self._window = attempt_window
        #: Все неудачи окна по порядку, с ключами адреса и почты: выходя из окна, неудача
        #: снимается и из их окон — тем же шагом, без обхода словарей.
        self._failures: deque[tuple[datetime, str, str]] = deque()
        self._in_flight = 0
        #: Окна ключей по видам. Строка есть, только пока у ключа есть неудача в окне или
        #: идущая попытка, — а каждая занимает место общего окна, поэтому строк не больше
        #: `limit_total` в каждом виде.
        self._keys: dict[KeyedScope, dict[str, _KeyAttempts]] = {"address": {}, "account": {}}

    @classmethod
    def from_settings(cls, settings: Settings) -> PasswordLogin:
        """Вход по настройкам установки: из них нужен только срок сеанса."""
        return cls(session_ttl=timedelta(hours=settings.session_hours))

    @property
    def session_ttl(self) -> timedelta:
        return self._ttl

    async def open(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        client: ClientAddress | None,
    ) -> LiveSession:
        """Проверяет почту и пароль, пришедшие с адреса `client`, и выпускает токен сеанса.

        Место занимается **до** проверки — в окне адреса, почты и в общем, — и идущие
        попытки считаются наравне с неудачными: иначе сотня одновременных запросов прошла
        бы проверку раньше, чем первая неудача попала в счётчик. Сверх любого из окон
        пароль не проверяется вовсе — даже верный: ограничение, которое пропускает
        угаданный пароль, ничего не ограничивает.

        Отказы — `401 unauthorized` с `details.reason`: `wrong_credentials` одинаково для
        неизвестной почты, учётной записи без пароля и неверного пароля (иначе ответ
        выдавал бы, какие адреса заведены), `account_disabled` — только после верного
        пароля: перебирающему он не говорит ничего.
        """
        address = client_key(client)
        account_key = normalize_email(email)
        self._reserve_attempt(address, account_key)
        # Попытка без исхода (отменённая, упавшая) считается неудачей: верен ли был
        # пароль, неизвестно, а бесплатная попытка была бы обходом окна.
        succeeded = False
        try:
            account = await AccountRepository(session).get_by_email(account_key)
            stored = (
                PasswordHash.parse(account.password_hash)
                if account is not None and account.password_hash is not None
                else None
            )
            # scrypt держит процессор десятые доли секунды: в потоке, чтобы цикл событий
            # API в это время обслуживал остальных.
            matches = await asyncio.to_thread(
                verify_password, password, stored or _unknown_account_hash()
            )
            succeeded = matches and stored is not None and account is not None
        finally:
            self._finish_attempt(address, account_key, failed=not succeeded)
        if not succeeded:
            raise UnauthorizedError(
                message="Email or password does not match",
                details={"reason": "wrong_credentials"},
            )
        assert account is not None  # `succeeded` означает найденную учётную запись
        if account.is_disabled:
            raise UnauthorizedError(
                message="The account is disabled",
                details={"reason": "account_disabled"},
            )

        secret = generate_token()
        participant = account.participant
        token = await TokenRepository(session).add(
            Token(
                participant=participant,
                scope=TokenScope.MAIN,
                name=SESSION_TOKEN_NAME,
                token_hash=hash_token(secret),
                expires_at=self._clock() + self._ttl,
                # Сеанс выпускает себе сам человек, вошедший паролем: в списке токенов
                # видно, что вкладку открыл он, а не администратор и не трекер.
                **created_by_columns(participant.author),
            )
        )
        return LiveSession(secret=secret, token=token, account=account)

    async def check(self, session: AsyncSession, secret: str | None) -> LiveSession:
        """Живой сеанс из куки или отказ `unauthorized` с причиной в `details.reason`.

        Причины: `missing_session` — куки нет; `unknown_session` — секрет не токен
        сеанса, токен отозван (выход, смена пароля, отключение) или учётная запись
        отключена; `session_expired` — срок вышел.
        """
        if not secret:
            raise UnauthorizedError(
                message="No live session", details={"reason": "missing_session"}
            )
        token = await TokenRepository(session).get_by_hash(hash_token(secret))
        account = (
            None
            if token is None or token.participant_id is None
            else await AccountRepository(session).get_by_participant(token.participant_id)
        )
        if (
            token is None
            or not token.is_session
            or token.is_revoked
            or account is None
            or account.is_disabled
        ):
            raise UnauthorizedError(
                message="No live session", details={"reason": "unknown_session"}
            )
        if token.expired_at(self._clock()):
            raise UnauthorizedError(
                message="No live session", details={"reason": "session_expired"}
            )
        return LiveSession(secret=secret.strip(), token=token, account=account)

    async def close(self, session: AsyncSession, secret: str | None) -> None:
        """Отзывает токен сеанса из куки, если он есть. Повтор и чужой секрет — не ошибка.

        Отзывается только токен сеанса: кука с секретом другого токена — не сеанс, и
        выход не должен отзывать ключ агента, случайно оказавшийся в куке.
        """
        if not secret:
            return
        token = await TokenRepository(session).get_by_hash(hash_token(secret))
        if token is not None and token.is_session and not token.is_revoked:
            token.revoked_at = self._clock()
            await session.flush()

    def _reserve_attempt(self, address: str, account: str) -> None:
        """Занимает место попытки в окнах адреса, почты и в общем — или отказывает `429`.

        Окно адреса проверяется первым, потом окно почты: исчерпавший своё узнаёт о своём,
        а не о чужом. Отказ не занимает места нигде и строк окон не заводит — поток
        отказов памяти не ест.
        """
        now = self._clock()
        self._forget_old_failures(now)
        keys: tuple[tuple[KeyedScope, str], ...] = (("address", address), ("account", account))
        for scope, key in keys:
            attempts = self._keys[scope].get(key)
            if attempts is not None and (
                len(attempts.failures) + attempts.in_flight >= self._limits[scope]
            ):
                oldest = attempts.failures[0] if attempts.failures else None
                raise self._exceeded(scope, self._limits[scope], oldest, now)
        if len(self._failures) + self._in_flight >= self._limit_total:
            oldest = self._failures[0][0] if self._failures else None
            raise self._exceeded("installation", self._limit_total, oldest, now)
        for scope, key in keys:
            self._keys[scope].setdefault(key, _KeyAttempts()).in_flight += 1
        self._in_flight += 1

    def _finish_attempt(self, address: str, account: str, *, failed: bool) -> None:
        """Освобождает место идущей попытки; неудача остаётся во всех окнах до выхода из них."""
        self._in_flight -= 1
        keys: tuple[tuple[KeyedScope, str], ...] = (("address", address), ("account", account))
        at = self._clock()
        if failed:
            self._failures.append((at, address, account))
        for scope, key in keys:
            attempts = self._keys[scope][key]
            attempts.in_flight -= 1
            if failed:
                attempts.failures.append(at)
            else:
                self._drop_if_idle(scope, key)

    def _drop_if_idle(self, scope: KeyedScope, key: str) -> None:
        attempts = self._keys[scope].get(key)
        if attempts is not None and not attempts.failures and not attempts.in_flight:
            del self._keys[scope][key]

    def _forget_old_failures(self, now: datetime) -> None:
        """Снимает неудачи, вышедшие из окна, — из общего и из окон их адреса и почты.

        Все очереди пополняются одной записью в один момент, поэтому старшая неудача
        общего окна — это и старшая неудача своего адреса и своей почты. Ключ без неудач
        и идущих попыток забывается сразу.
        """
        while self._failures and self._failures[0][0] <= now - self._window:
            _, address, account = self._failures.popleft()
            keys: tuple[tuple[KeyedScope, str], ...] = (
                ("address", address),
                ("account", account),
            )
            for scope, key in keys:
                self._keys[scope][key].failures.popleft()
                self._drop_if_idle(scope, key)

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
