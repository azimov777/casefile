"""Адрес клиента запроса: кто открыл соединение или что сказал о нём свой прокси.

Нужен окну попыток входа по паролю (`app/services/login.py`): неудачи считаются на
адрес клиента, и толк от этого есть, только если адрес нельзя написать себе самому.
Поэтому заголовку верят не по его присутствию, а по тому, **кто** его прислал
(`docs/CONCEPT.md`, 5.4; решение TRK-98#6):

- собеседник TCP, названный в `TRACKER_REAL_IP_FROM`, — nginx интерфейса своей установки
  (прод-контур называет службу `ui`). Он перезаписывает `X-Real-IP` адресом, который
  видел сам (`ui/docker/nginx.conf.template`), и адрес клиента берётся оттуда;
- любой другой собеседник — сам себе адрес, что бы ни стояло в его заголовках.

`X-Forwarded-For` здесь не читается вовсе. Цепочку прокси разбирает nginx, и только от
прокси, которого владелец назвал в `CASEFILE_TRUSTED_PROXIES`; второй разбор той же
цепочки здесь был бы вторым правилом доверия, проверяемым отдельно от первого.
"""

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger("client_address")

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
type Resolver = Callable[[str], Awaitable[frozenset[IPAddress]]]

#: Заголовок, в котором свой прокси сообщает адрес клиента. Перезаписывает его nginx
#: интерфейса (`proxy_set_header X-Real-IP $remote_addr`), поэтому присланное клиентом
#: до API не доходит.
REAL_IP_HEADER = "x-real-ip"

#: Сколько секунд помнится разрешённое имя доверенного прокси. Без запоминания каждая
#: попытка входа — в том числе поток отказов `429` — шла бы в DNS; с долгим — `ui`,
#: пересозданный обновлятором с новым адресом, долго оставался бы чужим.
RESOLVE_TTL_SECONDS = 5.0


async def resolve_host(name: str) -> frozenset[IPAddress]:
    """Адреса имени по DNS контейнера. Имя службы compose разрешает встроенный DNS Docker."""
    infos = await asyncio.get_running_loop().getaddrinfo(name, None, type=socket.SOCK_STREAM)
    # У адреса IPv6 из `getaddrinfo` бывает зона (`fe80::1%eth0`); собеседник её не несёт.
    return frozenset(ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos)


def parse_address(value: str | None) -> IPAddress | None:
    """Адрес из строки или `None`, если это не адрес (имя тестового клиента, мусор)."""
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


class ClientAddresses:
    """Кто клиент запроса: собеседник TCP или `X-Real-IP` от собеседника из списка.

    Список — из настройки `TRACKER_REAL_IP_FROM`: адреса, сети и имена хостов. Имя
    разрешается при запросе, а не при старте: служба `ui` поднимается после API и
    получает новый адрес при каждом пересоздании.
    """

    def __init__(
        self,
        trusted: Sequence[str],
        *,
        resolve: Resolver = resolve_host,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = RESOLVE_TTL_SECONDS,
    ) -> None:
        networks: list[IPNetwork] = []
        names: list[str] = []
        for entry in trusted:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                names.append(entry)
        self._networks = tuple(networks)
        self._names = tuple(names)
        self._resolve = resolve
        self._clock = clock
        self._ttl = ttl
        #: Имя → (до какого момента верно, адреса). Записей не больше, чем имён в настройке.
        self._resolved: dict[str, tuple[float, frozenset[IPAddress]]] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> ClientAddresses:
        return cls(settings.real_ip_from)

    async def of(self, request: Request) -> IPAddress | None:
        """Адрес клиента запроса; `None` — адрес неизвестен (у ASGI нет собеседника).

        Доверенный собеседник без годного `X-Real-IP` — сам себе адрес, и это видно в
        журнале: nginx установки заголовок ставит всегда, и его отсутствие значит, что
        перед API стоит не он.
        """
        peer = parse_address(request.client.host if request.client else None)
        if peer is None or not await self._trusts(peer):
            return peer
        claimed = parse_address(request.headers.get(REAL_IP_HEADER))
        if claimed is None:
            logger.warning(
                "Trusted peer %s sent no usable %s header; counting it as the client",
                peer,
                REAL_IP_HEADER,
            )
            return peer
        return claimed

    async def _trusts(self, peer: IPAddress) -> bool:
        if any(peer in network for network in self._networks):
            return True
        for name in self._names:
            if peer in await self._addresses_of(name):
                return True
        return False

    async def _addresses_of(self, name: str) -> frozenset[IPAddress]:
        now = self._clock()
        cached = self._resolved.get(name)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            addresses = await self._resolve(name)
        except OSError as exc:
            # Имя не разрешилось: служба `ui` остановлена или пересоздаётся. Доверия нет —
            # собеседник остаётся сам себе адресом, и это безопасная сторона.
            logger.warning("Trusted proxy name %s did not resolve: %s", name, exc)
            addresses = frozenset()
        self._resolved[name] = (now + self._ttl, addresses)
        return addresses


def get_client_addresses(request: Request) -> ClientAddresses:
    """Правило того приложения, которое обслуживает запрос (`create_app`)."""
    addresses: ClientAddresses = request.app.state.client_addresses
    return addresses


ClientAddressesDep = Annotated[ClientAddresses, Depends(get_client_addresses)]
