"""Вход по почте и паролю: `/api/v1/session`, токен сеанса, окна попыток.

`docs/CONCEPT.md`, 5.4 (TRK-113). Приложение здесь своё, собранное с настройками
теста, а не общая фикстура `app`: часы входа подменяются, чтобы проверять срок сеанса и
окна попыток без ожидания.

Токена в запросах входа нет нигде — и это часть проверки: вход и есть то, чем браузер
получает свой токен. Дальше вкладка ходит этим токеном, как любой клиент.
"""

import asyncio
import ipaddress
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.client_address import ClientAddresses, IPAddress
from app.api.routes.session import SESSION_COOKIE
from app.core.config import Settings
from app.db.models.account import Account
from app.db.models.author import created_by_columns
from app.db.repositories import TokenRepository
from app.db.session import get_session
from app.domain.participants import ParticipantKind
from app.domain.passwords import PasswordHash, hash_password, verify_password
from app.domain.tokens import TokenScope, hash_token
from app.main import create_app
from app.services import accounts as accounts_service
from app.services import login as login_module
from app.services import participants as participants_service
from app.services.auth import TRACKER_ACTOR
from app.services.login import (
    ATTEMPT_LIMIT_PER_ACCOUNT,
    ATTEMPT_LIMIT_PER_ADDRESS,
    ATTEMPT_LIMIT_TOTAL,
    ATTEMPT_WINDOW,
    SESSION_TOKEN_NAME,
    PasswordLogin,
    client_key,
)

PASSWORD = "correct horse battery staple"
SESSION_URL = "/api/v1/session"
ALICE = "alice@example.com"
BOB = "bob@example.com"

#: Дешёвый хеш: стоимость scrypt логике входа безразлична, она читает параметры из строки.
HASH = hash_password(PASSWORD, n=2**4, r=1, p=1).render()


class Clock:
    """Часы сценария входа, которые двигает тест.

    Точка отсчёта — настоящее время, а не зашитая календарная дата: `expires_at`,
    который приложение считает от этих часов, едет в `Set-Cookie` (`Expires`), а куку
    после ответа хранит `http.cookiejar.CookieJar` клиента `httpx.AsyncClient` — и
    решает, жива ли она, по **настоящим** часам машины. Зашитая дата в прошлом делает
    такую куку просроченной для клиента раньше, чем для сервера (TRK-103).
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


async def make_account(
    db_session: AsyncSession,
    name: str,
    email: str,
    *,
    password_hash: str | None = HASH,
    is_admin: bool = False,
) -> Account:
    """Человек с учётной записью — строкой прямо в базе, с дешёвым хешем пароля."""
    participant = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.HUMAN, name=name
    )
    account = Account(
        participant=participant,
        email=email,
        password_hash=password_hash,
        is_admin=is_admin,
        **created_by_columns(TRACKER_ACTOR.author),
    )
    db_session.add(account)
    await db_session.flush()
    return account


@pytest.fixture
async def alice(db_session: AsyncSession) -> Account:
    return await make_account(db_session, "alice", ALICE, is_admin=True)


@pytest.fixture
async def bob(db_session: AsyncSession) -> Account:
    return await make_account(db_session, "bob", BOB)


def application_of(
    db_session: AsyncSession, clock: Clock | None = None, **overrides: Any
) -> FastAPI:
    """Приложение с сеансом на сутки (и настройками теста) на транзакции теста."""
    settings = Settings(session_hours=24, **overrides)
    application = create_app(settings)
    application.dependency_overrides[get_session] = lambda: db_session
    if clock is not None:
        # Тот же вход, что собрал `create_app`, но на часах теста.
        application.state.password_login = PasswordLogin(
            session_ttl=timedelta(hours=settings.session_hours), clock=clock
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


@pytest.fixture
def signin_app(db_session: AsyncSession, clock: Clock, alice: Account, bob: Account) -> FastAPI:
    """Установка с двумя людьми, API которой клиенты видят напрямую — без прокси впереди."""
    return application_of(db_session, clock)


@pytest.fixture
async def signin(signin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_from(signin_app) as http_client:
        yield http_client


def session_cookie(response: Response) -> SimpleCookie:
    """Кука сеанса из ответа, разобранная целиком — с атрибутами."""
    header = response.headers.get("set-cookie")
    assert header is not None, "the response sets no cookie"
    parsed = SimpleCookie()
    parsed.load(header)
    assert SESSION_COOKIE in parsed, header
    return parsed


async def log_in(
    client: AsyncClient, email: str = ALICE, password: str = PASSWORD, **headers: str
) -> Response:
    return await client.post(
        SESSION_URL, json={"email": email, "password": password}, headers=headers
    )


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


# --- Вход ------------------------------------------------------------------------------


async def test_the_right_password_opens_a_session_token_in_an_httponly_cookie(
    signin: AsyncClient, clock: Clock, db_session: AsyncSession, alice: Account
) -> None:
    """Вход выпускает токен сеанса и ставит его секрет в куку `HttpOnly` со сроком.

    Тот же секрет приходит в `data.token`: им вкладка ходит в REST. Токен — набора
    `main`, участника учётной записи, со сроком сеанса, и выпустил его сам человек.
    """
    response = await log_in(signin)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert datetime.fromisoformat(data["expires_at"]) == clock.now + timedelta(hours=24)
    assert data["account"]["email"] == ALICE
    assert data["account"]["participant"] == "alice"
    assert data["account"]["is_admin"] is True

    morsel = session_cookie(response)[SESSION_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["samesite"].lower() == "strict"
    assert morsel["path"] == "/"
    assert morsel["expires"]
    # Запрос пришёл по голому HTTP: `Secure` сделал бы куку невидимой на этом же адресе.
    assert not morsel["secure"]
    assert morsel.value == data["token"]

    token = await TokenRepository(db_session).get_by_hash(hash_token(data["token"]))
    assert token is not None
    assert token.participant_id == alice.participant_id
    assert token.scope is TokenScope.MAIN
    assert token.name == SESSION_TOKEN_NAME
    assert token.expires_at == clock.now + timedelta(hours=24)
    assert token.created_by.signature == "alice"


async def test_behind_a_tls_proxy_the_cookie_is_secure(signin: AsyncClient) -> None:
    """Прокси с TLS сообщает схему заголовком — кука получает `Secure`."""
    response = await log_in(signin, **{"X-Forwarded-Proto": "https"})

    assert response.status_code == 200, response.text
    assert session_cookie(response)[SESSION_COOKIE]["secure"] is True


@pytest.mark.parametrize(
    ("email", "password"),
    [(ALICE, PASSWORD + "!"), ("nobody@example.com", PASSWORD), (BOB, "x" * 20)],
)
async def test_a_wrong_password_and_an_unknown_email_are_refused_alike(
    signin: AsyncClient, email: str, password: str
) -> None:
    """Неверный пароль и незаведённая почта неразличимы: ответ не выдаёт, кто заведён."""
    response = await log_in(signin, email, password)

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized",
        "message": "Email or password does not match",
        "details": {"reason": "wrong_credentials"},
    }
    assert "set-cookie" not in response.headers


async def test_the_email_matches_ignoring_case(signin: AsyncClient) -> None:
    response = await log_in(signin, "  Alice@Example.COM ")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["account"]["email"] == ALICE


async def test_an_account_without_a_password_cannot_sign_in(
    db_session: AsyncSession, clock: Clock
) -> None:
    """Учётная запись, заведённая установкой себе (`owner@localhost`), паролем не входит."""
    await make_account(db_session, "owner", "owner@localhost", password_hash=None, is_admin=True)
    async with client_from(application_of(db_session, clock)) as http_client:
        response = await log_in(http_client, "owner@localhost", PASSWORD)

    assert response.status_code == 401
    assert response.json()["error"]["details"] == {"reason": "wrong_credentials"}


@pytest.mark.parametrize(
    "body",
    [
        {"password": PASSWORD},
        {"email": ALICE},
        {"email": ALICE, "password": PASSWORD, "user": "alice"},
    ],
)
async def test_the_login_body_is_exactly_email_and_password(
    signin: AsyncClient, body: dict[str, str]
) -> None:
    response = await signin.post(SESSION_URL, json=body)

    assert response.status_code == 422


# --- Токен сеанса — ключ вкладки -------------------------------------------------------


async def test_the_session_token_signs_what_the_person_does(signin: AsyncClient) -> None:
    """Токен сеанса — обычный токен REST: «кто я» — этот человек, и его имя — подпись."""
    token = (await log_in(signin, BOB)).json()["data"]["token"]

    me = await signin.get("/api/v1/bootstrap", headers=bearer(token))
    registered = await signin.post(
        "/api/v1/participants",
        json={"kind": "agent", "name": "bobs_agent"},
        headers=bearer(token),
    )

    assert me.status_code == 200, me.text
    assert me.json()["data"]["participant"]["name"] == "bob"
    assert me.json()["data"]["account"]["email"] == BOB
    assert me.json()["data"]["token"]["scope"] == "main"
    assert registered.status_code == 201, registered.text
    assert registered.json()["data"]["created_by"] == {"kind": "human", "signature": "bob"}


async def test_the_cookie_hands_the_tab_its_token_until_the_session_expires(
    signin: AsyncClient, clock: Clock
) -> None:
    """`GET` отвечает тем же токеном и сроком, пока сеанс жив, и `session_expired` после."""
    opened = (await log_in(signin)).json()["data"]

    live = await signin.get(SESSION_URL)
    assert live.status_code == 200, live.text
    assert live.json()["data"]["token"] == opened["token"]
    assert live.json()["data"]["expires_at"] == opened["expires_at"]

    clock.advance(timedelta(hours=24))
    expired = await signin.get(SESSION_URL)
    assert expired.status_code == 401
    assert expired.json()["error"]["details"] == {"reason": "session_expired"}


async def test_without_a_session_cookie_there_is_no_session(
    signin: AsyncClient, main_secret: str
) -> None:
    """Кука с чужим секретом — не сеанс, даже если это действующий токен без срока."""
    missing = await signin.get(SESSION_URL)
    forged = await signin.get(SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}=not-a-session"})
    not_a_session = await signin.get(
        SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}={main_secret}"}
    )

    assert missing.status_code == 401
    assert missing.json()["error"]["details"] == {"reason": "missing_session"}
    for response in (forged, not_a_session):
        assert response.status_code == 401
        assert response.json()["error"]["details"] == {"reason": "unknown_session"}


async def test_the_session_ignores_a_token_in_the_header(signin: AsyncClient) -> None:
    """Сеанс решается кукой: токен в заголовке его не открывает."""
    token = (await log_in(signin)).json()["data"]["token"]
    signin.cookies.clear()

    response = await signin.get(SESSION_URL, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["details"] == {"reason": "missing_session"}


async def test_a_session_survives_a_restart_of_the_api(
    db_session: AsyncSession, alice: Account
) -> None:
    """Сеанс — токен в базе: новое приложение (перезапуск API) видит его, как прежнее."""
    async with client_from(application_of(db_session)) as first:
        opened = await log_in(first)
        cookie = first.cookies.get(SESSION_COOKIE)
    async with client_from(application_of(db_session)) as second:
        response = await second.get(SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["token"] == opened.json()["data"]["token"]


# --- Выход -----------------------------------------------------------------------------


async def test_sign_out_revokes_the_session_token_and_clears_the_cookie(
    signin: AsyncClient,
) -> None:
    """После выхода мертва и кука, и токен вкладки — сразу, а не на перезагрузке."""
    token = (await log_in(signin)).json()["data"]["token"]
    kept = signin.cookies.get(SESSION_COOKIE)

    response = await signin.delete(SESSION_URL)

    assert response.status_code == 204
    assert response.content == b""
    assert session_cookie(response)[SESSION_COOKIE]["max-age"] == "0"
    assert signin.cookies.get(SESSION_COOKIE) is None

    replayed = await signin.get(SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}={kept}"})
    assert replayed.json()["error"]["details"] == {"reason": "unknown_session"}
    tab = await signin.get("/api/v1/bootstrap", headers=bearer(token))
    assert tab.status_code == 401
    assert tab.json()["error"]["details"] == {"reason": "token_revoked"}


async def test_sign_out_is_idempotent(signin: AsyncClient) -> None:
    assert (await signin.delete(SESSION_URL)).status_code == 204
    assert (await signin.delete(SESSION_URL)).status_code == 204


async def test_sign_out_does_not_revoke_a_token_that_is_not_a_session(
    signin: AsyncClient, main_secret: str
) -> None:
    """Ключ агента, попавший в куку, выход не отзывает: выход закрывает только сеанс."""
    response = await signin.delete(
        SESSION_URL, headers={"Cookie": f"{SESSION_COOKIE}={main_secret}"}
    )

    assert response.status_code == 204
    assert (await signin.get("/api/v1/bootstrap", headers=bearer(main_secret))).status_code == 200


# --- Отключённая учётная запись --------------------------------------------------------


async def test_a_disabled_account_cannot_sign_in_and_says_so_only_to_the_right_password(
    signin: AsyncClient, db_session: AsyncSession, bob: Account
) -> None:
    """Отключение говорит о себе только знающему пароль: перебирающему — `wrong_credentials`."""
    await accounts_service.update_account(db_session, bob, actor=TRACKER_ACTOR, disabled=True)

    right = await log_in(signin, BOB)
    wrong = await log_in(signin, BOB, "wrong password")

    assert right.status_code == 401
    assert right.json()["error"]["details"] == {"reason": "account_disabled"}
    assert "set-cookie" not in right.headers
    assert wrong.json()["error"]["details"] == {"reason": "wrong_credentials"}


async def test_disabling_an_account_ends_its_live_session(
    signin: AsyncClient, db_session: AsyncSession, bob: Account
) -> None:
    token = (await log_in(signin, BOB)).json()["data"]["token"]

    await accounts_service.update_account(db_session, bob, actor=TRACKER_ACTOR, disabled=True)

    session = await signin.get(SESSION_URL)
    tab = await signin.get("/api/v1/bootstrap", headers=bearer(token))
    assert session.json()["error"]["details"] == {"reason": "unknown_session"}
    assert tab.json()["error"]["details"] == {"reason": "token_revoked"}


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


#: Адрес nginx интерфейса в сети контура и клиенты. Адреса — из блоков для
#: документации (RFC 5737), чтобы не спутать их ни с чьими настоящими.
NGINX = "172.18.0.5"
GUESSER = "203.0.113.7"
OWNER = "198.51.100.20"


@pytest.fixture
def behind_nginx(db_session: AsyncSession, clock: Clock, alice: Account, bob: Account) -> FastAPI:
    """Установка, где API верит `X-Real-IP` только от своего nginx — как в прод-контуре."""
    return application_of(db_session, clock, real_ip_from=[NGINX])


async def test_attempts_over_the_address_window_are_refused_even_with_the_right_password(
    signin: AsyncClient, clock: Clock
) -> None:
    """Сверх окна адреса пароль не проверяется вовсе: `429` с `Retry-After`, и верный тоже.

    Неудачи — по разным почтам, чтобы упереться именно в окно адреса, а не почты.
    """
    for number in range(ATTEMPT_LIMIT_PER_ADDRESS):
        assert (await log_in(signin, f"guess{number}@example.com", "x")).status_code == 401
    clock.advance(timedelta(seconds=10))

    refused = await log_in(signin)

    window = int(ATTEMPT_WINDOW.total_seconds())
    assert refusal(refused) == {
        "retry_after": window - 10,
        "limit": ATTEMPT_LIMIT_PER_ADDRESS,
        "window_seconds": window,
        "scope": "address",
    }

    clock.advance(ATTEMPT_WINDOW)
    assert (await log_in(signin)).status_code == 200


async def test_guessing_one_account_from_many_addresses_stops_at_its_window(
    signin_app: FastAPI, clock: Clock
) -> None:
    """Перебор пароля одного человека со многих адресов упирается в окно его почты.

    Остальных людей он не трогает: Боб входит с ещё одного адреса как обычно. Цена
    названа (`CONCEPT.md`, 5.4): сама Алиса ждёт, пока окно её почты не освободится.
    """
    for number in range(ATTEMPT_LIMIT_PER_ACCOUNT):
        async with client_from(signin_app, f"203.0.113.{number + 1}") as guesser:
            assert (await log_in(guesser, ALICE, "wrong password")).status_code == 401
    clock.advance(timedelta(seconds=5))

    async with client_from(signin_app, "203.0.113.200") as another:
        refused = await log_in(another, ALICE)
    async with client_from(signin_app, OWNER) as colleague:
        signed_in = await log_in(colleague, BOB)

    window = int(ATTEMPT_WINDOW.total_seconds())
    assert refusal(refused) == {
        "retry_after": window - 5,
        "limit": ATTEMPT_LIMIT_PER_ACCOUNT,
        "window_seconds": window,
        "scope": "account",
    }
    assert signed_in.status_code == 200, signed_in.text


async def test_a_guesser_does_not_lock_out_another_person_signing_in_from_another_address(
    signin_app: FastAPI,
) -> None:
    """С одного адреса идут непрерывные неудачи, а верный пароль Боба с другого проходит.

    Перебирающий упирается в своё окно, и дальше его попытки отказываются, не занимая
    места: общий потолок он не выбирает, сколько бы ни старался.
    """
    async with client_from(signin_app, GUESSER) as guesser, client_from(signin_app, OWNER) as bob:
        outcomes = [
            (await log_in(guesser, ALICE, f"guess number {n}")).status_code
            for n in range(ATTEMPT_LIMIT_PER_ADDRESS * 4)
        ]
        signed_in = await log_in(bob, BOB)

    assert outcomes[:ATTEMPT_LIMIT_PER_ADDRESS] == [401] * ATTEMPT_LIMIT_PER_ADDRESS
    assert set(outcomes[ATTEMPT_LIMIT_PER_ADDRESS:]) == {429}
    assert signed_in.status_code == 200, signed_in.text


async def test_guessing_spread_over_addresses_and_accounts_stops_at_the_ceiling(
    db_session: AsyncSession, clock: Clock, bob: Account
) -> None:
    """Перебор, разнесённый и по адресам, и по почтам, упирается в общий потолок.

    Потолок — защита процессора, а не окно входа, и цена у него прежняя: пока он
    выбран, ждут все, Боб тоже.
    """
    pairs = ATTEMPT_LIMIT_TOTAL // ATTEMPT_LIMIT_PER_ADDRESS
    for number in range(pairs):
        await make_account(db_session, f"person_{number}", f"person{number}@example.com")
    application = application_of(db_session, clock)
    for number in range(pairs):
        async with client_from(application, f"203.0.113.{number + 1}") as guesser:
            for _ in range(ATTEMPT_LIMIT_PER_ADDRESS):
                response = await log_in(guesser, f"person{number}@example.com", "wrong")
                assert response.status_code == 401
    clock.advance(timedelta(seconds=15))

    async with client_from(application, OWNER) as colleague:
        refused = await log_in(colleague, BOB)
        window = int(ATTEMPT_WINDOW.total_seconds())
        assert refusal(refused) == {
            "retry_after": window - 15,
            "limit": ATTEMPT_LIMIT_TOTAL,
            "window_seconds": window,
            "scope": "installation",
        }

        clock.advance(ATTEMPT_WINDOW)
        assert (await log_in(colleague, BOB)).status_code == 200


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded"])
async def test_a_forged_address_header_without_a_trusted_proxy_does_not_widen_the_window(
    signin_app: FastAPI, header: str
) -> None:
    """Подделанный заголовок с адресом не даёт новых окон: перебор ограничен, как был.

    Никто не назван доверенным — клиент это тот, кто открыл соединение, что бы он ни
    написал о себе. Каждая попытка называет себя новым адресом и новой почтой, а окно
    адреса у всех одно.
    """
    async with client_from(signin_app, GUESSER) as guesser:
        outcomes = []
        for number in range(ATTEMPT_LIMIT_PER_ADDRESS * 3):
            forged = f"192.0.2.{number + 1}"
            value = f"for={forged}" if header == "Forwarded" else forged
            response = await log_in(guesser, f"guess{number}@example.com", "x", **{header: value})
            outcomes.append(response.status_code)

    assert outcomes.count(401) == ATTEMPT_LIMIT_PER_ADDRESS
    assert outcomes[ATTEMPT_LIMIT_PER_ADDRESS:] == [429] * (ATTEMPT_LIMIT_PER_ADDRESS * 2)


async def test_behind_the_installation_nginx_the_client_is_its_x_real_ip(
    behind_nginx: FastAPI,
) -> None:
    """За своим nginx клиент — его `X-Real-IP`: перебор одного не держит другого."""
    async with client_from(behind_nginx, NGINX) as via_nginx:
        for number in range(ATTEMPT_LIMIT_PER_ADDRESS):
            guessed = await log_in(
                via_nginx, f"guess{number}@example.com", "x", **{"X-Real-IP": GUESSER}
            )
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
                    f"guess{n}@example.com",
                    "x",
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
                await log_in(
                    direct, f"guess{n}@example.com", "x", **{"X-Real-IP": f"192.0.2.{n + 1}"}
                )
            ).status_code
            for n in range(ATTEMPT_LIMIT_PER_ADDRESS * 3)
        ]

    assert outcomes.count(401) == ATTEMPT_LIMIT_PER_ADDRESS
    assert outcomes[ATTEMPT_LIMIT_PER_ADDRESS:] == [429] * (ATTEMPT_LIMIT_PER_ADDRESS * 2)


async def test_a_trusted_peer_without_a_usable_x_real_ip_is_the_client_itself(
    behind_nginx: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    """Свой nginx заголовок ставит всегда; нет его или в нём мусор — клиент сам собеседник."""
    caplog.set_level(logging.WARNING)
    async with client_from(behind_nginx, NGINX) as via_nginx:
        for number, value in enumerate(["not an address", "", "203.0.113.7:4431"]):
            await log_in(via_nginx, f"guess{number}@example.com", "x", **{"X-Real-IP": value})
        await log_in(via_nginx, "guess3@example.com", "x")
        await log_in(via_nginx, "guess4@example.com", "x")
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


@pytest.fixture
def cheap_unknown_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустышка неизвестной почты — дешёвым хешем: сотни попыток по полной цене scrypt
    проверяли бы терпение, а не логику окон."""
    monkeypatch.setattr(login_module, "_unknown_account_hash", lambda: PasswordHash.parse(HASH))


@pytest.mark.usefixtures("cheap_unknown_account")
async def test_the_counters_never_hold_more_keys_than_the_ceiling(
    db_session: AsyncSession, alice: Account
) -> None:
    """Адрес и почта помнятся, пока у них неудача в окне или идущая попытка, — не больше потолка.

    Сотни адресов и почт, по одной неудаче каждый, со сдвигом часов: словари окон не
    растут выше потолка, отказанные ключи в них не заводятся, а после окна они пустеют.
    """
    clock = Clock()
    login = PasswordLogin(session_ttl=timedelta(hours=1), clock=clock)
    largest = 0
    for number in range(ATTEMPT_LIMIT_TOTAL * 3):
        address = ipaddress.ip_address(f"10.0.{number // 250}.{number % 250 + 1}")
        with pytest.raises(
            (login_module.UnauthorizedError, login_module.PasswordAttemptsExceededError)
        ):
            await login.open(
                db_session, email=f"guess{number}@example.com", password="x", client=address
            )
        largest = max(largest, len(login._keys["address"]), len(login._keys["account"]))
        clock.advance(timedelta(milliseconds=200))

    assert largest <= ATTEMPT_LIMIT_TOTAL

    clock.advance(ATTEMPT_WINDOW)
    await login.open(db_session, email=ALICE, password=PASSWORD, client=ipaddress.ip_address(OWNER))
    assert login._keys == {"address": {}, "account": {}}


async def test_an_unknown_email_is_checked_at_the_price_of_a_real_one(
    signin: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Незаведённая почта проверяется против пустышки, а не отвечает сразу: по времени
    ответа нельзя прочитать, какие адреса заведены."""
    checked: list[PasswordHash] = []

    def recording_verify(password: str, stored: PasswordHash) -> bool:
        checked.append(stored)
        return verify_password(password, stored)

    monkeypatch.setattr(login_module, "verify_password", recording_verify)
    monkeypatch.setattr(login_module, "_unknown_account_hash", lambda: PasswordHash.parse(HASH))

    response = await log_in(signin, "nobody@example.com")

    assert response.status_code == 401
    assert len(checked) == 1


async def test_attempts_in_flight_count_against_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Одновременные попытки занимают окно до исхода: сотня разом не проскочит проверку.

    Проверка пароля держится на событии, пока тест не отпустит: все попытки окна адреса
    идут одновременно, и следующая с того же адреса получает отказ, не дожидаясь их
    неудач, — а попытка с другого адреса на другую почту доходит до проверки.

    Учётные записи здесь — заглушка репозитория: одновременные попытки на одной сессии
    базы теста шли бы по одному соединению, а проверяется окно, а не выборка.
    """
    release = threading.Event()
    checked: list[str] = []

    def slow_verify(password: str, stored: PasswordHash) -> bool:
        checked.append(password)
        release.wait(timeout=10)
        return False

    class Accounts:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_email(self, _email: str) -> SimpleNamespace:
            return SimpleNamespace(password_hash=HASH, is_disabled=False)

    monkeypatch.setattr(login_module, "verify_password", slow_verify)
    monkeypatch.setattr(login_module, "AccountRepository", Accounts)
    login = PasswordLogin(session_ttl=timedelta(hours=1))
    session: Any = None
    guesser = ipaddress.ip_address(GUESSER)

    pending = [
        asyncio.create_task(
            login.open(session, email=f"guess{n}@example.com", password="x", client=guesser)
        )
        for n in range(ATTEMPT_LIMIT_PER_ADDRESS)
    ]
    await asyncio.sleep(0)
    try:
        with pytest.raises(login_module.PasswordAttemptsExceededError) as refused:
            await login.open(session, email=ALICE, password=PASSWORD, client=guesser)
        colleague = asyncio.create_task(
            login.open(session, email=BOB, password=PASSWORD, client=ipaddress.ip_address(OWNER))
        )
        await asyncio.sleep(0)
    finally:
        release.set()
        results = await asyncio.gather(*pending, colleague, return_exceptions=True)

    assert refused.value.details["scope"] == "address"
    assert checked.count(PASSWORD) == 1
    assert all(isinstance(result, login_module.UnauthorizedError) for result in results)


# --- Настройки и журнал -----------------------------------------------------------------


def test_an_empty_legacy_hash_from_compose_means_nothing_to_carry_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose передаёт переменную всегда; пустая — «переносить нечего», а не испорченный хеш.

    И API её больше не читает: с любым значением приложение собирается одинаково.
    """
    monkeypatch.setenv("TRACKER_PASSWORD_HASH", "")

    assert Settings().password_hash is None
    assert create_app(Settings(password_hash="$scrypt$garbage")).state.password_login
    assert HASH not in repr(Settings(password_hash=HASH))


async def test_the_password_never_reaches_the_log(
    signin: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Ни верный, ни неверный пароль не попадают в журнал процесса."""
    caplog.set_level(logging.DEBUG)

    await log_in(signin, ALICE, "wrong password but long")
    await log_in(signin)

    assert "wrong password but long" not in caplog.text
    assert PASSWORD not in caplog.text
