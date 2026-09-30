"""Токен доступа: одна и та же схема для REST и для MCP."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.db.models.participant import Participant
from app.domain.tokens import TOKEN_HASH_LENGTH, TokenKind


class Token(BaseModel, CreatedByMixin):
    """Секрет, по которому запрос находит своего автора .

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(TOKEN_HASH_LENGTH),
        unique=True,
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    # Срок есть у сеанса браузера (`app/services/login.py`) и у подключения OAuth
    # (`app/services/oauth.py`): после него токен не пускает (`token_expired`). У ключей
    # и у `local-ui` срока нет — их отзывают руками. Вид строки задаёт `kind`, а не срок.
    expires_at: Mapped[datetime | None] = mapped_column(default=None)
    # Вид строки доступа (`TokenKind`): сеанс, ключ или подключение. Задаётся при выпуске
    # и больше не меняется; умолчания нет намеренно — каждая дверь выпуска называет свой.
    kind: Mapped[TokenKind] = mapped_column(
        string_enum(TokenKind, name="token_kind", length=16),
        nullable=False,
    )

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
        """Вход человека в интерфейс: сеанс браузера или ключ машины `local-ui`.

        Сеанс браузера среди них — тот, у кого есть срок (`app/services/login.py`).
        """
        return self.kind is TokenKind.SESSION

    @property
    def is_browser_session(self) -> bool:
        """Сеанс браузера: вход по почте и паролю, вид `session` со сроком.

        Второй вход того же вида — ключ машины `local-ui` — срока не имеет, и кукой входа
        он не бывает (`app/services/login.py`).
        """
        return self.is_session and self.expires_at is not None

    def expired_at(self, moment: datetime) -> bool:
        """Истёк ли срок к этому моменту. Токен без срока не истекает никогда."""
        return self.expires_at is not None and self.expires_at <= moment

    @property
    def is_shared(self) -> bool:
        """Общий агентский токен: автора называет заголовок, а не сам токен."""
        return self.participant_id is None

    def belongs_to(self, participant: Participant) -> bool:
        """Свой ли это токен участника: говорит от его имени или выпущен им.

        Тот же предикат на стороне базы — `owned_by` в `app/db/repositories/tokens.py`;
        расходиться им нельзя (`docs/CONCEPT.md`, 3.1; решение `TRK-114#12`). Автор
        выпуска сверяется целиком — родом и подписью: имя участника неизменяемо, а род
        `human` у автора бывает только у участника, поэтому метка временного агента с тем
        же текстом за человека не сойдёт.
        """
        return self.participant_id == participant.id or self.created_by == participant.author
