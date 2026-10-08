"""Участник: человек или постоянный агент. Тот, кого можно назвать по имени."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.domain.authors import Author, participant_author
from app.domain.participants import ParticipantKind


class Participant(BaseModel, CreatedByMixin):
    """Строка реестра участников.

    Реестр нужен ровно для двух вещей: адресовать вопрос и подписывать записи именем, а
    не меткой (TRK#75). Прав за участником не стоит никаких — их даёт только
    набор токена.

    Удаления нет: имя участника уже записано подписью в делах, и строка, исчезнувшая из
    реестра, превратила бы эти подписи в ссылки в никуда. Отключения тоже нет — токен
    отзывается, а участник остаётся адресуемым.
    """

    __tablename__ = "participants"

    kind: Mapped[ParticipantKind] = mapped_column(
        string_enum(ParticipantKind, name="participant_kind", length=16),
        nullable=False,
    )
    # Имя хранится уже канонизированным (нижний регистр), поэтому уникальность без учёта
    # регистра держит обычное `UNIQUE`, а не функциональный индекс по `lower(name)`.
    # Канонизацию делает домен (`validate_participant_name`) — до всякой записи.
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)

    # Хозяин агента: человек, чей это агент (TRK#73; TRK-475#14). У людей, у
    # общих агентов и у локальных `claude`/`codex` — NULL. Связь объектом подгружается
    # сразу: имя хозяина отдают и список участников, и bootstrap, а ленивая загрузка в
    # асинхронной сессии падает `MissingGreenlet`.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("participants.id"), nullable=True, default=None
    )
    # `join_depth=2`: связь самоссылочная, и без глубины жадная загрузка не идёт по ней,
    # когда участник сам приехал по связи другой сущности (`Token.participant`) — хозяина
    # у участника токена запроса тогда нет, и первый кадр агента с хозяином падает
    # `MissingGreenlet` при сборке ответа (`500`).
    owner: Mapped[Participant | None] = relationship(
        remote_side="Participant.id", lazy="joined", foreign_keys=[owner_id], join_depth=2
    )

    @property
    def owner_name(self) -> str | None:
        """Имя хозяина или `None`: так его отдаёт REST."""
        return self.owner.name if self.owner is not None else None

    @property
    def author(self) -> Author:
        """Подпись этого участника: род — его род, подпись — его имя.

        Свойство на модели, а не функция в сценарии: автора участника собирают и
        аутентификация, и тесты, и будущие записи дела, а сценарий, который умел бы это
        один, пришлось бы импортировать отовсюду — включая модули, от которых он сам
        зависит.
        """
        return participant_author(self.kind.value, self.name)
