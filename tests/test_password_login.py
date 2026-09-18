"""Вход владельца по паролю: `/api/v1/session`, окно попыток, срок сеанса, команда хеша.

Замок на одну дверь (`docs/CONCEPT.md`, 5.4; TRK-90). Приложение здесь своё, собранное с
паролем, а не общая фикстура `app`: режим задаёт настройка установки, и тест проверяет
ровно то приложение, которое её получило. Часы у сценария подменяются, чтобы проверять
срок сеанса и окно попыток без ожидания.

Токена в этих запросах нет нигде — и это часть проверки: вход по паролю и есть то, чем
браузер получает ключ установки.
"""

import asyncio
import io
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.api.routes.session import SESSION_COOKIE
from app.core.config import Settings
from app.db.session import get_session
from app.domain.passwords import MIN_PASSWORD_LENGTH, PasswordHash, hash_password, verify_password
from app.main import create_app
from app.services import login as login_module
from app.services.login import ATTEMPT_LIMIT, ATTEMPT_WINDOW, PasswordLogin

PASSWORD = "correct horse battery staple"
SESSION_URL = "/api/v1/session"

#: Дешёвый хеш: стоимость scrypt логике входа безразлична, она читает параметры из строки.
HASH = hash_password(PASSWORD, n=2**4, r=1, p=1).render()


class Clock:
    """Часы сценария входа, которые двигает тест."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> Clock:
    return Clock()


@asynccontextmanager
async def client_of(
    settings: Settings, db_session: AsyncSession, clock: Clock | None = None
) -> AsyncIterator[AsyncClient]:
    """Клиент приложения, собранного с этими настройками, на транзакции теста."""
    application = create_app(settings)
    application.dependency_overrides[get_session] = lambda: db_session
    if clock is not None:
        # Тот же вход, что собрал `create_app`, но на часах теста.
        built: PasswordLogin = application.state.password_login
        application.state.password_login = PasswordLogin(
            password_hash=built._hash,
            session_ttl=built._ttl,
            clock=clock,
        )
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://casefile.test") as http_client:
        yield http_client


@pytest.fixture
async def locked(db_session: AsyncSession, clock: Clock) -> AsyncIterator[AsyncClient]:
    """Установка с паролем владельца и сеансом на сутки."""
    settings = Settings(password_hash=HASH, session_hours=24)
    async with client_of(settings, db_session, clock) as http_client:
        yield http_client


def session_cookie(response: Response) -> SimpleCookie:
    """Кука сеанса из ответа, разобранная целиком — с атрибутами."""
    header = response.headers.get("set-cookie")
    assert header is not None, "the response sets no cookie"
    parsed = SimpleCookie()
    parsed.load(header)
    assert SESSION_COOKIE in parsed, header
    return parsed


async def log_in(client: AsyncClient, password: str = PASSWORD, **headers: str) -> Response:
    return await client.post(SESSION_URL, json={"password": password}, headers=headers)


# --- Вход ------------------------------------------------------------------------------


async def test_the_right_password_opens_a_session_in_an_httponly_cookie(
    locked: AsyncClient, clock: Clock
) -> None:
    """Вход ставит куку `HttpOnly`, `SameSite=Strict`, `Path=/` со сроком сеанса.

    Секрета в теле нет: скрипт страницы его не видит, куку шлёт сам браузер.
    """
    response = await log_in(locked)

    assert response.status_code == 200, response.text
    expires_at = datetime.fromisoformat(response.json()["data"]["expires_at"])
    assert expires_at == clock.now + timedelta(hours=24)

    morsel = session_cookie(response)[SESSION_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["samesite"].lower() == "strict"
    assert morsel["path"] == "/"
    assert morsel["expires"]
    # Запрос пришёл по голому HTTP: `Secure` сделал бы куку невидимой на этом же адресе.
    assert not morsel["secure"]
    assert morsel.value not in response.text


async def test_behind_a_tls_proxy_the_cookie_is_secure(locked: AsyncClient) -> None:
    """Прокси с TLS сообщает схему заголовком — кука получает `Secure`."""
    response = await log_in(locked, **{"X-Forwarded-Proto": "https"})

    assert response.status_code == 200, response.text
    assert session_cookie(response)[SESSION_COOKIE]["secure"] is True


async def test_a_wrong_password_is_refused_and_sets_nothing(locked: AsyncClient) -> None:
    response = await log_in(locked, PASSWORD + "!")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["details"] == {"reason": "wrong_password"}
    assert "set-cookie" not in response.headers


async def test_an_extra_field_in_the_login_body_is_refused(locked: AsyncClient) -> None:
    """Имени пользователя у входа нет: пароль у установки один — владельца."""
    response = await locked.post(SESSION_URL, json={"password": PASSWORD, "user": "owner"})

    assert response.status_code == 422


# --- Проверка сеанса -------------------------------------------------------------------


async def test_the_cookie_session_is_live_until_it_expires(
    locked: AsyncClient, clock: Clock
) -> None:
    """`GET` отвечает `200` с тем же сроком, пока сеанс жив, и `401 session_expired` после."""
    opened = await log_in(locked)
    expires_at = opened.json()["data"]["expires_at"]

    live = await locked.get(SESSION_URL)
    assert live.status_code == 200, live.text
    assert live.json()["data"]["expires_at"] == expires_at

    clock.advance(timedelta(hours=24))
    expired = await locked.get(SESSION_URL)
    assert expired.status_code == 401
    assert expired.json()["error"]["details"] == {"reason": "session_expired"}


async def test_without_a_cookie_there_is_no_session(locked: AsyncClient) -> None:
    missing = await locked.get(SESSION_URL)
    forged = await locked.get(SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}=not-a-session"})

    assert missing.status_code == 401
    assert missing.json()["error"]["details"] == {"reason": "missing_session"}
    assert forged.status_code == 401
    assert forged.json()["error"]["details"] == {"reason": "unknown_session"}


async def test_the_session_does_not_need_a_token_and_ignores_one(locked: AsyncClient) -> None:
    """Токен в заголовке ничего не меняет: сеанс решается кукой, а не ключом."""
    response = await locked.get(SESSION_URL, headers={"Authorization": "Bearer trk_nope"})

    assert response.status_code == 401
    assert response.json()["error"]["details"] == {"reason": "missing_session"}


# --- Выход -----------------------------------------------------------------------------


async def test_logout_ends_the_session_on_the_server_and_clears_the_cookie(
    locked: AsyncClient,
) -> None:
    """После выхода та же кука мертва, даже если её сохранили до выхода."""
    await log_in(locked)
    kept = locked.cookies.get(SESSION_COOKIE)
    assert kept

    response = await locked.delete(SESSION_URL)

    assert response.status_code == 204
    assert response.content == b""
    assert session_cookie(response)[SESSION_COOKIE]["max-age"] == "0"
    assert locked.cookies.get(SESSION_COOKIE) is None

    replayed = await locked.get(SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}={kept}"})
    assert replayed.status_code == 401
    assert replayed.json()["error"]["details"] == {"reason": "unknown_session"}


async def test_logout_is_idempotent(locked: AsyncClient) -> None:
    assert (await locked.delete(SESSION_URL)).status_code == 204
    assert (await locked.delete(SESSION_URL)).status_code == 204


async def test_a_new_process_forgets_every_session(db_session: AsyncSession) -> None:
    """Сеансы живут в памяти процесса: перезапуск API (новое приложение) гасит их все."""
    settings = Settings(password_hash=HASH)
    async with client_of(settings, db_session) as first:
        await log_in(first)
        cookie = first.cookies.get(SESSION_COOKIE)
    async with client_of(settings, db_session) as second:
        response = await second.get(SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})

    assert response.status_code == 401
    assert response.json()["error"]["details"] == {"reason": "unknown_session"}


# --- Перебор ---------------------------------------------------------------------------


async def test_attempts_over_the_window_are_refused_even_with_the_right_password(
    locked: AsyncClient, clock: Clock
) -> None:
    """Сверх окна пароль не проверяется вовсе: `429` с `Retry-After`, и верный тоже."""
    for _ in range(ATTEMPT_LIMIT):
        assert (await log_in(locked, "wrong password")).status_code == 401
    clock.advance(timedelta(seconds=10))

    refused = await log_in(locked)

    assert refused.status_code == 429
    error = refused.json()["error"]
    assert error["code"] == "password_attempts_exceeded"
    window = int(ATTEMPT_WINDOW.total_seconds())
    assert error["details"] == {
        "retry_after": window - 10,
        "limit": ATTEMPT_LIMIT,
        "window_seconds": window,
    }
    assert refused.headers["retry-after"] == str(window - 10)
    assert "set-cookie" not in refused.headers

    clock.advance(ATTEMPT_WINDOW)
    assert (await log_in(locked)).status_code == 200


async def test_attempts_in_flight_count_against_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Одновременные попытки занимают окно до исхода: сотня разом не проскочит проверку.

    Проверка пароля держится на событии, пока тест не отпустит: все попытки окна идут
    одновременно, и следующая получает отказ, не дожидаясь их неудач.
    """
    release = threading.Event()
    checked: list[str] = []

    def slow_verify(password: str, stored: PasswordHash) -> bool:
        checked.append(password)
        release.wait(timeout=10)
        return verify_password(password, stored)

    monkeypatch.setattr(login_module, "verify_password", slow_verify)
    login = PasswordLogin(password_hash=PasswordHash.parse(HASH), session_ttl=timedelta(hours=1))

    pending = [asyncio.create_task(login.open("wrong password")) for _ in range(ATTEMPT_LIMIT)]
    await asyncio.sleep(0)
    try:
        with pytest.raises(login_module.PasswordAttemptsExceededError):
            await login.open(PASSWORD)
    finally:
        release.set()
        results = await asyncio.gather(*pending, return_exceptions=True)

    assert PASSWORD not in checked
    assert all(isinstance(result, login_module.UnauthorizedError) for result in results)


# --- Установка без пароля --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "body"), [("POST", {"password": PASSWORD}), ("GET", None), ("DELETE", None)]
)
async def test_without_a_password_hash_there_is_no_login(
    db_session: AsyncSession, method: str, body: dict[str, str] | None
) -> None:
    """Пароль не задан — `409 password_login_off`, а не `401`: неверного ничего не прислали."""
    async with client_of(Settings(password_hash=None), db_session) as unlocked:
        response = await unlocked.request(method, SESSION_URL, json=body)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "password_login_off"


def test_an_empty_hash_from_compose_means_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose передаёт переменную всегда; пустая — «пароля нет», а не испорченный хеш."""
    monkeypatch.setenv("TRACKER_PASSWORD_HASH", "")

    assert Settings().password_hash is None
    assert not create_app(Settings()).state.password_login.enabled


def test_a_malformed_hash_stops_the_api_without_printing_it() -> None:
    """Испорченный хеш роняет сборку приложения, и в отказе нет самой строки."""
    broken = "$scrypt$" + HASH

    with pytest.raises(ValueError) as refused:
        create_app(Settings(password_hash=broken))

    assert "TRACKER_PASSWORD_HASH" in str(refused.value)
    assert broken not in str(refused.value)
    assert HASH not in repr(Settings(password_hash=HASH))


async def test_the_password_never_reaches_the_log(
    locked: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Ни верный, ни неверный пароль не попадают в журнал процесса."""
    caplog.set_level(logging.DEBUG)

    await log_in(locked, "wrong password but long")
    await log_in(locked)

    assert "wrong password but long" not in caplog.text
    assert PASSWORD not in caplog.text


# --- Команда `password-hash` ---------------------------------------------------------


def run_password_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], typed: str
) -> tuple[int, str, str]:
    """Запускает команду с паролем в трубе, как `echo ... | python -m app.cli password-hash`."""
    monkeypatch.setattr("sys.stdin", io.StringIO(typed))
    code = cli.main(["password-hash"])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_command_prints_one_env_line_with_a_working_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """В вывод уходит одна строка для `.env`; пароля нет ни в выводе, ни в пояснениях."""
    code, out, err = run_password_hash(monkeypatch, capsys, f"{PASSWORD}\n")

    assert code == 0
    lines = out.splitlines()
    assert len(lines) == 1, out
    name, _, value = lines[0].partition("=")
    assert name == "TRACKER_PASSWORD_HASH"
    assert verify_password(PASSWORD, PasswordHash.parse(value))
    assert PASSWORD not in out and PASSWORD not in err
    assert ".env" in err


def test_the_command_refuses_a_short_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    short = "x" * (MIN_PASSWORD_LENGTH - 1)
    code, out, err = run_password_hash(monkeypatch, capsys, f"{short}\n")

    assert code == 1
    assert out == ""
    assert str(MIN_PASSWORD_LENGTH) in err
    assert short not in err
