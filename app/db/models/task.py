"""Задача: центральная сущность трекера.

Поля фиксированы (`CONCEPT.md`, 3.3): название, описание, четыре текстовых раздела и
список проверок — колонки, а не реестр полей. Статус — перечисление, а не ссылка на
справочник: справочника статусов в базе нет.

Ключ задачи (`TRK-42`) неизменяем и не переиспользуется. Ключ и очередь — две колонки,
а не ключ, вычисляемый из очереди: на ключ ссылаются записи дела и внешние системы, и
он обязан пережить любую будущую правку принадлежности.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.db.models.queue import Queue
from app.domain.tasks import (
    INITIAL_STATUS,
    MAX_ASSIGNEE_LENGTH,
    MAX_TASK_KEY_LENGTH,
    MAX_TITLE_LENGTH,
    TaskPriority,
    TaskStatus,
)


class Task(BaseModel, CreatedByMixin):
    """Строка задачи.

    Внешний ключ на очередь без `ondelete`: очереди не удаляются, а если это однажды
    случится, база откажет, и задачи не исчезнут молча.

    Автор строки (`CreatedByMixin`) — тот, кто завёл задачу. Это не «исполнитель»:
    исполнитель — свободная строка, которую трекер не проверяет и не меняет сам.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        # «Задачи очереди в таком-то статусе» — основной запрос списка и назначателя.
        # Индекс начинается с очереди: по одному `queue_id` он работает тоже, обратное
        # неверно.
        Index("ix_tasks_queue_id_status", "queue_id", "status"),
        # «Что у этого исполнителя» — фильтр поиска и входящая агента.
        Index("ix_tasks_assignee", "assignee"),
        # Курсорная пагинация проекта идёт по паре `(created_at, id)`; без индекса
        # каждая страница означала бы сортировку всей таблицы.
        Index("ix_tasks_created_at_id", "created_at", "id"),
        # GIN по `tags`: фильтр `tags @> '["release"]'` — основной запрос поиска по
        # меткам, и без индекса он читал бы всю таблицу.
        Index("ix_tasks_tags", "tags", postgresql_using="gin"),
        # Версия только растёт и начинается с единицы: ноль означал бы, что счётчик
        # правили руками, и оптимистичная блокировка перестала бы ловить гонку.
        CheckConstraint("version >= 1", name="version_positive"),
    )

    key: Mapped[str] = mapped_column(String(MAX_TASK_KEY_LENGTH), unique=True, nullable=False)
    queue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("queues.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(MAX_TITLE_LENGTH), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Четыре текстовых раздела. Пустая строка вместо NULL: «раздела нет» и «раздел пуст»
    # — одно состояние, и два способа его записать разъехались бы у клиентов.
    goal: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    context: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    constraints: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    output: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    # Пятый раздел: упорядоченный список строк, нумерация с 1 по позиции. JSONB, а не
    # таблица: проверка не самостоятельный объект, на неё ссылаются номером внутри
    # задачи, и отдельная таблица дала бы соединение ради трёх строк.
    checks: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    status: Mapped[TaskStatus] = mapped_column(
        string_enum(TaskStatus, name="task_status", length=16),
        default=INITIAL_STATUS,
        server_default=text(f"'{INITIAL_STATUS.value}'"),
        nullable=False,
    )
    # Свободная строка: имя участника или метка. Внешнего ключа нет намеренно — у
    # временного агента строки в реестре нет (`CONCEPT.md`, 3.3).
    assignee: Mapped[str | None] = mapped_column(
        String(MAX_ASSIGNEE_LENGTH), default=None, nullable=True
    )
    # Плоский список строк в JSONB: тег — не объект, на него не ссылаются. Порядок
    # значим — он виден в карточке.
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        string_enum(TaskPriority, name="task_priority", length=16),
        default=TaskPriority.NORMAL,
        server_default=text(f"'{TaskPriority.NORMAL.value}'"),
        nullable=False,
    )

    # Версия для оптимистичной блокировки. Ведёт её SQLAlchemy (`version_id_col`):
    # каждый UPDATE строки идёт с условием `WHERE version = :seen` и поднимает
    # версию на единицу, а расхождение поднимает `StaleDataError`, которую сценарий
    # переводит в `version_conflict`. Так гонка двух правок ловится базой, а не только
    # сравнением в Python до записи.
    version: Mapped[int] = mapped_column(
        BigInteger,
        default=1,
        server_default=text("1"),
        nullable=False,
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "eager_defaults": True,
        "version_id_col": version,
    }

    # Ключ и название очереди входят в каждую карточку задачи, а очередь у задачи одна,
    # поэтому `joined`: одно соединение вместо второго запроса на каждый ответ.
    queue: Mapped[Queue] = relationship(lazy="joined")
