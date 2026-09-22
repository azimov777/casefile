"""Токен доступа: одна и та же схема для REST и для MCP."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.db.models.participant import Participant
from app.domain.tokens import TOKEN_HASH_LENGTH, TokenScope


class Token(BaseModel, CreatedByMixin):
    """Секрет, по которому запрос находит своего автора и свой набор прав.

    Полное значение токена в базе не хранится: есть только хеш, по нему же идёт поиск.
    Отзыв — это проставленная дата в `revoked_at`, а не удаление строки: запись
    остаётся видна в списке, и понятно, чем именно ходили раньше.

    `participant_id` пуст у **общего агентского** токена. Такой токен не называет автора
    сам — подпись приезжает заголовком `X-Actor-Label`, и без неё запрос отклоняется
    (`app/services/auth.py`). Это и есть разница между постоянным агентом и временным:
    первый адресуем по имени, второго можно только прочитать в подписи.
    """

    __tablename__ = "tokens"

    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    scope: Mapped[TokenScope] = mapped_column(
        string_enum(TokenScope, name="token_scope", length=16),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(TOKEN_HASH_LENGTH),
        unique=True,
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    # Срок есть только у токена сеанса браузера (`app/services/login.py`): вход по почте
    # и паролю выпускает его, и после срока он не пускает (`token_expired`). У остальных
    # токенов срока нет — их отзывают руками.
    expires_at: Mapped[datetime | None] = mapped_column(default=None)

    # Аутентификация всегда идёт от токена к участнику, поэтому связь грузится сразу
    # одним запросом: иначе на каждый запрос к API приходилось бы два обращения к БД.
    # `innerjoin` здесь запрещён — у общего агентского токена участника нет, и
    # внутреннее соединение просто не нашло бы такой токен.
    participant: Mapped[Participant | None] = relationship(lazy="joined")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_session(self) -> bool:
        """Токен сеанса браузера: выпущен входом по почте и паролю и живёт до срока."""
        return self.expires_at is not None

    def expired_at(self, moment: datetime) -> bool:
        """Истёк ли срок к этому моменту. Токен без срока не истекает никогда."""
        return self.expires_at is not None and self.expires_at <= moment

    @property
    def is_shared(self) -> bool:
        """Общий агентский токен: автора называет заголовок, а не сам токен."""
        return self.participant_id is None
