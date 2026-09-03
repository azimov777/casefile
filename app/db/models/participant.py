"""Участник: человек или постоянный агент. Тот, кого можно назвать по имени."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.domain.authors import Author, participant_author
from app.domain.participants import ParticipantKind


class Participant(BaseModel, CreatedByMixin):
    """Строка реестра участников.

    Реестр нужен ровно для двух вещей: адресовать вопрос и подписывать записи именем, а
    не меткой (`CONCEPT.md`, 3.1). Прав за участником не стоит никаких — их даёт только
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

    @property
    def author(self) -> Author:
        """Подпись этого участника: род — его род, подпись — его имя.

        Свойство на модели, а не функция в сценарии: автора участника собирают и
        аутентификация, и тесты, и будущие записи дела, а сценарий, который умел бы это
        один, пришлось бы импортировать отовсюду — включая модули, от которых он сам
        зависит.
        """
        return participant_author(self.kind.value, self.name)
