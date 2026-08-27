"""Актор: человек, агент или система. Инициатор любого действия в трекере."""

# Отложенные аннотации: `ApiToken` импортирован только для проверки типов — обратный
# импорт во время исполнения замкнул бы модели в цикл. SQLAlchemy разбирает такую
# аннотацию сам, находя класс по имени в своём реестре.
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.domain.actors import ActorType

if TYPE_CHECKING:
    from app.db.models.api_token import ApiToken


class Actor(BaseModel):
    """Тот, кому можно назначить задачу, приписать изменение и адресовать уведомление.

    Ролей в v1 нет: любой активный актор может всё, что позволяет единая точка проверки
    прав (`app/services/permissions.py`). Отключённый актор не проходит аутентификацию —
    это способ убрать агента, не удаляя его следы из истории изменений.
    """

    __tablename__ = "actors"

    type: Mapped[ActorType] = mapped_column(
        string_enum(ActorType, name="actor_type", length=16),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true(), nullable=False)

    tokens: Mapped[list[ApiToken]] = relationship(
        back_populates="actor",
        cascade="all, delete-orphan",
        # Ленивая загрузка коллекции в async-сессии падает с MissingGreenlet в самом
        # неудобном месте. `raise` превращает случайное обращение в понятную ошибку
        # сразу: нужен список токенов — грузи его явно через selectinload.
        lazy="raise",
        passive_deletes=True,
    )

    @property
    def is_system(self) -> bool:
        """Системный актор защищён от изменений через API."""
        return self.type is ActorType.SYSTEM
