"""Служба mcp как защищённый ресурс OAuth 2.0 (RFC 9728): объявление, а не выдача.

Клиент без токена получает `401` с `WWW-Authenticate: Bearer resource_metadata="…"` и по
этой ссылке узнаёт, где брать токен: `/.well-known/oauth-protected-resource` называет
сервер авторизации. Этим занимается SDK — достаточно дать серверу `AuthSettings` и
проверяющего токены. Сам сервер авторизации (DCR, PKCE, `/token`) — следующий шаг
программы TRK-446; здесь его адрес — сама служба mcp.

## Проверяющий только узнаёт, что токен есть

Настоящая проверка токена остаётся там, где была: `authenticate` на каждом вызове
(`app/mcp/runtime.py`). Она же отвечает за `details.reason` — `token_revoked`,
`unknown_token`, `token_expired`, — и её код ошибки клиенты агентов уже разбирают.
Проверка в SDK до протокола вернула бы им безликий `invalid_token` и отняла причину.
Поэтому `PresentedToken` пропускает любой непустой bearer и сам ничего не решает: `401`
транспорта — только на запрос без токена вовсе. Когда `/token` начнёт выдавать токены
OAuth, именно здесь отказ отозванному токену станет `401` с `resource_metadata`, чтобы
клиент пошёл на обновление; до тех пор клиента, у которого обновлять нечем, это только
сбило бы.
"""

from urllib.parse import urlsplit

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from app.core.config import Settings

__all__ = ["PresentedToken", "auth_settings"]

#: Единственная область токена служб Casefile: права задаёт набор токена, а не область.
SCOPE = "casefile"


class PresentedToken:
    """Проверяющий SDK: токен в заголовке есть — запрос идёт дальше, разбор за `authenticate`."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.strip():
            return None
        return AccessToken(token=token, client_id="casefile", scopes=[SCOPE], expires_at=None)


def auth_settings(settings: Settings) -> AuthSettings:
    """Описание ресурса: его адрес — публичный адрес MCP, сервер авторизации — тот же хост.

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
    )
