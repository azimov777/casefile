"""Служба mcp — защищённый ресурс OAuth 2.0 и сервер авторизации OAuth 2.1 при нём.

Клиент без токена получает `401` с `WWW-Authenticate: Bearer resource_metadata="…"`,
по метаданным protected resource (RFC 9728) находит сервер авторизации — эту же службу,
регистрируется (DCR, RFC 7591), проходит `/authorize` с PKCE S256 и получает в `/token`
подключение — токен участника `trk_…` вида `oauth` со сроком и `expires_in` — и
refresh-токен. Маршруты, разбор запросов, PKCE и точное сравнение `redirect_uri` — SDK;
здесь только перевод его вызовов в сценарии `app/services/oauth.py` и обратно. Решения —
`TRK-448#8`, `TRK-448#9`, `TRK-469#24`.

## Проверка токена — на транспорте, с причиной

SDK не даёт одновременно провайдера и проверяющего: с провайдером проверяет его
`load_access_token`. Он проверяет **любой** bearer — выпущенный через OAuth, «Доступами»
или командой установки — одной функцией `verify_token` (`app/services/auth.py`), и
недействительный получает `401` транспорта: только так клиент OAuth узнаёт, что пора
обновить токен или войти снова. Там, где провайдер не ставится, стоит тот же проверяющий.

Ответ `401` от SDK безлик («Authentication required»). Причина (`token_revoked`,
`unknown_token`, `token_expired`, `account_disabled`) нужна агенту: по ней он понимает,
перевыпускать ли токен. Проверяющий кладёт её в запрос, а `RefusalReasons` — внешний слой
приложения — дописывает её в `error_description` заголовка и в тело `details.reason`.

## Клиент по документу и порт на петле

SDK не знает CIMD и сверяет `redirect_uri` точным совпадением. Оба пробела закрыты
здесь, не трогая SDK: `get_client` отдаёт `LoopbackClient` — клиента, который сравнивает
адрес на петле без порта (`redirect_matches`, RFC 8252 §7.3), — и находит клиента по
документу через сценарий (`find_client`). Метаданные сервера авторизации SDK строит сам и
объявляет только `client_secret_*`; `advertise_client_documents` подменяет их маршрут
метаданными с `client_id_metadata_document_supported` и методом `none`: без него Codex
отказывается от CIMD (TRK-432#6), а все клиенты Casefile публичные (TRK-448#9).

## Сервер авторизации — только там, где SDK его допускает

SDK отказывается подниматься с issuer по `http` не на петле (RFC 8414). Установка в сети
по голому http до сих пор работала токеном в заголовке; упасть из-за OAuth она не должна.
Поэтому сервер авторизации ставится, только если адрес пригоден (`authorization_enabled`),
а иначе служба остаётся защищённым ресурсом без `/authorize`.
"""

import contextvars
import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from mcp.server.auth.handlers.metadata import MetadataHandler, ProtectedResourceMetadataHandler
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from pydantic import AnyHttpUrl, AnyUrl, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.domain.oauth import OAUTH_SCOPE, OAuthRefusal, redirect_matches, resource_matches
from app.mcp.runtime import SessionFactory
from app.services import oauth as oauth_service
from app.services.auth import verify_token
from app.services.client_documents import ClientDocuments

__all__ = [
    "SCOPE",
    "CasefileAuthorization",
    "DeclaredScope",
    "IssuerOnAuthorize",
    "LoopbackClient",
    "PresentedToken",
    "RefusalReasons",
    "ResourceOnToken",
    "ServiceOrigin",
    "advertise_client_documents",
    "allowed_hosts",
    "auth_settings",
    "authorization_enabled",
    "declare_scope",
]

logger = get_logger("oauth")

#: Единственная область токена служб Casefile: у агента один вид доступа, область прав не делит.
SCOPE = OAUTH_SCOPE

#: `client_id` в описании токена для SDK. Одно значение у любого токена: SDK привязывает
#: сессию streamable HTTP к тройке (клиент, issuer, субъект), и после обновления токена
#: сессия того же участника должна оставаться его сессией.
_TOKEN_CLIENT = "casefile"

#: Причина отказа текущего запроса. Держатель — изменяемый словарь, который ставит
#: `RefusalReasons` до вызова приложения: проверяющий пишет в него, а не присваивает
#: переменную, и запись видна внешнему слою, в какой бы копии контекста она ни была сделана.
_refusal: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "mcp_bearer_refusal", default=None
)

_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


class PresentedToken:
    """Проверяющий bearer-токенов службы: годен ли токен, решает `verify_token`."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with self._sessions() as session:
                row = await verify_token(session, token)
                subject = None if row.participant is None else row.participant.name
                expires = row.expires_at
        except UnauthorizedError as refusal:
            holder = _refusal.get()
            if holder is not None:
                holder["reason"] = str(refusal.details.get("reason", "unauthorized"))
                holder["message"] = refusal.message
            return None
        # Срок — тот же, что в базе: SDK сверяет его и сам, но отказ с причиной
        # (`token_expired`) даёт `verify_token` раньше него.
        return AccessToken(
            token=token,
            client_id=_TOKEN_CLIENT,
            scopes=[SCOPE],
            expires_at=None if expires is None else int(expires.timestamp()),
            subject=subject,
        )


class LoopbackClient(OAuthClientInformationFull):
    """Клиент SDK, который принимает адрес возврата на петле с любым портом.

    Остальное — как у SDK: без `redirect_uri` в запросе берётся единственный
    зарегистрированный, неподходящий адрес — `InvalidRedirectUriError`.
    """

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None:
            requested = str(redirect_uri)
            if any(redirect_matches(str(uri), requested) for uri in self.redirect_uris or []):
                return redirect_uri
            raise InvalidRedirectUriError(
                f"Redirect URI '{redirect_uri}' not registered for client"
            )
        return super().validate_redirect_uri(redirect_uri)


class _Code(AuthorizationCode):
    """Код для SDK плюс идентификатор строки: по нему сценарий гасит код."""

    row_id: uuid.UUID


class _Refresh(RefreshToken):
    """Refresh для SDK плюс идентификатор строки: по нему сценарий его гасит."""

    row_id: uuid.UUID


class CasefileAuthorization(PresentedToken):
    """Провайдер сервера авторизации SDK поверх сценариев `app/services/oauth.py`.

    Каждый метод — своя транзакция (`sessions`), как вызов инструмента: SDK зовёт их по
    одному на шаг протокола. Отказ сценария `OAuthRefusal` становится ошибкой протокола
    того шага, где он случился.
    """

    def __init__(
        self,
        sessions: SessionFactory,
        consent: oauth_service.ConsentPolicy | None,
        documents: ClientDocuments | None = None,
        *,
        access_ttl: timedelta,
        resource: str,
        consent_page: str | None = None,
    ) -> None:
        """`consent` — согласие сразу (локальный режим); `consent_page` — адрес страницы
        входа (сетевой режим, `app/mcp/consent.py`), куда `/authorize` отправляет браузер.
        Задаётся одно из двух. `resource` — адрес этой службы: с ним сверяется параметр
        `resource` запроса `/authorize` (RFC 8707)."""
        if (consent is None) == (consent_page is None):
            raise ValueError("Exactly one of consent and consent_page is required")
        super().__init__(sessions)
        self._consent = consent
        self._consent_page = consent_page
        self._documents = documents or ClientDocuments.from_settings()
        self._access_ttl = access_ttl
        self._resource = resource

    # --- Клиенты -------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        metadata = await oauth_service.find_client(
            self._sessions, client_id, documents=self._documents
        )
        if metadata is None:
            return None
        try:
            return LoopbackClient.model_validate(metadata)
        except ValidationError as error:
            # Документ CIMD прошёл правила Casefile, но не схему SDK (например, `logo_uri`
            # не адрес): такого клиента для SDK нет, а не сбой `/authorize`.
            logger.warning("OAuth client %s has metadata SDK rejects: %s", client_id, error)
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Сохраняет клиента публичным: ответ регистрации отдаёт `none` и без секрета.

        SDK возвращает клиенту этот же объект, поэтому метод и секрет правятся в нём.
        """
        try:
            async with self._sessions() as session:
                await oauth_service.register_client(
                    session,
                    client_id=client_info.client_id or "",
                    metadata=_present(client_info.model_dump(mode="json")),
                )
        except OAuthRefusal as refusal:
            raise RegistrationError(
                error="invalid_redirect_uri", error_description=refusal.description
            ) from refusal
        client_info.token_endpoint_auth_method = "none"
        client_info.client_secret = None
        client_info.client_secret_expires_at = None

    # --- Код -----------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource is not None and not resource_matches(self._resource, params.resource):
            raise AuthorizeError(error="invalid_target", error_description=_FOREIGN_RESOURCE)
        if self._consent_page is not None:
            return _consent_page_url(self._consent_page, client, params)
        assert self._consent is not None  # одно из двух, проверено в конструкторе
        try:
            async with self._sessions() as session:
                code = await oauth_service.authorize(
                    session,
                    client_id=client.client_id or "",
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    code_challenge=params.code_challenge,
                    scopes=params.scopes,
                    resource=params.resource,
                    policy=self._consent,
                )
        except OAuthRefusal as refusal:
            raise AuthorizeError(
                error="access_denied", error_description=refusal.description
            ) from refusal
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> _Code | None:
        async with self._sessions() as session:
            view = await oauth_service.find_code(
                session, client_id=client.client_id or "", code=authorization_code
            )
        if view is None:
            return None
        return _Code(
            code=authorization_code,
            row_id=view.id,
            scopes=view.scopes,
            expires_at=view.expires_at.timestamp(),
            client_id=view.client_id,
            code_challenge=view.code_challenge,
            redirect_uri=AnyUrl(view.redirect_uri),
            redirect_uri_provided_explicitly=view.redirect_uri_provided_explicitly,
            resource=view.resource,
            subject=view.participant_name,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: _Code
    ) -> OAuthToken:
        del client
        try:
            async with self._sessions() as session:
                pair = await oauth_service.redeem_code(
                    session, code_id=authorization_code.row_id, access_ttl=self._access_ttl
                )
        except OAuthRefusal as refusal:
            raise TokenError(
                error="invalid_grant", error_description=refusal.description
            ) from refusal
        return _token_response(pair)

    # --- Refresh -------------------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> _Refresh | None:
        async with self._sessions() as session:
            view = await oauth_service.find_refresh(
                session, client_id=client.client_id or "", refresh=refresh_token
            )
        if view is None:
            return None
        return _Refresh(
            token=refresh_token,
            row_id=view.id,
            client_id=view.client_id,
            scopes=view.scopes,
            resource=view.resource,
            subject=view.participant_name,
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: _Refresh, scopes: list[str]
    ) -> OAuthToken:
        del client
        try:
            async with self._sessions() as session:
                pair = await oauth_service.rotate_refresh(
                    session,
                    refresh_id=refresh_token.row_id,
                    access_ttl=self._access_ttl,
                    scopes=scopes,
                )
        except OAuthRefusal as refusal:
            raise TokenError(
                error="invalid_grant", error_description=refusal.description
            ) from refusal
        return _token_response(pair)

    # --- Доступ --------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await self.verify_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Точка отзыва RFC 7009 не объявлена: токен отзывают «Доступы» (`/tokens`)."""
        del token
        raise NotImplementedError("token revocation goes through the tokens registry")


def _consent_page_url(
    page: str, client: OAuthClientInformationFull, params: AuthorizationParams
) -> str:
    """Адрес страницы входа с запросом `/authorize`, уже проверенным SDK.

    Адрес возврата передаётся, только если клиент назвал его сам: иначе страница, как и
    SDK, возьмёт единственный зарегистрированный, и код сверится с тем же флагом.
    """
    query = {
        "response_type": "code",
        "client_id": client.client_id or "",
        "code_challenge": params.code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": str(params.redirect_uri)
        if params.redirect_uri_provided_explicitly
        else None,
        "state": params.state,
        "scope": " ".join(params.scopes) if params.scopes else None,
        "resource": params.resource,
    }
    return f"{page}?{urlencode({key: value for key, value in query.items() if value})}"


def _present(metadata: dict[str, Any]) -> dict[str, Any]:
    """Метаданные без пустых полей: в базе — то, что клиент прислал, а не умолчания схемы."""
    return {key: value for key, value in metadata.items() if value is not None}


def _token_response(pair: oauth_service.IssuedPair) -> OAuthToken:
    """Ответ `/token` с `expires_in`: без него Codex не обновляет токен заранее (`TRK-469#24`)."""
    return OAuthToken(
        access_token=pair.access_token,
        token_type="Bearer",
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
        scope=" ".join(pair.scopes),
    )


class RefusalReasons:
    """Внешний слой приложения: дописывает причину отказа в `401` транспорта.

    Ставит держателя причины до вызова приложения. Если ответ — `401` и проверяющий
    записал причину, заменяет `error_description` в `WWW-Authenticate` и тело на
    `{"error": "invalid_token", "error_description": …, "code": "unauthorized",
    "details": {"reason": …}}`. Остальные ответы проходят как есть.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        holder: dict[str, str] = {}
        marker = _refusal.set(holder)
        held: list[Message] = []

        async def forward(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 401 and holder:
                held.append(message)
                return
            if held and message["type"] == "http.response.body":
                if not message.get("more_body"):
                    await _send_refusal(send, held[0], holder)
                return
            await send(message)

        try:
            await self.app(scope, receive, forward)
        finally:
            _refusal.reset(marker)


async def _send_refusal(send: Send, start: Message, holder: dict[str, str]) -> None:
    reason = holder["reason"]
    message = holder.get("message", "Unauthorized")
    body = json.dumps(
        {
            "error": "invalid_token",
            "error_description": message,
            "code": "unauthorized",
            "details": {"reason": reason},
        }
    ).encode()
    headers = []
    for name, value in start.get("headers", []):
        if name.lower() == b"content-length":
            continue
        if name.lower() == b"www-authenticate":
            value = value.replace(
                b'error_description="Authentication required"',
                f'error_description="{message} ({reason})"'.encode(),
            )
        headers.append((name, value))
    headers.append((b"content-length", str(len(body)).encode()))
    await send({**start, "headers": headers})
    await send({"type": "http.response.body", "body": body})


_FOREIGN_RESOURCE = "resource names a server other than this one"


class ResourceOnToken:
    """Внешний слой: `/token` с чужим `resource` (RFC 8707) отвечает `invalid_target`.

    SDK принимает `resource` в запросе `/token`, но провайдеру его не отдаёт, и
    сверить его в провайдере нельзя. Слой читает форму запроса, сверяет каждое значение
    `resource` с адресом службы и пересылает тело приложению нетронутым. Запрос без
    `resource` проходит как прежде.
    """

    def __init__(self, app: ASGIApp, resource: str) -> None:
        self.app = app
        self._resource = resource

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != _TOKEN_PATH or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        chunks: list[Message] = []
        body = b""
        more = True
        while more:
            message = await receive()
            chunks.append(message)
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            more = message.get("more_body", False)
        wanted = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get(
            "resource", []
        )
        if any(not resource_matches(self._resource, value) for value in wanted):
            payload = json.dumps(
                {"error": "invalid_target", "error_description": _FOREIGN_RESOURCE}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                        (b"pragma", b"no-cache"),
                        (b"content-length", str(len(payload)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload})
            return
        replay = iter(chunks)

        async def replayed() -> Message:
            return next(replay, None) or await receive()

        await self.app(scope, replayed, send)


class IssuerOnAuthorize:
    """Внешний слой: добавляет `iss` (RFC 9207) в каждый редирект `/authorize` к клиенту.

    Редирект с кодом строит провайдер, с ошибкой — обработчик SDK (`access_denied`,
    `invalid_scope`), и `iss` там нет; форкать SDK нельзя, поэтому `iss` дописывается в
    `Location` по дороге. Редирект на страницу входа (без `code` и `error`) не трогается:
    браузер вернётся к клиенту уже со страницы, и `iss` ставит она сама
    (`app/mcp/consent.py`). `iss` — тот же issuer, что в метаданных сервера авторизации
    для этого запроса: `issuer` получает область ASGI запроса и называет его.
    """

    def __init__(self, app: ASGIApp, issuer: Callable[[Scope], str]) -> None:
        self.app = app
        self._issuer = issuer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != _AUTHORIZE_PATH:
            await self.app(scope, receive, send)
            return

        issuer = self._issuer(scope)

        async def forward(message: Message) -> None:
            if message["type"] == "http.response.start" and 300 <= message["status"] < 400:
                headers = [
                    (name, _with_issuer(value, issuer) if name.lower() == b"location" else value)
                    for name, value in message.get("headers", [])
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, forward)


def _with_issuer(location: bytes, issuer: str) -> bytes:
    url = location.decode()
    query = parse_qs(urlsplit(url).query)
    if "iss" in query or not ({"code", "error"} & query.keys()):
        return location
    return construct_redirect_uri(url, iss=issuer).encode()


def advertise_client_documents(application: Starlette, settings: Settings) -> None:
    """Подменяет метаданные сервера авторизации SDK на объявляющие CIMD и метод `none`.

    SDK строит их сам (`build_metadata`) и отдаёт маршрутом
    `/.well-known/oauth-authorization-server`; здесь маршрут получает тот же документ
    плюс `client_id_metadata_document_supported: true` и `none` среди методов `/token`.
    Issuer документа — адрес, которым служба себя называет этому запросу
    (`ServiceOrigin`): клиент сверяет его с адресом, по которому документ получил
    (RFC 8414 §3.3). Сервер авторизации не поднят (`authorization_enabled` ложно) —
    маршрута нет, и подменять нечего.
    """
    origin = ServiceOrigin(settings)
    documents: dict[str, OAuthMetadata] = {}

    def document(served: str) -> OAuthMetadata:
        if served in documents:
            return documents[served]
        auth = auth_settings(settings, served)
        metadata = build_metadata(
            auth.issuer_url,
            auth.service_documentation_url,
            auth.client_registration_options or ClientRegistrationOptions(),
            auth.revocation_options or RevocationOptions(),
            supports_identity_assertion=auth.identity_assertion_enabled,
        )
        methods = ["none", *(metadata.token_endpoint_auth_methods_supported or [])]
        documents[served] = metadata.model_copy(
            update={
                "client_id_metadata_document_supported": True,
                # RFC 9207: каждый ответ `/authorize` несёт `iss` (слой `IssuerOnAuthorize`
                # ниже и страница согласия), поэтому флаг объявляется без оговорок.
                "authorization_response_iss_parameter_supported": True,
                "token_endpoint_auth_methods_supported": list(dict.fromkeys(methods)),
            }
        )
        return documents[served]

    async def handle(request: Request) -> Response:
        return await MetadataHandler(document(origin.of(request.scope))).handle(request)

    def issuer(scope: Scope) -> str:
        return str(document(origin.of(scope)).issuer)

    endpoint = cors_middleware(handle, ["GET", "OPTIONS"])
    for route in application.router.routes:
        if isinstance(route, Route) and route.path == _AS_METADATA_PATH:
            route.app = endpoint
    application.add_middleware(IssuerOnAuthorize, issuer=issuer)
    application.add_middleware(ResourceOnToken, resource=settings.effective_mcp_public_url)


class DeclaredScope:
    """Внешний слой: дописывает `scope="casefile"` в `WWW-Authenticate` ответа `401`.

    SDK кладёт в вызов только `error`, `error_description` и `resource_metadata`, а область
    берёт из `required_scopes`; их у Casefile нет намеренно (область токена не проверяется,
    TRK-484), поэтому параметр дописывается по дороге. Ответ без `Bearer` или с уже
    названным `scope` не трогается. `resource_metadata` SDK строит из публичного адреса;
    запросу на другое имя петли той же службы (`ServiceOrigin`) слой называет документ на
    узле запроса: клиент сверит `resource` в нём с адресом, куда подключался (RFC 9728 §3.3).
    """

    def __init__(self, app: ASGIApp, origin: ServiceOrigin) -> None:
        self.app = app
        self._origin = origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        served = self._origin.of(scope)
        configured = self._origin.configured

        async def forward(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = [
                    (
                        name,
                        _challenge(value, configured, served)
                        if name.lower() == _CHALLENGE
                        else value,
                    )
                    for name, value in message.get("headers", [])
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, forward)


def _challenge(challenge: bytes, configured: str, served: str) -> bytes:
    text = challenge.decode()
    if not text.startswith("Bearer "):
        return challenge
    if served != configured:
        text = text.replace(f'resource_metadata="{configured}/', f'resource_metadata="{served}/')
    if " scope=" not in text:
        text = f'{text}, scope="{SCOPE}"'
    return text.encode()


def declare_scope(application: Starlette, settings: Settings) -> None:
    """Объявляет единственную область `casefile` в документе ресурса и в `401`.

    Документ `/.well-known/oauth-protected-resource/…` SDK строит из `required_scopes`
    (пусто), поэтому маршрут получает тот же документ с `scopes_supported: [casefile]`.
    Область объявляется, но не требуется: токен без неё принимается как раньше. Адрес
    ресурса и сервера авторизации в документе — тот, которым служба называет себя этому
    запросу (`ServiceOrigin`).
    """
    origin = ServiceOrigin(settings)
    documents: dict[str, ProtectedResourceMetadataHandler] = {}

    async def handle(request: Request) -> Response:
        served = origin.of(request.scope)
        if served not in documents:
            auth = auth_settings(settings, served)
            documents[served] = ProtectedResourceMetadataHandler(
                ProtectedResourceMetadata(
                    resource=auth.resource_server_url,
                    authorization_servers=[AnyHttpUrl(auth.issuer_url)],
                    scopes_supported=[SCOPE],
                )
            )
        return await documents[served].handle(request)

    endpoint = cors_middleware(handle, ["GET", "OPTIONS"])
    for route in application.router.routes:
        if isinstance(route, Route) and route.path.startswith(_RESOURCE_METADATA_PREFIX):
            route.app = endpoint
    application.add_middleware(DeclaredScope, origin=origin)


class ServiceOrigin:
    """Каким адресом служба называет себя запросу: публичным или другим именем петли.

    Документы OAuth называют службу публичным адресом (`effective_mcp_public_url`), а
    клиент обязан сверить `resource` с адресом, куда подключался (RFC 9728 §3.3), и issuer —
    с адресом, откуда взял метаданные (RFC 8414 §3.3). У локальной установки адрес по
    умолчанию — `localhost`, плагин же подключается к `127.0.0.1` (TRK-451), и Claude Code
    с Codex на расхождении отказывали во входе (TRK-488). Поэтому локальная служба
    называет себя тем именем петли, на которое пришёл запрос: `localhost`, `127.0.0.1`
    или `[::1]`, — при том же порте, что у публичного адреса.

    Только при публичном адресе `http` на петле и не в режиме входа по учётным записям:
    в сети узел один (`allowed_hosts`), и любой другой `Host` получает публичный адрес.
    `Host` пишет клиент, но выбрать он может лишь одно из трёх имён петли этой же машины.
    """

    def __init__(self, settings: Settings) -> None:
        parts = urlsplit(settings.effective_mcp_public_url)
        self.configured = f"{parts.scheme}://{parts.netloc}"
        self._port = parts.port or 80
        self._aliases = (
            parts.scheme == "http"
            and (parts.hostname or "") in _LOOPBACK
            and settings.login != "password"
        )

    def of(self, scope: Scope) -> str:
        """Начало адреса (`схема://узел:порт`), которым служба называет себя запросу."""
        if not self._aliases:
            return self.configured
        headers = scope.get("headers", [])
        host = next((value.decode("latin-1") for name, value in headers if name == b"host"), "")
        try:
            parts = urlsplit(f"//{host}")
            name, port = (parts.hostname or "").lower(), parts.port
        except ValueError:
            return self.configured
        if name not in _LOOPBACK or port != self._port:
            return self.configured
        return f"http://{'[::1]' if name == '::1' else name}:{port}"


_RESOURCE_METADATA_PREFIX = "/.well-known/oauth-protected-resource"
_CHALLENGE = b"www-authenticate"

_AS_METADATA_PATH = "/.well-known/oauth-authorization-server"
_AUTHORIZE_PATH = "/authorize"
_TOKEN_PATH = "/token"


def allowed_hosts(settings: Settings) -> TransportSecuritySettings | None:
    """Сетевой режим входа: эндпоинт MCP отвечает только на узле публичного адреса.

    SDK сам включает проверку `Host` и `Origin` (защита от DNS rebinding) лишь при
    привязке к петле; в контейнере служба слушает `0.0.0.0`, и проверки нет. В сети со
    входом по учётным записям (`TRACKER_LOGIN=password`) узел один — публичный адрес за
    прокси (`TRACKER_MCP_PUBLIC_URL`), и запрос на любой другой получает `421`: прокси
    обязан передавать `Host` клиента (README, «Network mode»). Локально — как у SDK.
    """
    if settings.login != "password" or not authorization_enabled(settings):
        return None
    parts = urlsplit(settings.effective_mcp_public_url)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[parts.netloc],
        allowed_origins=[f"{parts.scheme}://{parts.netloc}"],
    )


def authorization_enabled(settings: Settings) -> bool:
    """Пригоден ли публичный адрес службы в issuer: `https` или `http` на петле."""
    parts = urlsplit(settings.effective_mcp_public_url)
    return parts.scheme == "https" or (
        parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK
    )


def auth_settings(settings: Settings, origin: str | None = None) -> AuthSettings:
    """Описание ресурса и сервера авторизации: оба — публичный адрес службы mcp.

    Адрес берётся из `effective_mcp_public_url`: клиент за прокси и по TLS ходит на него,
    и `resource` в метаданных обязан совпасть с адресом, по которому он пришёл. `origin`
    заменяет начало адреса (`схема://узел:порт`) тем, которым служба называет себя
    запросу на другое имя петли (`ServiceOrigin`); путь остаётся прежним.
    """
    resource = settings.effective_mcp_public_url
    parts = urlsplit(resource)
    issuer = origin or f"{parts.scheme}://{parts.netloc}"
    if origin is not None:
        resource = f"{origin}{parts.path}"
    return AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource,
        # Область токена не проверяется: у агента один вид доступа, наборов нет.
        # `resource` сверяется сам: на `/authorize` провайдером, на `/token` слоем
        # `ResourceOnToken`; проверка SDK на запросе с токеном (`aud`) без JWT не нужна.
        validate_token_resource=False,
        required_scopes=None,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
    )
