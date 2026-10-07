"""Обсуждение и привязка к нему задач (решение проекта `TRK#51`)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.discussions import (
    MAX_DISCUSSION_TITLE_LENGTH,
    DiscussionStatus,
    format_discussion_address,
)


class Discussion(BaseModel, CreatedByMixin):
    """Строка реестра обсуждений: переписка по одному узкому вопросу внутри проекта.

    Карточка короткая (`TRK#51`, п. 1): номер внутри проекта, название — сам вопрос одной
    строкой, статус и время закрытия. Описания нет — контекст в первой записи дела, а
    дело — записи `entries` с `discussion_id`. Задач обсуждение не содержит: они
    привязываются строками `discussion_tasks`.

    Удаления нет, проект и номер неизменяемы: адрес `TRK~7` стоит в ссылках записей.
    """

    __tablename__ = "discussions"
    __table_args__ = (
        # Номер уникален внутри проекта: им обсуждение адресуют (`TRK~7`), и тот же индекс
        # отвечает на поиск по адресу. Выдаёт номер репозиторий под блокировкой строки
        # проекта (`DiscussionRepository.next_number`), а не счётчик на проекте.
        UniqueConstraint("project_id", "number"),
    )

    # Без `ondelete`: проекты не удаляются, а если однажды — база откажет.
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(MAX_DISCUSSION_TITLE_LENGTH), nullable=False)
    status: Mapped[DiscussionStatus] = mapped_column(
        string_enum(DiscussionStatus, name="discussion_status", length=16),
        default=DiscussionStatus.OPEN,
        server_default=DiscussionStatus.OPEN.value,
        nullable=False,
    )
    # Время закрытия или `NULL` у открытого. Ставит его закрытие той же транзакцией, что
    # подшивает итог и запись `closed` (`app/services/discussions.py`).
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Ключ проекта — половина адреса, и адрес нужен почти каждому ответу, поэтому `joined`,
    # как у области.
    project: Mapped[Project] = relationship(lazy="joined")

    @property
    def address(self) -> str:
        """Адрес обсуждения: `TRK~7`. Им обсуждение называют везде."""
        return format_discussion_address(self.project.key, self.number)


class DiscussionTask(BaseModel, CreatedByMixin):
    """Привязка задачи к обсуждению: задача зависит от его итога (`TRK#51`, п. 3).

    Одна строка на пару, и пара уникальна: повтор — `discussion_task_exists`. Отвязка
    удаляет строку, а история остаётся записями `attached` и `detached` в делах обеих
    сторон — как у связей между задачами (`app/db/models/link.py`).
    """

    __tablename__ = "discussion_tasks"
    __table_args__ = (
        UniqueConstraint("discussion_id", "task_id"),
        # Обсуждения задачи — признаки её карточки, проверки входа в работу и закрытия, и
        # отбор списка по задаче: все идут от задачи, а уникальность начинается с
        # обсуждения.
        Index("ix_discussion_tasks_task_id", "task_id"),
    )

    discussion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discussions.id"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)

    # Задача нужна каждому чтению привязки — ключ, название и статус, — поэтому `joined`.
    task: Mapped[Task] = relationship(lazy="joined")
