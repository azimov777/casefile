"""Справочники: статусы, типы задач, резолюции.

Три таблицы одной формы, поэтому общая часть вынесена в примесь. Это редактируемые
данные, а не зашитый перечень: начальный набор создаётся миграцией такими же обычными
строками, какие потом заводит пользователь или агент.

Область действия задаётся полем `queue_id`: `NULL` — запись глобальная и доступна всем
очередям, заполненное — локальная и видна только своей очереди. Та же логика, что у
локальных полей задачи из задачи 04.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, text, true
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.domain.catalogs import MAX_CATALOG_KEY_LENGTH, StatusCategory, format_catalog_ref

if TYPE_CHECKING:
    from app.db.models.queue import Queue


class CatalogEntryMixin:
    """Общая часть записи справочника: ключ, название, область действия, активность.

    Отключение (`is_active = false`) — единственный способ убрать запись, которой
    пользовались: строка остаётся на месте, ссылки из истории изменений не портятся,
    но в конфигурации очереди её больше нет. Удалять можно только неиспользуемое.
    """

    key: Mapped[str] = mapped_column(String(MAX_CATALOG_KEY_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true(), nullable=False)

    @declared_attr
    def queue_id(cls) -> Mapped[uuid.UUID | None]:
        """Очередь-владелец или `NULL` для глобальной записи.

        `ondelete="CASCADE"`: удаление очереди уносит её локальные справочники — они
        вне очереди не имеют смысла. Глобальных записей это не касается.
        """
        return mapped_column(
            ForeignKey("queues.id", ondelete="CASCADE"),
            default=None,
            nullable=True,
        )

    @declared_attr
    def queue(cls) -> Mapped[Queue | None]:
        """Очередь-владелец, чтобы собрать ссылку `TRK.open`, не зная контекста.

        `foreign_keys` обязателен: между справочником и очередью два пути внешних
        ключей — этот и обратный `queues.default_status_id`. Без явного указания
        SQLAlchemy не может выбрать, по какому строить связь, и падает при настройке
        отображения.

        Загрузка `selectin`, а не `joined`: у глобальных записей `queue_id` пуст, и
        для них дополнительный запрос вообще не выполняется, а список локальных
        записей забирает свою очередь одним запросом на всю страницу.
        """
        return relationship(
            lazy="selectin",
            foreign_keys=lambda: [cls.queue_id],
        )

    @property
    def ref(self) -> str:
        """Ссылка на запись: `open` у глобальной, `TRK.open` у локальной.

        Живёт на модели, а не только в сценарии справочников, из-за направления
        зависимостей. Ссылка нужна ещё и сценарию событий (`app/services/events.py`),
        который собирает из неё полезную нагрузку, а импортировать оттуда
        `app/services/catalogs.py` нельзя: справочники зависят от `issue_usage`, тот —
        от событий, и получилось бы кольцо. Второй же реализации формата у проекта быть
        не должно — `catalogs.format_entry_ref` зовёт это свойство.

        Ключ очереди берётся из связи, а не из контекста вызова: контекст можно
        перепутать и отдать запись одной очереди под именем другой. У глобальной записи
        (`queue_id IS NULL`) обращения к базе не происходит вовсе.
        """
        return format_catalog_ref(
            self.key,
            queue_key=self.queue.key if self.queue_id is not None else None,
        )

    @declared_attr.directive
    def __table_args__(cls) -> tuple[Any, ...]:
        """Ключ уникален внутри своей области действия.

        `postgresql_nulls_not_distinct=True` — суть ограничения. По умолчанию
        PostgreSQL считает NULL-ы различными, и обычное ограничение на пару
        `(queue_id, key)` пропустило бы сколько угодно глобальных статусов `open`:
        у всех `queue_id IS NULL`, а значит, для базы они не дубликаты. С этим флагом
        NULL сравнивается как обычное значение, и одно ограничение закрывает оба
        случая — глобальную уникальность и уникальность внутри очереди.
        Флаг требует PostgreSQL 15+; проект на 17 в обоих контурах.
        """
        return (
            UniqueConstraint(
                "queue_id",
                "key",
                postgresql_nulls_not_distinct=True,
            ),
        )


class Status(CatalogEntryMixin, BaseModel):
    """Статус задачи: где она находится в процессе."""

    __tablename__ = "statuses"

    # Категория обязательна и не имеет значения по умолчанию сознательно: доски,
    # прогресс проектов и автоматика опираются на неё, а не на ключ и название.
    # Статус без категории был бы невидим для всех трёх механик.
    category: Mapped[StatusCategory] = mapped_column(
        string_enum(StatusCategory, name="status_category", length=16),
        nullable=False,
    )


class IssueType(CatalogEntryMixin, BaseModel):
    """Тип задачи: задача, баг, эпик и что угодно ещё, заведённое пользователем."""

    __tablename__ = "issue_types"

    # Иконка — свободная строка-идентификатор для фронтенда, а не путь и не картинка:
    # набор иконок принадлежит интерфейсу, бэкенд хранит только выбор пользователя.
    # Пустая строка вместо NULL: у поля нет осмысленного «значение отсутствует»,
    # а два способа сказать «иконки нет» неизбежно разъезжаются.
    icon: Mapped[str] = mapped_column(
        String(64),
        default="",
        server_default=text("''"),
        nullable=False,
    )


class Resolution(CatalogEntryMixin, BaseModel):
    """Резолюция: чем закончилась задача. Статус говорит «где», резолюция — «чем кончилось»."""

    __tablename__ = "resolutions"
