"""Вход владельца по паролю: сеанс браузера в куке.

Замок на одну дверь (`docs/CONCEPT.md`, 5.4). Эти маршруты — единственные под `/api/v1`,
которые не требуют токена (`app/api/contract.py`, `TOKEN_EXEMPT`): пароль и есть то, чем
браузер получает ключ установки. Кто пришёл, спрашивает не этот код, а nginx интерфейса:
он отдаёт `/config.json` только после `auth_request` на `GET /api/v1/session`
(`ui/docker/nginx.conf.template`).

Роутер переводит HTTP в вызов сценария и обратно; сеансы и окно попыток живут в
`app/services/login.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.schemas.common import DataResponse
from app.api.schemas.session import PasswordLogin as PasswordLoginBody
from app.api.schemas.session import SessionRead
from app.services.login import OpenedSession, PasswordLogin

router = APIRouter(prefix="/session", tags=["session"])

#: Имя куки сеанса. Без префикса `__Host-`: он требует `Secure`, а установку в доверенной
#: сети открывают и по голому HTTP.
SESSION_COOKIE = "casefile_session"

SessionCookie = Annotated[
    str | None,
    Cookie(
        alias=SESSION_COOKIE,
        description="Browser session opened by `POST /api/v1/session`; set and read as `HttpOnly`",
    ),
]


def get_password_login(request: Request) -> PasswordLogin:
    """Вход того приложения, которое обслуживает запрос (`create_app` кладёт его в состояние).

    Зависимостью, а не модулем: у каждого собранного приложения свои сеансы и своё окно
    попыток — тест, собравший приложение со своим паролем, не делит их с соседним.
    """
    login: PasswordLogin = request.app.state.password_login
    return login


PasswordLoginDep = Annotated[PasswordLogin, Depends(get_password_login)]


@router.post("", summary="Log in with the owner password")
async def open_session(
    payload: PasswordLoginBody,
    request: Request,
    response: Response,
    login: PasswordLoginDep,
) -> DataResponse[SessionRead]:
    """Проверяет пароль владельца и ставит куку сеанса; с ней `/config.json` отдаёт ключ.

    Кука `casefile_session` — `HttpOnly`, `SameSite=Strict`, `Path=/`, со сроком сеанса, и
    `Secure`, если запрос пришёл по HTTPS (прокси сообщает это `X-Forwarded-Proto`).

    Неверный пароль — `401 unauthorized` с `details.reason: wrong_password`. Неудачных
    попыток за окно столько, сколько разрешено, — `429 password_attempts_exceeded` с
    `Retry-After`, и пароль тогда не проверяется вовсе. Пароля у установки нет — `409
    password_login_off`.

    Отвечает `200`, а не `201`: сеанс не адресуемый ресурс, и повторить вход ключом
    идемпотентности нельзя — такие ключи живут в паре с токеном, а его здесь нет.
    """
    opened = await login.open(payload.password)
    _set_cookie(response, opened, secure=_arrived_over_https(request))
    return DataResponse[SessionRead](data=SessionRead(expires_at=opened.expires_at))


@router.get("", summary="Check the browser session")
async def read_session(
    login: PasswordLoginDep, secret: SessionCookie = None
) -> DataResponse[SessionRead]:
    """Жив ли сеанс из куки: `200` со сроком или `401 unauthorized`.

    Причина отказа — в `details.reason`: `missing_session`, `unknown_session` (в том
    числе после выхода и перезапуска API), `session_expired`. Этим маршрутом nginx
    интерфейса решает, отдать ли `/config.json`.
    """
    expires_at = login.check(secret)
    return DataResponse[SessionRead](data=SessionRead(expires_at=expires_at))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
async def close_session(
    request: Request,
    login: PasswordLoginDep,
    secret: SessionCookie = None,
) -> Response:
    """Гасит сеанс на сервере и стирает куку. Идемпотентен: без сеанса отвечает так же.

    Ключ, уже отданный вкладке, выход не отзывает — он отнимает возможность получить
    ключ заново (`docs/CONCEPT.md`, 5.4).
    """
    login.close(secret)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=_arrived_over_https(request),
        httponly=True,
        samesite="strict",
    )
    return response


def _set_cookie(response: Response, opened: OpenedSession, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        opened.secret,
        # Срок и в куке: браузер сам забудет истёкшую, а не будет слать её до выхода.
        expires=opened.expires_at,
        path="/",
        secure=secure,
        httponly=True,
        # `Strict`: куку шлют только запросы со своего сайта, и страница чужого не
        # выйдет ею из сеанса. Открыть доску по ссылке извне это не мешает: страницу
        # nginx отдаёт и без куки, а `/config.json` приложение спрашивает уже само, со
        # своего источника, — и кука едет с этим запросом.
        samesite="strict",
    )


def _arrived_over_https(request: Request) -> bool:
    """Пришёл ли запрос по HTTPS — сам или через прокси, снявший TLS.

    Заголовку прокси здесь можно верить: подделав его, клиент добьётся лишь того, что
    его собственная кука станет строже. Первое значение списка — то, что видел первый
    прокси, то есть браузер.
    """
    forwarded = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded.split(",")[0].strip().lower() or request.url.scheme
    return scheme == "https"
