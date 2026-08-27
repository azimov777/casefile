"""Базовый класс моделей SQLAlchemy и общие для всех таблиц колонки."""

import enum
import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, Enum, MetaData, func, text
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

    # `eager_defaults` обязателен для всего проекта, и вот почему. `updated_at`
    # вычисляет база (`onupdate=func.now()`), поэтому после UPDATE SQLAlchemy считает
    # локальное значение устаревшим и помечает атрибут протухшим. Первое же обращение
    # к нему — например, при сборке ответа Pydantic — пытается сходить в базу за
    # свежим значением, а это происходит уже вне async-контекста: MissingGreenlet.
    # С этим флагом SQLAlchemy дописывает `RETURNING updated_at` в сам UPDATE, и
    # второго обращения не требуется. Для INSERT то же самое работает по умолчанию,
    # поэтому ошибка проявляется только на изменении и только в живом запуске.
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}


def string_enum(python_type: type[enum.Enum], *, name: str, length: int = 32) -> Enum:
    """Перечисление как VARCHAR с ограничением CHECK, а не как тип PostgreSQL.

    Так во всём проекте. Причина: native enum в PostgreSQL расширяется через
    `ALTER TYPE ... ADD VALUE`, и добавленное значение нельзя использовать в той же
    транзакции — миграция, которая заводит значение и тут же им пользуется, падает.
    Плюс каждый такой тип надо создавать и удалять в миграции руками, иначе
    `downgrade` оставляет за собой мусор.

    `VARCHAR` + `CHECK` даёт ту же целостность, расширяется заменой одного
    ограничения и в питоновском коде читается всё тем же enum — преобразованием
    занимается SQLAlchemy.

    `create_constraint=True` указывать обязательно: с версии 1.4 у SQLAlchemy это
    значение по умолчанию — `False`, и без него `native_enum=False` даёт голый VARCHAR
    вообще без проверки. Схема при этом выглядит правильной, а в колонку записывается
    любая строка.

    `values_callable` заставляет хранить значение (`"human"`), а не имя члена
    (`"HUMAN"`): по умолчанию SQLAlchemy пишет имя, и в базе оказывается регистр,
    которого нет ни в API, ни в коде.
    """
    return Enum(
        python_type,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
