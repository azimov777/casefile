"""Клиент OAuth, код авторизации и refresh-токен: путь к обычному токену участника.

Сам доступ — строка `tokens` (`app/db/models/token.py`); здесь только то, что к ней
ведёт. Все три таблицы переживают перезапуск службы mcp: клиент, вошедший вчера,
обновляет токен сегодня, не регистрируясь заново (TRK-448).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.author import CreatedByMixin
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.domain.tokens import TOKEN_HASH_LENGTH


class OAuthClient(BaseModel):
    """Клиент, зарегистрированный динамически (RFC 7591): его метаданные как прислал.

    `client_id` — текст, а не UUID: SDK выдаёт UUID строкой, а клиент по документу
    метаданных (CIMD, TRK-449) называет себя URL. Метаданные лежат JSONB целиком — это
    ответ регистрации, который клиенту обещано вернуть без потерь (RFC 7591 §3.2.1), и
    разбирает их SDK, а не база. Секрета у клиента нет: все клиенты публичные
    (`app/services/oauth.py`).
    """

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    client_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class OAuthCode(BaseModel, CreatedByMixin):
    """Одноразовый код авторизации: кому выдан, под какой PKCE-вызов и куда вернуть.

    Хранится хеш кода. `used_at` проставляется атомарно при обмене, а не удалением
    строки: повтор погашенного кода — признак перехвата, и строка нужна, чтобы отозвать
    выданный по нему токен (`token_id`, RFC 6749 §10.5).

    Автор строки (`CreatedByMixin`) — тот, кто согласовал выдачу; он же станет автором
    выпуска токена. Участник — тот, от чьего имени токен будет говорить.
    """

    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(default=None)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tokens.id", ondelete="SET NULL"), default=None
    )

    client: Mapped[OAuthClient] = relationship(lazy="joined", innerjoin=True)
    participant: Mapped[Participant] = relationship(lazy="joined", innerjoin=True)


class OAuthRefreshToken(BaseModel):
    """Refresh-токен: хеш, токен участника, который он обновляет, и цепочка ротаций.

    Годен, пока не погашен (`used_at`) и пока не отозван его токен (`token_id`): отзыв
    в «Доступах» отрезает клиента целиком, и обновиться втихую он не может. Каждый обмен
    гасит этот refresh и заводит следующий в той же цепочке (`family_id`); повтор
    погашенного отзывает цепочку целиком — это признак кражи (OAuth 2.1, §4.3.1).
    """

    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), index=True, nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text, default=None)
    used_at: Mapped[datetime | None] = mapped_column(default=None)

    client: Mapped[OAuthClient] = relationship(lazy="joined", innerjoin=True)
    token: Mapped[Token] = relationship(lazy="joined", innerjoin=True)
