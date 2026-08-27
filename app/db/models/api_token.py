"""Токен доступа к API: одна и та же схема для человека, для агента и для MCP."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.actor import Actor
from app.domain.tokens import TOKEN_HASH_LENGTH


class ApiToken(BaseModel):
    """Секрет, по которому запрос находит своего актора.

    Полное значение токена в базе не хранится: есть только хеш, по нему же идёт поиск.
    Отзыв — это проставленная дата в `revoked_at`, а не удаление строки: запись
    остаётся видна в списке токенов, и понятно, чем именно ходили раньше.
    """

    __tablename__ = "api_tokens"

    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("actors.id", ondelete="CASCADE"),
        index=True,
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

    actor: Mapped[Actor] = relationship(
        back_populates="tokens",
        # Аутентификация всегда идёт от токена к актору, поэтому связь грузится сразу
        # одним запросом: иначе на каждый запрос к API приходилось бы два обращения к БД.
        lazy="joined",
        innerjoin=True,
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
