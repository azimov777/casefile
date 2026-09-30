"""Служба mcp — защищённый ресурс OAuth 2.0 и сервер авторизации OAuth 2.1 при нём.

Клиент без токена получает `401` с `WWW-Authenticate: Bearer resource_metadata="…"`,
по метаданным protected resource (RFC 9728) находит сервер авторизации — эту же службу,
регистрируется (DCR, RFC 7591), проходит `/authorize` с PKCE S256 и получает в `/token`
обычный токен участника `trk_…` набора `task` и refresh-токен. Маршруты, разбор запросов,
PKCE и точное сравнение `redirect_uri` — SDK; здесь только перевод его вызовов в
сценарии `app/services/oauth.py` и обратно. Решения — `TRK-448#8`, `TRK-448#9`.

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
from typing import Any
from urllib.parse import urlsplit

from mcp.server.auth.handlers.metadata import MetadataHandler
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
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl, ValidationError
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.domain.oauth import OAUTH_SCOPE, OAuthRefusal, redirect_matches
from app.mcp.runtime import SessionFactory
from app.services import oauth as oauth_service
from app.services.auth import verify_token
from app.services.client_documents import ClientDocuments

__all__ = [
    "SCOPE",
    "CasefileAuthorization",
    "LoopbackClient",
    "PresentedToken",
    "RefusalReasons",
    "advertise_client_documents",
    "auth_settings",
    "authorization_enabled",
]

logger = get_logger("oauth")

#: Единственная область токена служб Casefile: права задаёт набор токена, а не область.
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
        except UnauthorizedError as refusal:
            holder = _refusal.get()
            if holder is not None:
                holder["reason"] = str(refusal.details.get("reason", "unauthorized"))
                holder["message"] = refusal.message
            return None
        return AccessToken(
            token=token, client_id=_TOKEN_CLIENT, scopes=[SCOPE], expires_at=None, subject=subject
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
        consent: oauth_service.ConsentPolicy,
        documents: ClientDocuments | None = None,
    ) -> None:
        super().__init__(sessions)
        self._consent = consent
        self._documents = documents or ClientDocuments()

    # --- Клиенты -------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self._sessions() as session:
            metadata = await oauth_service.find_client(
                session, client_id, documents=self._documents
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
                pair = await oauth_service.redeem_code(session, code_id=authorization_code.row_id)
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
                    session, refresh_id=refresh_token.row_id, scopes=scopes
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


def _present(metadata: dict[str, Any]) -> dict[str, Any]:
    """Метаданные без пустых полей: в базе — то, что клиент прислал, а не умолчания схемы."""
    return {key: value for key, value in metadata.items() if value is not None}


def _token_response(pair: oauth_service.IssuedPair) -> OAuthToken:
    """Ответ `/token`. Без `expires_in`: токен участника живёт до отзыва (`TRK-448#9`)."""
    return OAuthToken(
        access_token=pair.access_token,
        token_type="Bearer",
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


def advertise_client_documents(application: Starlette, settings: Settings) -> None:
    """Подменяет метаданные сервера авторизации SDK на объявляющие CIMD и метод `none`.

    SDK строит их сам (`build_metadata`) и отдаёт маршрутом
    `/.well-known/oauth-authorization-server`; здесь маршрут получает тот же документ
    плюс `client_id_metadata_document_supported: true` и `none` среди методов `/token`.
    Сервер авторизации не поднят (`authorization_enabled` ложно) — маршрута нет, и
    подменять нечего.
    """
    auth = auth_settings(settings)
    metadata = build_metadata(
        auth.issuer_url,
        auth.service_documentation_url,
        auth.client_registration_options or ClientRegistrationOptions(),
        auth.revocation_options or RevocationOptions(),
        supports_identity_assertion=auth.identity_assertion_enabled,
    )
    methods = ["none", *(metadata.token_endpoint_auth_methods_supported or [])]
    metadata = metadata.model_copy(
        update={
            "client_id_metadata_document_supported": True,
            "token_endpoint_auth_methods_supported": list(dict.fromkeys(methods)),
        }
    )
    endpoint = cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"])
    for route in application.router.routes:
        if isinstance(route, Route) and route.path == _AS_METADATA_PATH:
            route.app = endpoint


_AS_METADATA_PATH = "/.well-known/oauth-authorization-server"


def authorization_enabled(settings: Settings) -> bool:
    """Пригоден ли публичный адрес службы в issuer: `https` или `http` на петле."""
    parts = urlsplit(settings.effective_mcp_public_url)
    return parts.scheme == "https" or (
        parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK
    )


def auth_settings(settings: Settings) -> AuthSettings:
    """Описание ресурса и сервера авторизации: оба — публичный адрес службы mcp.

    Адрес берётся из `effective_mcp_public_url`: клиент за прокси и по TLS ходит на него,
    и `resource` в метаданных обязан совпасть с адресом, по которому он пришёл.
    """
    resource = settings.effective_mcp_public_url
    parts = urlsplit(resource)
    issuer = f"{parts.scheme}://{parts.netloc}"
    return AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource,
        # Область токена не проверяется: токен — обычный токен участника, права — в наборе.
        validate_token_resource=False,
        required_scopes=None,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
    )
