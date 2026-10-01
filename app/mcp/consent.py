"""Страница входа OAuth в сетевом режиме: почта и пароль, выбор участника, согласие.

В сети (`TRACKER_LOGIN=password`) `/authorize` не выдаёт код сразу: провайдер
(`app/mcp/oauth.py`) отправляет браузер сюда, на `/oauth/consent` той же службы mcp, с
параметрами запроса. Человек входит своей почтой и паролем, выбирает участника и
разрешает вход; код уходит на адрес возврата клиента. Кому выдать — политика
`SignedInConsent` (`app/services/oauth.py`), выпускающий — вошедший человек (TRK-450,
решение `TRK-475#14`).

## Каждый шаг проверяет запрос заново

Страницу можно открыть и отправить мимо `/authorize`, поэтому любой её запрос проходит те
же проверки, что SDK делает на `/authorize`: схема запроса (`AuthorizationRequest`: `code`,
PKCE `S256`), клиент зарегистрирован, адрес возврата — его, область допустима. Не прошёл —
страница ошибки без перенаправления: на незарегистрированный адрес код и ошибка не уходят
никогда.

## Вход привязан к браузеру, отправка формы — к странице

- Вход — настоящий сеанс браузера человека (`PasswordLogin`, как в интерфейсе: окна
  попыток, `account_disabled`). Его секрет живёт в куке `HttpOnly` с путём `/oauth`:
  повторный вход агента в том же браузере не спрашивает пароль, а выход, смена пароля и
  отключение учётной записи гасят сеанс, как любой другой.
- Каждая отправка формы несёт токен CSRF из скрытого поля, равный куке `SameSite=Strict`
  (двойная отправка): чужая страница не знает значения и не может отправить форму от
  имени вошедшего человека. Заголовок `Origin`, если он есть, обязан быть адресом службы.
- Страница отвечает только на своём адресе (`Host` — узел публичного адреса службы mcp):
  страница, открытая под чужим именем узла (DNS rebinding), не получит ни куки, ни кода.
- Ответы не кэшируются и не встраиваются в чужие страницы (`frame-ancestors 'none'`).

## Язык страницы

Английский, как ответы API и сообщения об ошибках (`docs/CONVENTIONS.md`): страницу
отдаёт служба mcp, словари интерфейса ей недоступны. Тексты собраны в `_TEXTS`.
"""

import html
import ipaddress
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from mcp.server.auth.handlers.authorize import AuthorizationRequest
from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import InvalidRedirectUriError, InvalidScopeError, OAuthClientInformationFull
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.core.errors import AppError, UnauthorizedError
from app.core.logging import get_logger
from app.db.models.participant import Participant
from app.domain.errors import PasswordAttemptsExceededError
from app.domain.oauth import OAuthRefusal
from app.mcp.oauth import CasefileAuthorization
from app.mcp.runtime import SessionFactory
from app.services import oauth as oauth_service
from app.services.login import LiveSession, PasswordLogin

__all__ = ["CONSENT_PATH", "ConsentPage", "consent_page_url"]

logger = get_logger("oauth")

#: Путь страницы на узле службы mcp. За прокси он проксируется вместе с `/authorize`.
CONSENT_PATH = "/oauth/consent"
#: Куки страницы живут только под `/oauth`: ни `/mcp`, ни интерфейс на том же узле их не видят.
_COOKIE_PATH = "/oauth"
SESSION_COOKIE = "casefile_oauth_session"
CSRF_COOKIE = "casefile_oauth_csrf"
#: Параметры запроса `/authorize`, которые страница несёт от шага к шагу.
_REQUEST_FIELDS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
)


def consent_page_url(issuer_url: str) -> str:
    """Полный адрес страницы на узле сервера авторизации: туда `/authorize` шлёт браузер."""
    issuer = urlsplit(issuer_url)
    return f"{issuer.scheme}://{issuer.netloc}{CONSENT_PATH}"


@dataclass(frozen=True, slots=True)
class _Checked:
    """Запрос, прошедший проверки `/authorize`: клиент, адрес возврата, области."""

    request: AuthorizationRequest
    client: OAuthClientInformationFull
    redirect_uri: str
    scopes: list[str] | None

    @property
    def client_name(self) -> str:
        return (self.client.client_name or "").strip() or (self.client.client_id or "")

    def view(self) -> oauth_service.ClientView:
        return oauth_service.ClientView(
            client_id=self.client.client_id or "",
            client_name=self.client.client_name,
            metadata=self.client.model_dump(mode="json"),
        )

    def params(self) -> dict[str, str]:
        """Параметры запроса для ссылки и скрытых полей: как пришли, без пустых."""
        dumped = self.request.model_dump(mode="json")
        return {key: str(dumped[key]) for key in _REQUEST_FIELDS if dumped.get(key) is not None}


class _Invalid(Exception):
    """Запрос страницы негоден: ответ — страница ошибки, без перенаправления."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class ConsentPage:
    """Маршрут `/oauth/consent` службы mcp: вход, выбор участника, согласие или отказ."""

    def __init__(
        self,
        sessions: SessionFactory,
        *,
        clients: CasefileAuthorization,
        login: PasswordLogin,
        issuer_url: str,
    ) -> None:
        """`clients` — провайдер сервера авторизации: его `get_client` находит клиента."""
        self._sessions = sessions
        self._clients = clients
        self._login = login
        issuer = urlsplit(issuer_url)
        self._origin = f"{issuer.scheme}://{issuer.netloc}"
        self._issuer = issuer_url  # `iss` ответа (RFC 9207): тот же issuer, что в метаданных
        self._host = issuer.netloc.lower()
        self._secure = issuer.scheme == "https"

    def register(self, server: MCPServer) -> None:
        server.custom_route(CONSENT_PATH, methods=["GET", "POST"], include_in_schema=False)(
            self.handle
        )

    async def handle(self, request: Request) -> Response:
        try:
            self._check_host(request)
            if request.method == "POST":
                return await self._post(request)
            return await self._get(request)
        except _Invalid as invalid:
            return self._page(
                _text("invalid_title"),
                f"<p>{html.escape(invalid.reason)}</p>",
                status=invalid.status,
                csrf=None,
            )

    # --- Шаги -------------------------------------------------------------------------

    async def _get(self, request: Request) -> Response:
        checked = await self._check(request.query_params)
        csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        async with self._sessions() as session:
            live = await self._live(session, request)
            if live is None:
                return self._login_form(checked, csrf, error=None, status=200)
            choices = await oauth_service.consent_choices(
                session, person=live.account.participant, client=checked.view()
            )
            return self._choice_form(checked, csrf, live.account.participant, choices)

    async def _post(self, request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") != self._origin:
            raise _Invalid(403, _text("foreign_origin"))
        form = await request.form()
        fields = {key: str(value) for key, value in form.items() if isinstance(value, str)}
        csrf = request.cookies.get(CSRF_COOKIE)
        if not csrf or not secrets.compare_digest(csrf, fields.get("csrf", "")):
            raise _Invalid(403, _text("stale_form"))
        checked = await self._check(fields)
        action = fields.get("action")
        if action == "login":
            return await self._sign_in(request, checked, csrf, fields)
        if action == "logout":
            return await self._sign_out(request, checked)
        if action == "deny":
            return self._back(checked, error="access_denied")
        if action == "allow":
            return await self._allow(request, checked, csrf, fields.get("participant"))
        raise _Invalid(400, _text("unknown_action"))

    async def _sign_in(
        self,
        request: Request,
        checked: _Checked,
        csrf: str,
        fields: Mapping[str, str],
    ) -> Response:
        try:
            async with self._sessions() as session:
                live = await self._login.open(
                    session,
                    email=fields.get("email", ""),
                    password=fields.get("password", ""),
                    client=_client_address(request),
                )
        except PasswordAttemptsExceededError as exceeded:
            retry = int(exceeded.details.get("retry_after", 60))
            error = _text("too_many").format(seconds=retry)
            response = self._login_form(
                checked, csrf, error=error, status=429, email=fields.get("email", "")
            )
            response.headers["retry-after"] = str(retry)
            return response
        except UnauthorizedError as refused:
            reason = str(refused.details.get("reason", ""))
            key = "account_disabled" if reason == "account_disabled" else "wrong_credentials"
            return self._login_form(
                checked, csrf, error=_text(key), status=401, email=fields.get("email", "")
            )
        response = RedirectResponse(f"{CONSENT_PATH}?{urlencode(checked.params())}", 303)
        response.set_cookie(
            SESSION_COOKIE,
            live.secret,
            max_age=int(self._login.session_ttl.total_seconds()),
            path=_COOKIE_PATH,
            secure=self._secure,
            httponly=True,
            samesite="lax",
        )
        return self._guarded(response)

    async def _sign_out(self, request: Request, checked: _Checked) -> Response:
        async with self._sessions() as session:
            await self._login.close(session, request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse(f"{CONSENT_PATH}?{urlencode(checked.params())}", 303)
        response.delete_cookie(SESSION_COOKIE, path=_COOKIE_PATH)
        return self._guarded(response)

    async def _allow(
        self,
        request: Request,
        checked: _Checked,
        csrf: str,
        choice: str | None,
    ) -> Response:
        try:
            async with self._sessions() as session:
                live = await self._live(session, request)
                if live is None:
                    error = _text("signed_out")
                    return self._login_form(checked, csrf, error=error, status=401)
                person = live.account.participant
                code = await oauth_service.authorize(
                    session,
                    client_id=checked.client.client_id or "",
                    redirect_uri=checked.redirect_uri,
                    redirect_uri_provided_explicitly=checked.request.redirect_uri is not None,
                    code_challenge=checked.request.code_challenge,
                    scopes=checked.scopes,
                    resource=checked.request.resource,
                    policy=oauth_service.SignedInConsent(person=person, choice=choice or None),
                )
        except OAuthRefusal as refusal:
            logger.info("OAuth consent refused: %s", refusal.description)
            return self._back(checked, error="access_denied", description=refusal.description)
        logger.info("OAuth consent given by %s to %s", person.name, checked.client_name)
        return self._back(checked, code=code)

    # --- Проверки ---------------------------------------------------------------------

    def _check_host(self, request: Request) -> None:
        host = (request.headers.get("host") or "").lower()
        if host != self._host:
            logger.warning("OAuth consent page asked on a foreign host: %s", host)
            raise _Invalid(400, "This page answers only on its own address")

    async def _check(self, params: Mapping[str, str]) -> _Checked:
        """Проверки `/authorize` заново: схема, клиент, адрес возврата, области."""
        try:
            request = AuthorizationRequest.model_validate(
                {key: params[key] for key in _REQUEST_FIELDS if params.get(key)}
            )
        except ValidationError as error:
            raise _Invalid(
                400, f"Invalid sign-in request: {error.error_count()} bad fields"
            ) from None
        client = await self._clients.get_client(request.client_id)
        if client is None:
            raise _Invalid(400, "The client is not registered")
        try:
            redirect = client.validate_redirect_uri(request.redirect_uri)
            scopes = client.validate_scope(request.scope)
        except (InvalidRedirectUriError, InvalidScopeError) as error:
            raise _Invalid(400, error.message) from None
        return _Checked(request=request, client=client, redirect_uri=str(redirect), scopes=scopes)

    async def _live(self, session: AsyncSession, request: Request) -> LiveSession | None:
        """Живой сеанс человека из куки страницы или `None` — войти заново."""
        secret = request.cookies.get(SESSION_COOKIE)
        if not secret:
            return None
        try:
            return await self._login.check(session, secret)
        except AppError:
            return None

    # --- Ответы -----------------------------------------------------------------------

    def _back(
        self,
        checked: _Checked,
        *,
        code: str | None = None,
        error: str | None = None,
        description: str | None = None,
    ) -> Response:
        """Возврат браузера клиенту: код или ошибка, всегда с `state` запроса и `iss` (RFC 9207)."""
        location = construct_redirect_uri(
            checked.redirect_uri,
            code=code,
            error=error,
            error_description=description,
            state=checked.request.state,
            iss=self._issuer,
        )
        return self._guarded(RedirectResponse(location, 303))

    def _login_form(
        self,
        checked: _Checked,
        csrf: str,
        *,
        error: str | None,
        status: int,
        email: str = "",
    ) -> Response:
        alert = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
        body = f"""
<p>{_text("login_lead").format(client=_strong(checked.client_name))}</p>
{_returns(checked)}
{alert}
<form method="post" action="{CONSENT_PATH}">
  {_hidden(checked, csrf)}
  <label>{_text("email")}
    <input name="email" type="email" value="{html.escape(email)}"
      autocomplete="username" required autofocus></label>
  <label>{_text("password")}
    <input name="password" type="password" autocomplete="current-password" required></label>
  <button name="action" value="login" class="primary">{_text("sign_in")}</button>
</form>"""
        return self._page(_text("login_title"), body, status=status, csrf=csrf)

    def _choice_form(
        self,
        checked: _Checked,
        csrf: str,
        person: Participant,
        choices: oauth_service.ConsentChoices,
    ) -> Response:
        options = [_option(agent, agent.id == choices.default.id) for agent in choices.options]
        name = person.name
        body = f"""
<p>{_text("choice_lead").format(client=_strong(checked.client_name))}</p>
{_returns(checked)}
<form method="post" action="{CONSENT_PATH}">
  {_hidden(checked, csrf)}
  <fieldset><legend>{_text("act_as")}</legend>{"".join(options)}</fieldset>
  <p class="note">{_text("revoke_note")}</p>
  <div class="actions">
    <button name="action" value="allow" class="primary">{_text("allow")}</button>
    <button name="action" value="deny">{_text("deny")}</button>
  </div>
  <p class="who">{_text("signed_in_as").format(name=_strong(name))}
    <button name="action" value="logout" class="link" formnovalidate>{_text("not_you")}</button></p>
</form>"""
        return self._page(_text("choice_title"), body, status=200, csrf=csrf)

    def _page(self, title: str, body: str, *, status: int, csrf: str | None) -> Response:
        response = HTMLResponse(_document(title, body), status_code=status)
        if csrf is not None:
            response.set_cookie(
                CSRF_COOKIE,
                csrf,
                path=_COOKIE_PATH,
                secure=self._secure,
                httponly=True,
                samesite="strict",
            )
        return self._guarded(response)

    @staticmethod
    def _guarded(response: Response) -> Response:
        response.headers["cache-control"] = "no-store"
        response.headers["x-frame-options"] = "DENY"
        # `same-origin`, не `no-referrer`: при `no-referrer` браузер шлёт с формой
        # `Origin: null`, и своя же форма не прошла бы проверку источника.
        response.headers["referrer-policy"] = "same-origin"
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["content-security-policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response


# --- Разметка -------------------------------------------------------------------------


def _strong(text: str) -> str:
    return f"<strong>{html.escape(text)}</strong>"


def _hidden(checked: _Checked, csrf: str) -> str:
    fields = {**checked.params(), "csrf": csrf}
    return "".join(
        f'<input type="hidden" name="{name}" value="{html.escape(value)}">'
        for name, value in fields.items()
    )


def _returns(checked: _Checked) -> str:
    """Куда вернётся браузер: узел адреса возврата, чтобы человек видел, кому уходит вход."""
    host = urlsplit(checked.redirect_uri).hostname or checked.redirect_uri
    return f'<p class="note">{_text("returns_to").format(host=_strong(host))}</p>'


def _option(agent: Participant, checked: bool) -> str:
    mark = " checked" if checked else ""
    name = html.escape(agent.name)
    description = html.escape(agent.description or "")
    hint = f'<span class="hint">{description}</span>' if description else ""
    return (
        f'<label class="option"><input type="radio" name="participant" value="{name}"{mark}>'
        f'<span><span class="name">{name}</span>{hint}</span></label>'
    )


def _client_address(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if request.client is None:
        return None
    try:
        return ipaddress.ip_address(request.client.host)
    except ValueError:
        return None


_TEXTS: dict[str, str] = {
    "login_title": "Sign in to Casefile",
    "login_lead": "{client} wants to connect to this Casefile as an agent. Sign in to allow it.",
    "choice_title": "Connect an agent",
    "choice_lead": "{client} wants to connect to this Casefile.",
    "returns_to": "Sign-in returns to {host}.",
    "email": "Email",
    "password": "Password",
    "sign_in": "Sign in",
    "act_as": "The agent will act as",
    "revoke_note": "You can disconnect it at any time in Access.",
    "allow": "Allow",
    "deny": "Deny",
    "signed_in_as": "Signed in as {name}.",
    "not_you": "Not you?",
    "wrong_credentials": "Email or password does not match.",
    "account_disabled": "The account is disabled.",
    "too_many": "Too many attempts. Try again in {seconds} s.",
    "signed_out": "The sign-in has ended. Sign in again.",
    "invalid_title": "This sign-in link is not valid",
    "stale_form": "The form is out of date. Start the sign-in from your agent again.",
    "foreign_origin": "The form was sent from another site.",
    "unknown_action": "Unknown action.",
}


def _text(key: str) -> str:
    return _TEXTS[key]


_STYLE = """
:root{--bg:#f6f5f2;--card:#fff;--text:#1d1c1a;--muted:#6b6862;--line:#dcd9d2;
--accent:#1f5f8b;--accent-text:#fff;--error:#a3261b;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--text:#ecebe7;
--muted:#a19e97;--line:#3a3935;--accent:#6aa9d8;--accent-text:#0e1a24;--error:#f08a7e}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;
align-items:flex-start;justify-content:center;padding:48px 16px}
main{width:100%;max-width:420px;background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:28px 24px}
.brand{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
margin:0 0 8px}
h1{font-size:22px;line-height:1.25;margin:0 0 16px}
p{margin:0 0 14px;overflow-wrap:anywhere}
.note,.who,.hint{color:var(--muted);font-size:14px}
.error{color:var(--error)}
label{display:block;margin:0 0 14px;font-size:14px}
input[type=email],input[type=password]{display:block;width:100%;margin-top:6px;padding:10px 12px;
font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:8px}
fieldset{border:0;padding:0;margin:0 0 12px}
legend{font-size:14px;color:var(--muted);margin-bottom:8px;padding:0}
.option{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;margin:0 0 8px;
border:1px solid var(--line);border-radius:8px;cursor:pointer}
.option input{margin-top:5px}
.name{display:block;font-weight:600;overflow-wrap:anywhere}
.hint{display:block}
.actions{display:flex;gap:10px;margin:18px 0}
button{font:inherit;padding:10px 18px;border-radius:8px;border:1px solid var(--line);
background:transparent;color:var(--text);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text)}
form>button.primary{width:100%}
button.link{border:0;padding:0;color:var(--accent);text-decoration:underline;font-size:14px}
"""


def _document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)} · Casefile</title>
<style>{_STYLE}</style>
</head>
<body><main>
<p class="brand">Casefile</p>
<h1>{html.escape(title)}</h1>
{body}
</main></body>
</html>
"""
