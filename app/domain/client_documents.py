"""Клиент по документу метаданных (CIMD): правила без сети, базы и SDK.

Клиент называет себя `https`-адресом (`client_id`), и по этому адресу лежит JSON с его
метаданными — как ответ регистрации DCR, только размещённый самим клиентом. Claude Code
и Codex пользуются этим, если сервер авторизации объявляет
`client_id_metadata_document_supported` (TRK-432#6). Спецификация — draft-ietf-oauth-
client-id-metadata-document и раздел authorization спецификации MCP. Скачивает документ
`app/services/client_documents.py`, решает о клиенте `app/services/oauth.py`.

## Почему сервер ходит по адресу, который ему назвал кто угодно

`/authorize` открыт без входа, и `client_id` в нём пишет сам запрашивающий. Значит,
любой, кто достучался до службы, может заставить её сходить по своему адресу (SSRF).
Поэтому адрес документа ограничен дважды:

- по форме (`check_document_url`) — только `https`, порт 443, без логина в адресе, без
  фрагмента, с путём и без `.`/`..` в нём;
- по адресу узла (`is_public_address`) — каждое имя, которое вернул DNS, обязано быть
  публичным адресом интернета: петля, частные сети, link-local (в том числе
  169.254.169.254 — метаданные облака), CGNAT и зарезервированные отказываются. Узел с
  хотя бы одним таким адресом отказывается целиком, а соединение идёт на уже
  проверенный адрес, а не на имя: иначе второй ответ DNS подменил бы его (DNS rebinding).

## Что сервер принимает из документа

Документ — ровно JSON-объект, чей `client_id` совпадает с адресом, откуда он скачан, со
списком `redirect_uris` по тем же правилам, что у DCR (`refuse_unsafe_redirect`). Секрета
у такого клиента быть не может (общий секрет, опубликованный по URL, — не секрет), и
метод на `/token` — только `none`: его защищает PKCE, как у всех клиентов Casefile.
"""

import re
from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any
from urllib.parse import urlsplit

from app.domain.oauth import OAUTH_SCOPE, OAuthRefusal, refuse_unsafe_redirect

__all__ = [
    "DOCUMENT_DEFAULT_LIFETIME",
    "DOCUMENT_MAX_BYTES",
    "DOCUMENT_MAX_LIFETIME",
    "DOCUMENT_MIN_LIFETIME",
    "DOCUMENT_PORT",
    "DOCUMENT_TIMEOUT_SECONDS",
    "check_document_url",
    "client_from_document",
    "document_lifetime",
    "is_document_client_id",
    "is_json_media_type",
    "is_public_address",
]

#: Предел размера документа. Документы Claude Code и Codex — 317 и 500 байт (замер
#: 2026-10-01); черновик CIMD советует серверу держать предел около 5 КБ.
DOCUMENT_MAX_BYTES = 5 * 1024

#: Сколько вся загрузка документа может занять — от DNS до последнего байта. Её ждёт
#: `/authorize` или `/token` клиента, у которого документ ещё не в кэше.
DOCUMENT_TIMEOUT_SECONDS = 5.0

#: Единственный порт документа. Другой порт на публичном узле ничем не нужен клиенту,
#: а службе дал бы простукивать чужие порты.
DOCUMENT_PORT = 443

#: Сколько документ живёт в кэше, если сервер клиента не сказал (`Cache-Control`).
DOCUMENT_DEFAULT_LIFETIME = timedelta(hours=1)
#: Короче не храним даже при `no-store`: иначе каждый шаг входа ходил бы в сеть заново.
DOCUMENT_MIN_LIFETIME = timedelta(minutes=5)
#: Дольше не храним: клиент, убравший адрес возврата, не должен ждать сутки.
DOCUMENT_MAX_LIFETIME = timedelta(hours=24)

_MAX_AGE = re.compile(r"(?:^|,)\s*max-age\s*=\s*\"?(\d+)\"?\s*(?:,|$)", re.IGNORECASE)

#: Поля секрета, которых у клиента по документу быть не может.
_SECRET_FIELDS = ("client_secret", "client_secret_expires_at")


def is_document_client_id(client_id: str) -> bool:
    """Называет ли `client_id` клиента по документу: он записан адресом `http(s)`.

    `http` сюда тоже попадает — чтобы получить отказ, а не уйти искать клиента DCR.
    """
    scheme = client_id.split(":", 1)[0].lower() if ":" in client_id else ""
    return scheme in {"http", "https"}


def check_document_url(url: str) -> None:
    """Отказывает адресу документа, по которому служба ходить не станет.

    Отказ — `OAuthRefusal("invalid_client", …)`: клиент с таким `client_id` не существует.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise OAuthRefusal("invalid_client", "client_id is not a valid URL") from None
    if parts.scheme != "https":
        raise OAuthRefusal("invalid_client", "client_id metadata document must be served by https")
    if not parts.hostname:
        raise OAuthRefusal("invalid_client", "client_id URL has no host")
    if parts.username is not None or parts.password is not None:
        raise OAuthRefusal("invalid_client", "client_id URL must not carry credentials")
    if parts.fragment or url.endswith("#"):
        raise OAuthRefusal("invalid_client", "client_id URL must not have a fragment")
    if port is not None and port != DOCUMENT_PORT:
        raise OAuthRefusal("invalid_client", "client_id URL must use the default https port")
    segments = parts.path.split("/")
    if not parts.path.strip("/"):
        raise OAuthRefusal("invalid_client", "client_id URL must have a path")
    if any(segment in {".", ".."} for segment in segments):
        raise OAuthRefusal("invalid_client", "client_id URL must not have dot segments")
    if _is_literal_address(parts.hostname) and not is_public_address(parts.hostname):
        raise OAuthRefusal("invalid_client", "client_id URL points to a non-public address")


def _is_literal_address(host: str) -> bool:
    try:
        ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def is_public_address(address: str) -> bool:
    """Публичный ли адрес интернета: только на такой служба откроет соединение.

    `is_global` отсекает петлю, частные сети, link-local, CGNAT (100.64/10), общие и
    зарезервированные блоки. Адрес IPv4, завёрнутый в IPv6 (`::ffff:10.0.0.1`,
    `64:ff9b::…`), проверяется по своей IPv4-части. Групповой адрес не бывает узлом.
    """
    try:
        parsed: IPv4Address | IPv6Address = ip_address(address.strip("[]").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(parsed, IPv6Address):
        inner = parsed.ipv4_mapped or parsed.sixtofour
        if inner is not None:
            parsed = inner
    return parsed.is_global and not parsed.is_multicast


def is_json_media_type(content_type: str | None) -> bool:
    """`application/json` или `application/<что-то>+json`, параметры не важны."""
    if not content_type:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or (
        media.startswith("application/") and media.endswith("+json")
    )


def document_lifetime(cache_control: str | None) -> timedelta:
    """Срок документа в кэше: `max-age` сервера клиента в пределах от 5 минут до суток.

    `no-store`/`no-cache` — нижний предел, а не ноль: вход — несколько запросов подряд
    (`/authorize`, `/token`), и каждый качал бы документ заново.
    """
    if cache_control:
        lowered = cache_control.lower()
        if "no-store" in lowered or "no-cache" in lowered:
            return DOCUMENT_MIN_LIFETIME
        found = _MAX_AGE.search(cache_control)
        if found:
            seconds = timedelta(seconds=int(found.group(1)))
            return min(max(seconds, DOCUMENT_MIN_LIFETIME), DOCUMENT_MAX_LIFETIME)
    return DOCUMENT_DEFAULT_LIFETIME


def client_from_document(url: str, document: object) -> dict[str, Any]:
    """Метаданные клиента из документа — или отказ `invalid_client`.

    Возвращает то, что сервер будет считать регистрацией клиента: поля документа, метод
    `none`, область Casefile и виды обмена по умолчанию, если документ их не назвал.
    """
    if not isinstance(document, dict):
        raise OAuthRefusal("invalid_client", "client metadata document is not a JSON object")
    if document.get("client_id") != url:
        raise OAuthRefusal(
            "invalid_client", "client_id in the metadata document does not match its URL"
        )
    present = [field for field in _SECRET_FIELDS if document.get(field) is not None]
    if present:
        raise OAuthRefusal(
            "invalid_client", "client metadata document must not carry a client secret"
        )
    method = document.get("token_endpoint_auth_method")
    if method not in {None, "none"}:
        raise OAuthRefusal(
            "invalid_client", "client metadata document must use token_endpoint_auth_method none"
        )
    uris = document.get("redirect_uris")
    if not isinstance(uris, list) or not all(isinstance(uri, str) for uri in uris):
        raise OAuthRefusal("invalid_client", "client metadata document has no redirect_uris list")
    try:
        refuse_unsafe_redirect(uris)
    except OAuthRefusal as refusal:
        raise OAuthRefusal("invalid_client", refusal.description) from None
    return {
        **{key: value for key, value in document.items() if value is not None},
        "client_id": url,
        "token_endpoint_auth_method": "none",
        "grant_types": document.get("grant_types") or ["authorization_code", "refresh_token"],
        "response_types": document.get("response_types") or ["code"],
        "scope": OAUTH_SCOPE,
    }
