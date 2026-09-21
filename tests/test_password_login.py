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
import ipaddress
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import cli
from app.api.client_address import ClientAddresses, IPAddress
from app.api.routes.session import SESSION_COOKIE
from app.core.config import Settings
from app.db.session import get_session
from app.domain.passwords import MIN_PASSWORD_LENGTH, PasswordHash, hash_password, verify_password
from app.main import create_app
from app.services import login as login_module
from app.services.login import (
    ATTEMPT_LIMIT_PER_ADDRESS,
    ATTEMPT_LIMIT_TOTAL,
    ATTEMPT_WINDOW,
    PasswordLogin,
    client_key,
)

PASSWORD = "correct horse battery staple"
SESSION_URL = "/api/v1/session"

#: Дешёвый хеш: стоимость scrypt логике входа безразлична, она читает параметры из строки.
HASH = hash_password(PASSWORD, n=2**4, r=1, p=1).render()


class Clock:
    """Часы сценария входа, которые двигает тест.

    Точка отсчёта — настоящее время, а не зашитая календарная дата: `expires_at`,
    который приложение считает от этих часов, едет в `Set-Cookie` (`Expires`), а куку
    после ответа хранит `http.cookiejar.CookieJar` клиента `httpx.AsyncClient` — и
    решает, жива ли она, по **настоящим** часам машины, не по часам сценария. Зашитая
    дата в прошлом (или ставшая прошлым за счёт течения времени) делает такую куку
    просроченной для клиента раньше, чем истечёт для сервера, и тест ложно краснеет
    без единой правки кода — ровно так это и случилось (TRK-103): дата, вморожённая на
    день написания теста, тремя днями позже уже была в прошлом. Отсчёт от настоящего
    времени держит `Expires` в будущем всегда, независимо от календаря на машине
    прогона; сдвиги `advance()` по-прежнему детерминированы относительно этой точки —
    проверки срока и окна остаются точными.
    """

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> Clock:
    return Clock()


def application_of(
    settings: Settings, db_session: AsyncSession, clock: Clock | None = None
) -> FastAPI:
    """Приложение, собранное с этими настройками, на транзакции теста."""
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
    return application


@asynccontextmanager
async def client_from(application: FastAPI, peer: str = "127.0.0.1") -> AsyncIterator[AsyncClient]:
    """Клиент, чьё соединение с приложением открыто с адреса `peer`.

    Один и тот же `application` — одни и те же окна попыток: так два клиента с разных
    адресов видят общий процесс API, как в жизни.
    """
    transport = ASGITransport(app=application, client=(peer, 123))
    async with AsyncClient(transport=transport, base_url="http://casefile.test") as http_client:
        yield http_client


@asynccontextmanager
async def client_of(
    settings: Settings, db_session: AsyncSession, clock: Clock | None = None
) -> AsyncIterator[AsyncClient]:
    """Клиент приложения, собранного с этими настройками, на транзакции теста."""
    async with client_from(application_of(settings, db_session, clock)) as http_client:
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


def refusal(response: Response) -> dict[str, object]:
    """Подробности отказа `429` — после проверки, что это он."""
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "password_attempts_exceeded"
    assert response.headers["retry-after"] == str(error["details"]["retry_after"])
    assert "set-cookie" not in response.headers
    details: dict[str, object] = error["details"]
    return details


@pytest.fixture
def locked_app(db_session: AsyncSession, clock: Clock) -> FastAPI:
    """Установка с паролем, API которой клиенты видят напрямую — без прокси впереди."""
    return application_of(Settings(password_hash=HASH, session_hours=24), db_session, clock)


#: Адрес nginx интерфейса в сети контура и два клиента за ним. Адреса — из блоков для
#: документации (RFC 5737), чтобы не спутать их ни с чьими настоящими.
NGINX = "172.18.0.5"
GUESSER = "203.0.113.7"
OWNER = "198.51.100.20"


@pytest.fixture
def behind_nginx(db_session: AsyncSession, clock: Clock) -> FastAPI:
    """Установка, где API верит `X-Real-IP` только от своего nginx — как в прод-контуре."""
    settings = Settings(password_hash=HASH, session_hours=24, real_ip_from=[NGINX])
    return application_of(settings, db_session, clock)


async def test_attempts_over_the_window_are_refused_even_with_the_right_password(
    locked: AsyncClient, clock: Clock
) -> None:
    """Сверх окна адреса пароль не проверяется вовсе: `429` с `Retry-After`, и верный тоже."""
    for _ in range(ATTEMPT_LIMIT_PER_ADDRESS):
        assert (await log_in(locked, "wrong password")).status_code == 401
    clock.advance(timedelta(seconds=10))

    refused = await log_in(locked)

    window = int(ATTEMPT_WINDOW.total_seconds())
    assert refusal(refused) == {
        "retry_after": window - 10,
        "limit": ATTEMPT_LIMIT_PER_ADDRESS,
        "window_seconds": window,
        "scope": "address",
    }

    clock.advance(ATTEMPT_WINDOW)
    assert (await log_in(locked)).status_code == 200


async def test_a_guesser_does_not_lock_out_the_owner_signing_in_from_another_address(
    locked_app: FastAPI,
) -> None:
    """С одного адреса идут непрерывные неудачи, а верный пароль с другого проходит.

    Перебирающий упирается в своё окно, и дальше его попытки отказываются, не занимая
    места: общий потолок он не выбирает, сколько бы ни старался.
    """
    async with client_from(locked_app, GUESSER) as guesser, client_from(locked_app, OWNER) as owner:
        outcomes = [
            (await log_in(guesser, f"guess number {n}")).status_code
            for n in range(ATTEMPT_LIMIT_TOTAL * 2)
        ]
        signed_in = await log_in(owner)

    assert outcomes[:ATTEMPT_LIMIT_PER_ADDRESS] == [401] * ATTEMPT_LIMIT_PER_ADDRESS
    assert set(outcomes[ATTEMPT_LIMIT_PER_ADDRESS:]) == {429}
    assert signed_in.status_code == 200, signed_in.text
    assert session_cookie(signed_in)[SESSION_COOKIE].value


async def test_guessing_from_many_addresses_stops_at_the_installation_ceiling(
    locked_app: FastAPI, clock: Clock
) -> None:
    """Перебор со многих адресов упирается в общий потолок — и тогда ждут все, владелец тоже.

    Это названная цена (`TRK-98#7`): распределённый перебор держит установку перед `429`,
    пока идёт, но подбирать быстрее потолка не может.
    """
    guessers = ATTEMPT_LIMIT_TOTAL // ATTEMPT_LIMIT_PER_ADDRESS
    for number in range(guessers):
        async with client_from(locked_app, f"203.0.113.{number + 1}") as guesser:
            for _ in range(ATTEMPT_LIMIT_PER_ADDRESS):
                assert (await log_in(guesser, "wrong password")).status_code == 401
    clock.advance(timedelta(seconds=15))

    async with client_from(locked_app, OWNER) as owner:
        refused = await log_in(owner)
        window = int(ATTEMPT_WINDOW.total_seconds())
        assert refusal(refused) == {
            "retry_after": window - 15,
            "limit": ATTEMPT_LIMIT_TOTAL,
            "window_seconds": window,
            "scope": "installation",
        }

        clock.advance(ATTEMPT_WINDOW)
        assert (await log_in(owner)).status_code == 200


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded"])
async def test_a_forged_address_header_without_a_trusted_proxy_does_not_widen_the_window(
    locked_app: FastAPI, header: str
) -> None:
    """Подделанный заголовок с адресом не даёт новых окон: перебор ограничен, как был.

    Никто не назван доверенным — клиент это тот, кто открыл соединение, что бы он ни
    написал о себе. Каждая попытка называет себя новым адресом, а окно у всех одно.
    """
    async with client_from(locked_app, GUESSER) as guesser:
        outcomes = []
        for number in range(ATTEMPT_LIMIT_TOTAL):
            forged = f"192.0.2.{number + 1}"
            value = f"for={forged}" if header == "Forwarded" else forged
            response = await log_in(guesser, "wrong password", **{header: value})
            outcomes.append(response.status_code)

    assert outcomes.count(401) == ATTEMPT_LIMIT_PER_ADDRESS
    assert outcomes[ATTEMPT_LIMIT_PER_ADDRESS:] == [429] * (
        ATTEMPT_LIMIT_TOTAL - ATTEMPT_LIMIT_PER_ADDRESS
    )


async def test_behind_the_installation_nginx_the_client_is_its_x_real_ip(
    behind_nginx: FastAPI,
) -> None:
    """За своим nginx клиент — его `X-Real-IP`: перебор одного не держит другого."""
    async with client_from(behind_nginx, NGINX) as via_nginx:
        for _ in range(ATTEMPT_LIMIT_PER_ADDRESS):
            guessed = await log_in(via_nginx, "wrong password", **{"X-Real-IP": GUESSER})
            assert guessed.status_code == 401
        refused = await log_in(via_nginx, **{"X-Real-IP": GUESSER})
        signed_in = await log_in(via_nginx, **{"X-Real-IP": OWNER})

    assert refusal(refused)["scope"] == "address"
    assert signed_in.status_code == 200, signed_in.text


async def test_the_api_reads_no_forwarding_chain_even_from_its_nginx(
    behind_nginx: FastAPI,
) -> None:
    """`X-Forwarded-For` не значит ничего и от своего nginx: цепочку разбирает nginx.

    nginx пишет адрес клиента в `X-Real-IP` сам, перезаписывая присланный; цепочка
    `X-Forwarded-For`, которую он пропускает дальше, начинается тем, что написал клиент.
    """
    async with client_from(behind_nginx, NGINX) as via_nginx:
        outcomes = [
            (
                await log_in(
                    via_nginx,
                    "wrong password",
                    **{"X-Real-IP": GUESSER, "X-Forwarded-For": f"192.0.2.{n + 1}, {GUESSER}"},
                )
            ).status_code
            for n in range(ATTEMPT_LIMIT_PER_ADDRESS + 3)
        ]

    assert outcomes.count(401) == ATTEMPT_LIMIT_PER_ADDRESS
    assert outcomes[-1] == 429


async def test_a_forged_x_real_ip_from_a_peer_that_is_not_the_nginx_is_ignored(
    behind_nginx: FastAPI,
) -> None:
    """`X-Real-IP` от собеседника не из списка — просто заголовок: клиент — сам собеседник.

    Так случилось бы, если бы порт API кто-то опубликовал в обход nginx: прямой клиент
    называет себя новым адресом на каждой попытке и всё равно упирается в своё окно.
    """
    async with client_from(behind_nginx, GUESSER) as direct:
        outcomes = [
            (
                await log_in(direct, "wrong password", **{"X-Real-IP": f"192.0.2.{n + 1}"})
            ).status_code
            for n in range(ATTEMPT_LIMIT_TOTAL)
        ]

    assert outcomes.count(401) == ATTEMPT_LIMIT_PER_ADDRESS
    assert outcomes[ATTEMPT_LIMIT_PER_ADDRESS:] == [429] * (
        ATTEMPT_LIMIT_TOTAL - ATTEMPT_LIMIT_PER_ADDRESS
    )


async def test_a_trusted_peer_without_a_usable_x_real_ip_is_the_client_itself(
    behind_nginx: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    """Свой nginx заголовок ставит всегда; нет его или в нём мусор — клиент сам собеседник."""
    caplog.set_level(logging.WARNING)
    async with client_from(behind_nginx, NGINX) as via_nginx:
        for value in ["not an address", "", "203.0.113.7:4431"]:
            await log_in(via_nginx, "wrong password", **{"X-Real-IP": value})
        await log_in(via_nginx, "wrong password")
        await log_in(via_nginx, "wrong password")
        refused = await log_in(via_nginx, **{"X-Real-IP": "   "})

    assert refusal(refused)["scope"] == "address"
    assert "sent no usable x-real-ip header" in caplog.text


class Resolver:
    """DNS для теста: имя → адреса, со счётчиком обращений."""

    def __init__(self, table: dict[str, set[str]]) -> None:
        self.table = table
        self.calls = 0

    async def __call__(self, name: str) -> frozenset[IPAddress]:
        self.calls += 1
        if name not in self.table:
            raise OSError(f"{name} does not resolve")
        return frozenset(ipaddress.ip_address(address) for address in self.table[name])


class Monotonic:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def request_from(peer: str, real_ip: str = OWNER) -> Request:
    """Запрос, пришедший с адреса `peer` с заголовком `X-Real-IP`."""
    return Request(
        {"type": "http", "headers": [(b"x-real-ip", real_ip.encode())], "client": (peer, 1)}
    )


async def test_a_trusted_proxy_named_by_host_follows_its_address() -> None:
    """Имя службы (`ui`) разрешается при входе: пересозданный с новым адресом nginx — свой.

    Разрешённое имя помнится несколько секунд — поток отказов не ходит в DNS на каждой
    попытке, — а не разрешившееся имя не доверяет никому.
    """
    resolver = Resolver({"ui": {NGINX}})
    monotonic = Monotonic()
    addresses = ClientAddresses(["ui"], resolve=resolver, clock=monotonic, ttl=5.0)

    assert str(await addresses.of(request_from(NGINX))) == OWNER
    assert str(await addresses.of(request_from(GUESSER))) == GUESSER
    assert resolver.calls == 1

    # `ui` пересоздан с новым адресом. Пока помнится старый, новый — чужой.
    resolver.table["ui"] = {"172.18.0.9"}
    assert str(await addresses.of(request_from("172.18.0.9"))) == "172.18.0.9"
    monotonic.now += 5.0
    assert str(await addresses.of(request_from("172.18.0.9"))) == OWNER
    assert resolver.calls == 2

    # Имя не разрешилось (служба остановлена) — доверия нет.
    del resolver.table["ui"]
    monotonic.now += 5.0
    assert str(await addresses.of(request_from("172.18.0.9"))) == "172.18.0.9"


async def test_a_trusted_network_needs_no_resolution() -> None:
    """Адрес или сеть в списке сверяются без DNS; клиент без адреса — неизвестен."""
    resolver = Resolver({})
    addresses = ClientAddresses(["172.18.0.0/16"], resolve=resolver)

    assert str(await addresses.of(request_from(NGINX))) == OWNER
    assert str(await addresses.of(request_from(GUESSER))) == GUESSER
    assert await addresses.of(Request({"type": "http", "headers": [], "client": None})) is None
    assert resolver.calls == 0


def test_the_trusted_peers_setting_takes_addresses_networks_and_names() -> None:
    """Список через запятую, пустая строка — никого, опечатка роняет старт."""
    assert Settings(real_ip_from="ui, 10.0.0.0/8,fd00::1").real_ip_from == [
        "ui",
        "10.0.0.0/8",
        "fd00::1",
    ]
    assert Settings(real_ip_from="").real_ip_from == []

    with pytest.raises(ValidationError, match="not an IP address, a network or a host name"):
        Settings(real_ip_from="ui/api")


def test_an_ipv6_client_is_its_64_network_and_a_mapped_ipv4_is_ipv4() -> None:
    """Одна машина IPv6 владеет целой `/64`: окно на отдельный адрес она обходила бы даром."""
    first = client_key(ipaddress.ip_address("2001:db8:1:2::1"))
    second = client_key(ipaddress.ip_address("2001:db8:1:2:ffff::9"))
    neighbour = client_key(ipaddress.ip_address("2001:db8:1:3::1"))

    assert first == second == "2001:db8:1:2::/64"
    assert neighbour != first
    assert client_key(ipaddress.ip_address("::ffff:203.0.113.7")) == GUESSER
    assert client_key(None) == login_module.UNKNOWN_CLIENT


async def test_the_counters_never_hold_more_addresses_than_the_ceiling() -> None:
    """Адрес помнится, пока у него неудача в окне или идущая попытка, — их не больше потолка.

    Сотни адресов, по одной неудаче каждый, со сдвигом часов: словарь адресов не растёт
    выше потолка, отказанные адреса в нём не заводятся, а после окна он пустеет.
    """
    clock = Clock()
    login = PasswordLogin(
        password_hash=PasswordHash.parse(HASH), session_ttl=timedelta(hours=1), clock=clock
    )
    largest = 0
    for number in range(300):
        address = ipaddress.ip_address(f"10.0.{number // 250}.{number % 250 + 1}")
        with pytest.raises(
            (login_module.UnauthorizedError, login_module.PasswordAttemptsExceededError)
        ):
            await login.open("wrong password", address)
        largest = max(largest, len(login._clients))
        clock.advance(timedelta(seconds=1))

    assert largest <= ATTEMPT_LIMIT_TOTAL
    assert len(login._clients) <= ATTEMPT_LIMIT_TOTAL

    clock.advance(ATTEMPT_WINDOW)
    await login.open(PASSWORD, ipaddress.ip_address(OWNER))
    assert login._clients == {}


async def test_attempts_in_flight_count_against_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Одновременные попытки занимают окно до исхода: сотня разом не проскочит проверку.

    Проверка пароля держится на событии, пока тест не отпустит: все попытки окна адреса
    идут одновременно, и следующая с того же адреса получает отказ, не дожидаясь их
    неудач, — а попытка с другого адреса проходит.
    """
    release = threading.Event()
    checked: list[str] = []

    def slow_verify(password: str, stored: PasswordHash) -> bool:
        checked.append(password)
        release.wait(timeout=10)
        return verify_password(password, stored)

    monkeypatch.setattr(login_module, "verify_password", slow_verify)
    login = PasswordLogin(password_hash=PasswordHash.parse(HASH), session_ttl=timedelta(hours=1))
    guesser = ipaddress.ip_address(GUESSER)

    pending = [
        asyncio.create_task(login.open("wrong password", guesser))
        for _ in range(ATTEMPT_LIMIT_PER_ADDRESS)
    ]
    await asyncio.sleep(0)
    try:
        with pytest.raises(login_module.PasswordAttemptsExceededError) as refused:
            await login.open(PASSWORD, guesser)
        owner = asyncio.create_task(login.open(PASSWORD, ipaddress.ip_address(OWNER)))
        await asyncio.sleep(0)
    finally:
        release.set()
        results = await asyncio.gather(*pending, return_exceptions=True)

    assert refused.value.details["scope"] == "address"
    assert (await owner).expires_at
    assert checked.count(PASSWORD) == 1
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
