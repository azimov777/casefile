"""Сценарии входа через OAuth 2.1: клиент, код, обмен на токен участника, refresh.

Слой mcp (`app/mcp/oauth.py`) переводит сюда вызовы провайдера SDK и обратно, а
правила живут здесь. Выдаётся обычный токен участника — тот же, что
выпускают «Доступы» (`app/services/tokens.py`), и отзывается он там же. Решения —
`TRK-448#8` и `TRK-448#9`.

## Кому выдать — отдельная точка

`/authorize` спрашивает `ConsentPolicy`: по клиенту и адресу возврата она называет
участника, от чьего имени будет говорить токен, и того, кто выдачу согласовал, — или
отказывает. Правило владельца (Claude Code → `claude`, Codex → `codex`, прочие → агент по
умолчанию, недостающий участник заводится сам; `TRK-446#14`) и страница входа в сети
встанут сюда задачей TRK-450. Пока стоит `DefaultAgentConsent`: участник `agent`, только
при `TRACKER_OAUTH_LOCAL_CONSENT` и только на адрес возврата на петле.

## Все клиенты публичные

SDK сверяет секрет клиента открытым текстом, то есть хранить его пришлось бы как есть.
Нативному клиенту (CLI на машине человека) секрет всё равно не тайна — защищает PKCE
S256, который SDK требует и сверяет сам. Поэтому регистрация заменяет метод на `none` и
не выдаёт секрета вовсе (RFC 7591 §3.2.1 разрешает серверу вернуть не то, что просили):
в базе секретов клиентов нет.

## Клиент по документу метаданных (CIMD)

Клиент, чей `client_id` — `https`-адрес, не регистрируется: `find_client` скачивает его
документ (`app/services/client_documents.py`), проверяет (`app/domain/client_documents.py`)
и запоминает строкой `oauth_clients` со сроком `document_expires_at`. Пока срок не
вышел, документ берётся из строки; вышел — скачивается заново. Не скачался или не прошёл
проверку — клиента нет, даже если в строке лежит прежний документ: клиент мог убрать
из него адрес возврата, и старая копия выдала бы код туда, куда он больше не велит.
`client_id` на `http` — тоже «клиента нет», без похода в сеть.

## Отзыв отрезает клиента целиком

Refresh годен, только пока жив его токен. Отзыв в «Доступах» делает refresh
недействительным, и тихо обновиться клиент не может — ему нужен новый вход. Ротация
гасит прежний refresh и отзывает прежний токен; повтор погашенного refresh отзывает
цепочку целиком.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.author import created_by_columns
from app.db.models.oauth import OAuthClient, OAuthCode, OAuthRefreshToken
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.repositories import OAuthRepository, ParticipantRepository
from app.domain.authors import Author, AuthorKind
from app.domain.client_documents import client_from_document, is_document_client_id
from app.domain.oauth import (
    CODE_TTL,
    OAUTH_SCOPE,
    OAuthRefusal,
    generate_oauth_secret,
    is_loopback_redirect,
    oauth_token_name,
    refuse_unsafe_redirect,
)
from app.domain.participants import ParticipantKind, normalize_participant_name
from app.domain.tokens import hash_token
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.client_documents import ClientDocuments
from app.services.participants import register_participant
from app.services.setup import DEFAULT_AGENT_DESCRIPTION, DEFAULT_AGENT_NAME
from app.services.tokens import issue_token

__all__ = [
    "CODE_PREFIX",
    "REFRESH_PREFIX",
    "ClientView",
    "CodeView",
    "ConsentPolicy",
    "DefaultAgentConsent",
    "Grant",
    "IssuedPair",
    "RefreshView",
    "authorize",
    "find_client",
    "find_code",
    "find_refresh",
    "redeem_code",
    "register_client",
    "rotate_refresh",
]

logger = get_logger("oauth")

#: Префиксы секретов: в логе и в переменной окружения видно, что это, а не токен `trk_`.
CODE_PREFIX = "trc_"
REFRESH_PREFIX = "trr_"

#: Сколько истёкший код хранится ради поимки повтора, прежде чем его уберёт уборка.
_CODE_RETENTION = timedelta(days=1)


# --- Кому выдать -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientView:
    """Клиент, каким его видит политика согласия: идентификатор, имя и метаданные целиком.

    Метаданные — как прислал клиент при регистрации (`client_name`, `software_id`,
    `redirect_uris`…): правило выбора участника по клиенту (TRK-450) читает их отсюда.
    """

    client_id: str
    client_name: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Grant:
    """Решение политики: от чьего имени токен и кто согласовал выдачу."""

    participant: Participant
    issuer: Author


class ConsentPolicy(Protocol):
    """Кому выдать токен по этому входу — или отказ `OAuthRefusal` (`access_denied`)."""

    async def __call__(
        self, session: AsyncSession, *, client: ClientView, redirect_uri: str
    ) -> Grant: ...


@dataclass(frozen=True, slots=True)
class DefaultAgentConsent:
    """Временное правило TRK-448: участник `agent`, согласие сразу — только на петлю.

    `enabled` — `TRACKER_OAUTH_LOCAL_CONSENT`. Выключено — отказ всем: служба mcp не знает,
    своя ли это машина, а согласие без страницы выдало бы токен любому в сети.
    """

    enabled: bool

    async def __call__(
        self, session: AsyncSession, *, client: ClientView, redirect_uri: str
    ) -> Grant:
        del client
        if not self.enabled:
            raise OAuthRefusal(
                "access_denied",
                "OAuth sign-in is not enabled on this installation; connect with a bearer token",
            )
        if not is_loopback_redirect(redirect_uri):
            raise OAuthRefusal(
                "access_denied",
                "sign-in without a consent page is granted to a loopback redirect_uri only",
            )
        return Grant(participant=await _default_agent(session), issuer=TRACKER_ACTOR.author)


async def _default_agent(session: AsyncSession) -> Participant:
    """Агент этой машины — тот же участник, кому установка выдаёт токен `agent-token`."""
    participants = ParticipantRepository(session)
    agent = await participants.get_by_name(normalize_participant_name(DEFAULT_AGENT_NAME))
    if agent is not None:
        return agent
    return await register_participant(
        session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.AGENT,
        name=DEFAULT_AGENT_NAME,
        description=DEFAULT_AGENT_DESCRIPTION,
    )


# --- Клиенты -----------------------------------------------------------------------


async def register_client(
    session: AsyncSession, *, client_id: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Сохраняет клиента DCR публичным и возвращает метаданные, которые он получит.

    Отказ `invalid_redirect_uri` — `http` не на петле или фрагмент в адресе возврата.
    """
    refuse_unsafe_redirect([str(uri) for uri in metadata.get("redirect_uris") or []])
    public = {
        **metadata,
        "client_id": client_id,
        "client_secret": None,
        "client_secret_expires_at": None,
        "token_endpoint_auth_method": "none",
    }
    await OAuthRepository(session).add(OAuthClient(client_id=client_id, client_metadata=public))
    logger.info("OAuth client registered by DCR: %s (%s)", client_id, metadata.get("client_name"))
    return public


async def find_client(
    session: AsyncSession,
    client_id: str,
    *,
    documents: ClientDocuments,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Метаданные клиента или `None`, если такого нет.

    `client_id`-адрес — клиент по документу: из строки, пока документ свеж, иначе
    скачанный заново (`documents`). Любой отказ загрузки или проверки — `None`.
    """
    repository = OAuthRepository(session)
    if not is_document_client_id(client_id):
        client = await repository.get_client(client_id)
        if client is None or client.document_expires_at is not None:
            return None
        return dict(client.client_metadata)

    moment = now or datetime.now(UTC)
    client = await repository.get_client(client_id)
    expires = None if client is None else client.document_expires_at
    if client is not None and expires is not None and expires > moment:
        return dict(client.client_metadata)
    try:
        fetched = await documents.fetch(client_id)
        metadata = client_from_document(client_id, fetched.document)
    except OAuthRefusal as refusal:
        logger.warning("OAuth client by CIMD refused: %s: %s", client_id, refusal.description)
        return None
    saved = await repository.save_document_client(client_id, metadata, moment + fetched.lifetime)
    logger.info(
        "OAuth client by CIMD: %s (%s), cached until %s",
        client_id,
        metadata.get("client_name"),
        saved.document_expires_at,
    )
    return dict(saved.client_metadata)


# --- Код авторизации ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodeView:
    """Код, каким его сверяет SDK: срок, PKCE, адрес возврата. Секрета здесь нет."""

    id: uuid.UUID
    client_id: str
    participant_name: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: list[str]
    resource: str | None
    expires_at: datetime


async def authorize(
    session: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    scopes: Sequence[str] | None,
    resource: str | None,
    policy: ConsentPolicy,
    now: datetime | None = None,
) -> str:
    """Согласует вход по политике и возвращает одноразовый код — единственный раз.

    Отказ политики уходит `OAuthRefusal` как есть. Код в базе — хешем, со сроком `CODE_TTL`.
    """
    moment = now or datetime.now(UTC)
    repository = OAuthRepository(session)
    client = await repository.get_client(client_id)
    if client is None:
        raise OAuthRefusal("unauthorized_client", "client is not registered")
    grant = await policy(session, client=_view(client), redirect_uri=redirect_uri)

    await repository.delete_codes_expired_before(moment - _CODE_RETENTION)
    secret = generate_oauth_secret(CODE_PREFIX)
    await repository.add(
        OAuthCode(
            code_hash=hash_token(secret),
            client=client,
            participant=grant.participant,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            scopes=list(scopes or [OAUTH_SCOPE]),
            resource=resource,
            expires_at=moment + CODE_TTL,
            **created_by_columns(grant.issuer),
        )
    )
    return secret


async def find_code(
    session: AsyncSession, *, client_id: str, code: str, now: datetime | None = None
) -> CodeView | None:
    """Код этого клиента, ещё не погашенный, или `None`.

    Повтор погашенного кода — признак перехвата: токен, выданный по нему, отзывается
    (RFC 6749 §10.5), а ответ тот же, что на неизвестный код. Чужой код — тоже `None`,
    не подтверждая, что он существует. Срок сверяет SDK по `expires_at`.
    """
    row = await OAuthRepository(session).get_code(hash_token(code))
    if row is None or row.client.client_id != client_id:
        return None
    if row.used_at is not None:
        if row.token_id is not None:
            await _revoke_token_id(session, row.token_id, now)
        return None
    return CodeView(
        id=row.id,
        client_id=row.client.client_id,
        participant_name=row.participant.name,
        code_challenge=row.code_challenge,
        redirect_uri=row.redirect_uri,
        redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
        scopes=list(row.scopes),
        resource=row.resource,
        expires_at=row.expires_at,
    )


@dataclass(frozen=True, slots=True)
class IssuedPair:
    """Выданный токен участника и refresh к нему — секреты существуют только здесь."""

    access_token: str
    refresh_token: str
    scopes: list[str]


async def redeem_code(
    session: AsyncSession, *, code_id: uuid.UUID, now: datetime | None = None
) -> IssuedPair:
    """Гасит код и выпускает по нему токен участника и refresh-токен.

    PKCE, адрес возврата и срок сверил SDK до вызова. Погашение атомарное: второй обмен
    того же кода, пришедший одновременно, получает `invalid_grant`.
    """
    moment = now or datetime.now(UTC)
    repository = OAuthRepository(session)
    if not await repository.claim_code(code_id, moment):
        raise OAuthRefusal("invalid_grant", "authorization code was already used")
    code = await session.get(OAuthCode, code_id)
    if code is None or code.expires_at <= moment:  # истёк между сверкой SDK и погашением
        raise OAuthRefusal("invalid_grant", "authorization code has expired")

    token, secret = await _issue(
        session, participant=code.participant, issuer=code.created_by, client=code.client
    )
    code.token_id = token.id
    refresh = await _add_refresh(
        session,
        client=code.client,
        token=token,
        family_id=uuid.uuid4(),
        scopes=code.scopes,
        resource=code.resource,
    )
    return IssuedPair(access_token=secret, refresh_token=refresh, scopes=list(code.scopes))


# --- Refresh -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefreshView:
    """Refresh-токен, каким его сверяет SDK: клиент и области."""

    id: uuid.UUID
    client_id: str
    participant_name: str | None
    scopes: list[str]
    resource: str | None


async def find_refresh(
    session: AsyncSession, *, client_id: str, refresh: str, now: datetime | None = None
) -> RefreshView | None:
    """Годный refresh-токен этого клиента или `None`.

    Негоден погашенный — его повтор отзывает всю цепочку (OAuth 2.1, §4.3.1) — и тот,
    чей токен отозван: отзыв в «Доступах» отрезает клиента целиком.
    """
    row = await OAuthRepository(session).get_refresh(hash_token(refresh))
    if row is None or row.client.client_id != client_id:
        return None
    if row.used_at is not None:
        await _revoke_family(session, row.family_id, now)
        return None
    if row.token.is_revoked:
        return None
    participant = row.token.participant
    return RefreshView(
        id=row.id,
        client_id=row.client.client_id,
        participant_name=None if participant is None else participant.name,
        scopes=list(row.scopes),
        resource=row.resource,
    )


async def rotate_refresh(
    session: AsyncSession,
    *,
    refresh_id: uuid.UUID,
    scopes: Sequence[str] | None = None,
    now: datetime | None = None,
) -> IssuedPair:
    """Меняет refresh-токен на новую пару: новый токен участника, новый refresh.

    Прежний refresh гасится, прежний токен отзывается — у клиента остаётся один живой
    доступ. Погашение атомарное, как у кода.
    """
    moment = now or datetime.now(UTC)
    if not await OAuthRepository(session).claim_refresh(refresh_id, moment):
        raise OAuthRefusal("invalid_grant", "refresh token was already used")
    previous = await session.get(OAuthRefreshToken, refresh_id)
    if previous is None or previous.token.is_revoked or previous.token.participant is None:
        raise OAuthRefusal("invalid_grant", "refresh token is no longer valid")

    token, secret = await _issue(
        session,
        participant=previous.token.participant,
        issuer=previous.token.created_by,
        client=previous.client,
    )
    previous.token.revoked_at = moment
    granted = list(scopes or previous.scopes)
    refresh = await _add_refresh(
        session,
        client=previous.client,
        token=token,
        family_id=previous.family_id,
        scopes=granted,
        resource=previous.resource,
    )
    return IssuedPair(access_token=secret, refresh_token=refresh, scopes=granted)


# --- Внутреннее --------------------------------------------------------------------


def _view(client: OAuthClient) -> ClientView:
    metadata = dict(client.client_metadata)
    name = metadata.get("client_name")
    return ClientView(
        client_id=client.client_id,
        client_name=name if isinstance(name, str) else None,
        metadata=metadata,
    )


async def _issuer_actor(session: AsyncSession, issuer: Author) -> Actor:
    """Под чьим именем выпускается токен: сам трекер или согласовавший человек.

    Выпуск идёт обычным `issue_token` и его правилами: человеку для выпуска нужна
    действующая учётная запись (`app/services/tokens.py`).
    """
    if issuer.kind is AuthorKind.TRACKER:
        return TRACKER_ACTOR
    participant = await ParticipantRepository(session).get_by_name(issuer.signature or "")
    return Actor(author=issuer, participant=participant)


async def _issue(
    session: AsyncSession, *, participant: Participant, issuer: Author, client: OAuthClient
) -> tuple[Token, str]:
    issued = await issue_token(
        session,
        actor=await _issuer_actor(session, issuer),
        name=oauth_token_name(_view(client).client_name, client.client_id),
        participant=participant,
    )
    return issued.token, issued.secret


async def _add_refresh(
    session: AsyncSession,
    *,
    client: OAuthClient,
    token: Token,
    family_id: uuid.UUID,
    scopes: Sequence[str],
    resource: str | None,
) -> str:
    secret = generate_oauth_secret(REFRESH_PREFIX)
    await OAuthRepository(session).add(
        OAuthRefreshToken(
            token_hash=hash_token(secret),
            client=client,
            token=token,
            family_id=family_id,
            scopes=list(scopes),
            resource=resource,
        )
    )
    return secret


async def _revoke_token_id(
    session: AsyncSession, token_id: uuid.UUID, now: datetime | None
) -> None:
    token = await session.get(Token, token_id)
    if token is not None and not token.is_revoked:
        token.revoked_at = now or datetime.now(UTC)


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime | None) -> None:
    moment = now or datetime.now(UTC)
    for row in await OAuthRepository(session).list_family(family_id):
        if row.used_at is None:
            row.used_at = moment
        if not row.token.is_revoked:
            row.token.revoked_at = moment
