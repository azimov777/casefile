"""Скачивание документа метаданных клиента (CIMD) так, чтобы им нельзя было ударить внутрь.

Правила адреса и документа — `app/domain/client_documents.py`; здесь только сеть.
Адрес приходит от кого угодно (`client_id` в `/authorize`), поэтому загрузка:

- разрешает имя сама и отказывает, если **хоть один** адрес не публичный;
- соединяется с уже проверенным адресом, а имя узла передаёт только в SNI и `Host`:
  сертификат сверяется по имени, а второй ответ DNS ничего не подменит;
- не идёт по перенаправлениям: ответ не `200` — отказ (черновик CIMD их не требует,
  а каждое перенаправление — новый непроверенный адрес);
- читает не больше `DOCUMENT_MAX_BYTES` и укладывается в `DOCUMENT_TIMEOUT_SECONDS` от
  DNS до последнего байта;
- принимает только `application/json`.

Адрес приходит от кого угодно, поэтому загрузка ещё и бережёт службу (TRK-477): не больше
`fetch_limit` походов в сеть за `FETCH_WINDOW` на весь процесс, а отказавший адрес
запоминается на `refusal_ttl`, и повтор в этот срок не ходит в сеть вовсе. Ни то, ни
другое не ослабляет правил адреса: они проверяются раньше. Сама загрузка идёт вне
транзакции базы (`find_client` в `app/services/oauth.py`).

Любой сбой — `OAuthRefusal("invalid_client", …)`: для клиента это «такого клиента нет».
Кэш — не здесь, а в строке клиента в базе (`app/services/oauth.py`): он переживает
перезапуск службы и нужен коду и refresh как внешний ключ.

Сеть подменяется в тестах целиком: `ClientDocuments(resolve=…, request=…)`.
"""

import asyncio
import http.client
import json
import socket
import ssl
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Self
from urllib.parse import urlsplit

from app import __version__
from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.client_documents import (
    DOCUMENT_MAX_BYTES,
    DOCUMENT_PORT,
    DOCUMENT_TIMEOUT_SECONDS,
    check_document_url,
    document_lifetime,
    is_json_media_type,
    is_public_address,
)
from app.domain.oauth import OAuthRefusal

__all__ = [
    "ClientDocuments",
    "DocumentRequest",
    "DocumentResponse",
    "FetchedDocument",
    "Request",
    "Resolve",
]

logger = get_logger("oauth")

#: Окно предела частоты загрузок.
FETCH_WINDOW = timedelta(minutes=1)
#: Сколько отказавших адресов помнит отрицательный кэш; сверх этого вытесняются самые старые.
REFUSALS_REMEMBERED = 1024

_USER_AGENT = f"Casefile/{__version__} (OAuth client metadata)"


@dataclass(frozen=True, slots=True)
class DocumentRequest:
    """Что открыть: проверенный адрес узла, имя для SNI и `Host`, путь с запросом."""

    address: str
    host: str
    port: int
    target: str


@dataclass(frozen=True, slots=True)
class DocumentResponse:
    """Ответ сервера клиента: статус, заголовки (имена в нижнем регистре), тело."""

    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """Разобранный JSON документа и срок, на который его можно запомнить."""

    document: object
    lifetime: timedelta


#: Разрешение имени: все адреса узла.
type Resolve = Callable[[str, int], Awaitable[list[str]]]
#: Запрос `GET` по проверенному адресу; тело не длиннее предела плюс байт.
type Request = Callable[[DocumentRequest], Awaitable[DocumentResponse]]


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS к заранее проверенному адресу: TCP — на адрес, TLS и `Host` — на имя."""

    def __init__(self, request: DocumentRequest, timeout: float) -> None:
        super().__init__(
            request.host,
            request.port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._address = request.address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


def _get_blocking(request: DocumentRequest, deadline: float) -> DocumentResponse:
    connection = _PinnedHTTPSConnection(request, timeout=DOCUMENT_TIMEOUT_SECONDS)
    try:
        connection.request(
            "GET",
            request.target,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        )
        response = connection.getresponse()
        body = bytearray()
        # Кусками и с часами: медленный сервер, отдающий по байту, не держит поток дольше
        # срока, а длинный не заставит прочитать больше предела.
        while len(body) <= DOCUMENT_MAX_BYTES and time.monotonic() < deadline:
            chunk = response.read1(DOCUMENT_MAX_BYTES + 1 - len(body))
            if not chunk:
                break
            body.extend(chunk)
        else:
            if len(body) <= DOCUMENT_MAX_BYTES:
                raise TimeoutError("client metadata document took too long")
        headers = {name.lower(): value for name, value in response.getheaders()}
        return DocumentResponse(status=response.status, headers=headers, body=bytes(body))
    finally:
        connection.close()


async def _request(request: DocumentRequest) -> DocumentResponse:
    deadline = time.monotonic() + DOCUMENT_TIMEOUT_SECONDS
    return await asyncio.to_thread(_get_blocking, request, deadline)


@dataclass(frozen=True, slots=True)
class ClientDocuments:
    """Загрузчик документов CIMD; сеть подменяема целиком."""

    resolve: Resolve = field(default=_resolve)
    request: Request = field(default=_request)
    #: Походов в сеть за `FETCH_WINDOW` на весь процесс; сверх этого — отказ без сети.
    fetch_limit: int = 30
    #: Сколько отказавший адрес не пробуется заново.
    refusal_ttl: timedelta = timedelta(minutes=1)
    #: Часы предела и отрицательного кэша; тесты подменяют.
    clock: Callable[[], float] = field(default=time.monotonic)
    _fetched_at: deque[float] = field(default_factory=deque, init=False, repr=False)
    _refused_until: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def from_settings(cls) -> Self:
        settings = get_settings()
        return cls(
            fetch_limit=settings.oauth_document_fetch_limit,
            refusal_ttl=settings.oauth_document_refusal_ttl,
        )

    def remember_refusal(self, url: str) -> None:
        """Запоминает адрес как отказавший: документ, скачанный, но не прошедший правила."""
        now = self.clock()
        refused = self._refused_until
        for stale in [known for known, until in refused.items() if until <= now]:
            del refused[stale]
        while len(refused) >= REFUSALS_REMEMBERED:
            del refused[next(iter(refused))]
        refused[url] = now + self.refusal_ttl.total_seconds()

    def _refuse_while_remembered(self, url: str) -> None:
        until = self._refused_until.get(url)
        if until is not None and until > self.clock():
            raise OAuthRefusal("invalid_client", "client metadata document was refused recently")

    def _spend_fetch(self, url: str) -> None:
        now = self.clock()
        window = FETCH_WINDOW.total_seconds()
        fetched = self._fetched_at
        while fetched and fetched[0] <= now - window:
            fetched.popleft()
        if len(fetched) >= self.fetch_limit:
            raise self._refuse(url, "too many client metadata document fetches")
        fetched.append(now)

    async def fetch(self, url: str) -> FetchedDocument:
        """Скачивает и разбирает документ по адресу — или `OAuthRefusal("invalid_client")`."""
        check_document_url(url)
        self._refuse_while_remembered(url)
        self._spend_fetch(url)
        try:
            return await self._fetch_document(url)
        except OAuthRefusal:
            self.remember_refusal(url)
            raise

    async def _fetch_document(self, url: str) -> FetchedDocument:
        try:
            async with asyncio.timeout(DOCUMENT_TIMEOUT_SECONDS):
                response = await self._fetch(url)
        except OAuthRefusal:
            raise
        except TimeoutError:
            raise self._refuse(url, "client metadata document fetch timed out") from None
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as failure:
            # `ValueError` — `http.client` отказывает пути с пробелом или не-ASCII
            # (`InvalidURL`, `UnicodeEncodeError`): это адрес клиента, а не сбой службы.
            raise self._refuse(url, f"client metadata document fetch failed: {failure}") from None

        if response.status != 200:
            raise self._refuse(url, f"client metadata document answered HTTP {response.status}")
        if len(response.body) > DOCUMENT_MAX_BYTES:
            raise self._refuse(url, "client metadata document is too large")
        if not is_json_media_type(response.headers.get("content-type")):
            raise self._refuse(url, "client metadata document is not application/json")
        try:
            document = json.loads(response.body)
        except ValueError:
            raise self._refuse(url, "client metadata document is not valid JSON") from None
        return FetchedDocument(
            document=document, lifetime=document_lifetime(response.headers.get("cache-control"))
        )

    async def _fetch(self, url: str) -> DocumentResponse:
        parts = urlsplit(url)
        host = parts.hostname or ""
        addresses = await self.resolve(host, DOCUMENT_PORT)
        if not addresses:
            raise self._refuse(url, "client_id host does not resolve")
        private = [address for address in addresses if not is_public_address(address)]
        if private:
            raise self._refuse(url, "client_id host resolves to a non-public address")
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        # Все адреса проверены; следующий пробуется, только если к этому не соединиться.
        *spare, last = addresses
        for address in spare:
            try:
                return await self.request(_target(address, host, target))
            except ConnectionError:
                continue
        return await self.request(_target(last, host, target))

    @staticmethod
    def _refuse(url: str, reason: str) -> OAuthRefusal:
        logger.warning("CIMD refused %s: %s", url, reason)
        return OAuthRefusal("invalid_client", reason)


def _target(address: str, host: str, target: str) -> DocumentRequest:
    return DocumentRequest(address=address, host=host, port=DOCUMENT_PORT, target=target or "/")
