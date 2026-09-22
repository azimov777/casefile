"""Вход по почте и паролю: сеанс браузера — токен в куке.

`docs/CONCEPT.md`, 5.4. Эти маршруты — единственные под `/api/v1`, которые не требуют
токена в заголовке (`app/api/contract.py`, `TOKEN_EXEMPT`): вход и есть то, чем браузер
получает свой токен. Кука `casefile_session` несёт секрет токена сеанса, а ответ входа и
чтения сеанса отдаёт его вкладке в `data.token` — дальше она ходит в REST обычным
заголовком `Authorization`, как любой клиент.

Роутер переводит HTTP в вызов сценария и обратно; вход и окна попыток живут в
`app/services/login.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.client_address import ClientAddressesDep
from app.api.deps import SessionDep
from app.api.schemas.accounts import AccountRead
from app.api.schemas.common import DataResponse
from app.api.schemas.session import SessionLogin, SessionRead
from app.services.login import LiveSession, PasswordLogin

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

    Зависимостью, а не модулем: у каждого собранного приложения своё окно попыток — тест,
    собравший приложение со своими часами, не делит его с соседним.
    """
    login: PasswordLogin = request.app.state.password_login
    return login


PasswordLoginDep = Annotated[PasswordLogin, Depends(get_password_login)]


@router.post("", summary="Sign in with email and password")
async def open_session(
    payload: SessionLogin,
    request: Request,
    response: Response,
    session: SessionDep,
    login: PasswordLoginDep,
    addresses: ClientAddressesDep,
) -> DataResponse[SessionRead]:
    """Проверяет почту и пароль, выпускает токен сеанса и ставит его секрет в куку.

    Токен — набора `main`, участника этой учётной записи, со сроком сеанса; им вкладка
    ходит в REST, и записи подписаны именем этого человека. Кука `casefile_session` —
    `HttpOnly`, `SameSite=Strict`, `Path=/`, со сроком сеанса, и `Secure`, если запрос
    пришёл по HTTPS (прокси сообщает это `X-Forwarded-Proto`).

    Неверная почта или пароль — `401 unauthorized` с `details.reason: wrong_credentials`,
    одинаково для незаведённой почты; отключённая учётная запись — `account_disabled`,
    только после верного пароля. Неудачных попыток за окно с этого адреса, на эту почту
    или со всей установки столько, сколько разрешено, — `429 password_attempts_exceeded`
    с `Retry-After` и `details.scope`, и пароль тогда не проверяется вовсе. Адрес клиента —
    собеседник TCP, а за nginx установки — его `X-Real-IP`; прочим заголовкам с адресом
    API не верит.

    Отвечает `200`, а не `201`: сеанс не адресуемый ресурс, и повторить вход ключом
    идемпотентности нельзя — такие ключи живут в паре с токеном, а его здесь нет.
    """
    live = await login.open(
        session,
        email=payload.email,
        password=payload.password,
        client=await addresses.of(request),
    )
    _set_cookie(response, live, secure=_arrived_over_https(request))
    return DataResponse[SessionRead](data=_read(live))


@router.get("", summary="Read the browser session")
async def read_session(
    session: SessionDep, login: PasswordLoginDep, secret: SessionCookie = None
) -> DataResponse[SessionRead]:
    """Живой сеанс из куки — с токеном вкладки — или `401 unauthorized`.

    Так вкладка после перезагрузки получает свой токен заново: секрет в куке `HttpOnly`,
    скрипту страницы он не виден. Причина отказа — в `details.reason`: `missing_session`,
    `unknown_session` (в том числе после выхода, смены пароля и отключения учётной
    записи), `session_expired`.
    """
    live = await login.check(session, secret)
    return DataResponse[SessionRead](data=_read(live))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def close_session(
    request: Request,
    session: SessionDep,
    login: PasswordLoginDep,
    secret: SessionCookie = None,
) -> Response:
    """Отзывает токен сеанса и стирает куку. Идемпотентен: без сеанса отвечает так же.

    Отзывается сам токен: вкладка, державшая его, теряет доступ на следующем же запросе,
    а не на перезагрузке (`docs/CONCEPT.md`, 5.4).
    """
    await login.close(session, secret)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=_arrived_over_https(request),
        httponly=True,
        samesite="strict",
    )
    return response


def _read(live: LiveSession) -> SessionRead:
    return SessionRead(
        token=live.secret,
        expires_at=live.expires_at,
        account=AccountRead.model_validate(live.account),
    )


def _set_cookie(response: Response, live: LiveSession, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        live.secret,
        # Срок и в куке: браузер сам забудет истёкшую, а не будет слать её до выхода.
        expires=live.expires_at,
        path="/",
        secure=secure,
        httponly=True,
        # `Strict`: куку шлют только запросы со своего сайта, и страница чужого не
        # выйдет ею из сеанса. Открыть доску по ссылке извне это не мешает: страницу
        # nginx отдаёт и без куки, а `GET /api/v1/session` приложение спрашивает уже само,
        # со своего источника, — и кука едет с этим запросом.
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
