"""Базовый класс моделей SQLAlchemy и общие для всех таблиц колонки."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Явные шаблоны имён индексов и ограничений. Без них Alembic генерирует имена сам,
# по-разному для одинаковых по смыслу ограничений, и миграции становится нельзя
# откатывать вслепую: имя, которое нужно удалить, придётся искать в базе.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Общий декларативный базовый класс: реестр таблиц и правила отображения типов."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Аннотация типа в модели однозначно задаёт колонку: `dict[str, Any]` — это JSONB
    # (кастомные поля задачи), `datetime` — всегда с таймзоной, как требуют соглашения.
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        datetime: DateTime(timezone=True),
    }

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


class UUIDPrimaryKeyMixin:
    """Первичный ключ UUID.

    `default` считается на стороне Python, до flush: сценарию нужен id объекта ещё
    внутри транзакции — чтобы сослаться на него из записи журнала и события outbox.
    `server_default` подстраховывает вставки из чистого SQL, в том числе в миграциях.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampsMixin:
    """Отметки времени создания и последнего изменения; время ставит база, не приложение."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BaseModel(UUIDPrimaryKeyMixin, TimestampsMixin, Base):
    """Базовый класс таблиц проекта: `id`, `created_at`, `updated_at` из соглашений."""

    __abstract__ = True
