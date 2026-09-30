"""Вход агента через OAuth 2.1: правила, которые не зависят ни от HTTP, ни от SDK.

Сервер авторизации живёт в службе mcp (`app/mcp/oauth.py`, программа TRK-446). Выдаёт он
не свой вид доступа, а обычный токен участника (`app/domain/tokens.py`): права, отзыв и
подпись в деле те же. Своё у OAuth только то, что ведёт к этому токену, — клиент,
одноразовый код и refresh-токен. Их правила собраны здесь.

## Секреты хранятся хешем

Код и refresh-токен — такие же случайные секреты высокой энтропии, как токен участника,
и хешируются тем же быстрым SHA-256 (`hash_token`): перебор 256 бит невозможен, а поиск
идёт одним запросом по уникальному индексу. Украденный дамп базы не даёт ни кода, ни
refresh. Секрета клиента нет вовсе: все клиенты публичные (`app/services/oauth.py`).

## Почему `http` допустим только на петле

Код уходит браузером на `redirect_uri` клиента. Адрес на петле — это процесс на той же
машине (Claude Code, Codex слушают `http://localhost:<порт>/callback`), и чужой узел кода
не увидит. `http` на любом другом адресе отдал бы код всем на пути (OAuth 2.1, §2.3.1),
поэтому регистрация такой адрес не принимает. `https` и прочие схемы проходят регистрацию,
но согласие без страницы выдаётся только на петлю (`is_loopback_redirect`).

## Порт адреса на петле не сравнивается

Нативный клиент слушает callback на порту, который ему дала система в момент входа, и
знать его при регистрации не может. Документы CIMD Claude Code и Codex поэтому пишут
`http://127.0.0.1/callback` без порта, а приходят на `/authorize` с
`http://127.0.0.1:54822/callback` (TRK-432#6). RFC 8252 §7.3 велит серверу принимать
на петле любой порт: `redirect_matches` сравнивает такой адрес без порта, а всё прочее —
точно, строкой, как SDK. Касается это и CIMD, и DCR.

## Клиент узнаётся по адресу документа, а без него — по имени

Правило владельца `TRK-446#14` выбирает участника по клиенту: Claude Code → `claude`,
Codex → `codex`, прочие → агент по умолчанию. Клиент по документу (CIMD) узнаётся по
`client_id` — адресу, который выдать за чужой нельзя: документ скачан с этого адреса.
Клиент DCR — по `client_name`, который он пишет сам. Подделка имени ничего не открывает:
в локальном режиме выбор участника делает сам владелец машины, а в сети имя выбирает
только агента по умолчанию среди своих агентов вошедшего человека (`TRK-475#14`).
"""

import secrets
from datetime import timedelta
from ipaddress import ip_address
from urllib.parse import urlsplit

__all__ = [
    "CODE_TTL",
    "OAUTH_SCOPE",
    "OAUTH_SECRET_ENTROPY_BYTES",
    "OTHER_CLIENT",
    "OAuthRefusal",
    "client_family",
    "generate_oauth_secret",
    "is_loopback_redirect",
    "oauth_token_name",
    "redirect_matches",
    "refuse_unsafe_redirect",
]

#: Единственная область OAuth в Casefile. Права задаёт набор токена, а не область, и
#: клиенту она нужна только как значение, которое можно запросить.
OAUTH_SCOPE = "casefile"

#: Сколько живёт код авторизации. Клиент меняет его на токен сразу после возврата
#: браузера — это миллисекунды; RFC 6749 §4.1.2 советует не больше десяти минут. Две
#: минуты оставляют запас на медленную машину и не дают коду пролежать без дела.
CODE_TTL = timedelta(minutes=2)

#: Энтропия кода и refresh-токена — как у токена участника (256 бит).
OAUTH_SECRET_ENTROPY_BYTES = 32

#: Предел имени токена в колонке `tokens.name`.
_TOKEN_NAME_LIMIT = 255

_LOOPBACK_HOSTS = frozenset({"localhost"})


class OAuthRefusal(Exception):
    """Отказ сценария OAuth с кодом протокола (RFC 6749, 7591) и пояснением.

    Не `AppError`: отказ уходит клиенту OAuth в форме его протокола (`error`,
    `error_description`), а не в оболочке REST, и переводит его слой mcp.
    """

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


def generate_oauth_secret(prefix: str) -> str:
    """Новый код или refresh-токен. Префикс отличает их от токена участника в логах."""
    return f"{prefix}{secrets.token_urlsafe(OAUTH_SECRET_ENTROPY_BYTES)}"


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() in _LOOPBACK_HOSTS:
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def is_loopback_redirect(uri: str) -> bool:
    """`http(s)` на адрес петли: код не покидает машину, на которой открыт браузер."""
    parts = urlsplit(uri)
    return parts.scheme in {"http", "https"} and _is_loopback_host(parts.hostname)


def redirect_matches(registered: str, requested: str) -> bool:
    """Годится ли запрошенный адрес возврата под зарегистрированный.

    Точное совпадение строк — всегда. Кроме него — `http` на петле (RFC 8252 §7.3):
    схема, узел, путь и запрос совпадают, порт любой. Узел сравнивается как есть:
    `localhost` не подменяет `127.0.0.1`, потому что клиент слушает конкретный адрес.
    """
    if registered == requested:
        return True
    try:
        want, got = urlsplit(registered), urlsplit(requested)
        want.port, got.port  # noqa: B018 — разбор порта бросает на мусоре
    except ValueError:
        return False
    if want.scheme != "http" or got.scheme != "http":
        return False
    if not _is_loopback_host(want.hostname) or want.hostname != got.hostname:
        return False
    if want.username or want.password or got.username or got.password:
        return False
    return (want.path or "/") == (got.path or "/") and want.query == got.query and not got.fragment


def refuse_unsafe_redirect(uris: list[str]) -> None:
    """Отказывает регистрации клиента с `http` не на петле (OAuth 2.1, §2.3.1).

    Фрагмент в адресе возврата запрещён RFC 6749 §3.1.2: код приехал бы в часть адреса,
    которую браузер не отправляет, и потерялся бы.
    """
    if not uris:
        raise OAuthRefusal("invalid_redirect_uri", "at least one redirect_uri is required")
    for uri in uris:
        parts = urlsplit(uri)
        if parts.fragment:
            raise OAuthRefusal("invalid_redirect_uri", f"redirect_uri {uri} has a fragment")
        if parts.scheme == "http" and not _is_loopback_host(parts.hostname):
            raise OAuthRefusal(
                "invalid_redirect_uri",
                f"redirect_uri {uri} uses http outside the loopback interface; use https",
            )


#: Семьи клиентов по правилу `TRK-446#14`: префикс адреса документа CIMD и начало имени DCR.
_CLIENT_FAMILIES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("claude", ("https://claude.ai/oauth/claude-code",), ("claude code",)),
    ("codex", ("https://chatgpt.com/oauth/codex/",), ("codex",)),
)
#: Семья прочих клиентов: их участник — агент по умолчанию.
OTHER_CLIENT = "agent"


def client_family(client_id: str, client_name: str | None) -> str:
    """Семья клиента: `claude` (Claude Code), `codex` (Codex) или `agent` для прочих.

    Клиент по документу узнаётся по адресу `client_id`, клиент DCR — по началу
    `client_name` без учёта регистра.
    """
    name = (client_name or "").strip().lower()
    for family, documents, names in _CLIENT_FAMILIES:
        if client_id.startswith(documents) or name.startswith(names):
            return family
    return OTHER_CLIENT


def oauth_token_name(client_name: str | None, client_id: str) -> str:
    """Имя выданного токена в «Доступах»: по нему человек узнаёт, какой клиент вошёл."""
    label = (client_name or "").strip() or client_id
    return f"oauth: {label}"[:_TOKEN_NAME_LIMIT]
