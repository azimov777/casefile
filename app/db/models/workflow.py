"""Воркфлоу очереди: упорядоченные статусы и разрешённые переходы между ними."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.catalog import Status
from app.db.models.queue import Queue
from app.domain.workflows import MAX_TRANSITION_NAME_LENGTH, MAX_WORKFLOW_NAME_LENGTH


class Workflow(BaseModel):
    """Именованный процесс внутри одной очереди.

    Назначение типам задач хранится на существующей `QueueIssueType`, а не в третьей
    таблице связи. Один процесс можно разделить между несколькими типами одной очереди;
    смена назначения не копирует граф и потому остаётся явной дешёвой операцией.
    """

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("queue_id", "name"),
        # Нужен составному FK на `queue_issue_types`: один только `workflow_id`
        # позволил бы на уровне БД назначить процесс чужой очереди.
        UniqueConstraint("id", "queue_id"),
    )

    queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(MAX_WORKFLOW_NAME_LENGTH), nullable=False)
    initial_status_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statuses.id"),
        nullable=False,
    )

    queue: Mapped[Queue] = relationship(lazy="joined", innerjoin=True)
    initial_status: Mapped[Status] = relationship(lazy="joined", innerjoin=True)
    status_links: Mapped[list[WorkflowStatus]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: (WorkflowStatus.position, WorkflowStatus.id),
    )
    transitions: Mapped[list[Transition]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: (Transition.position, Transition.id),
    )


class WorkflowStatus(BaseModel):
    """Членство статуса в графе и стабильный порядок узлов в API."""

    __tablename__ = "workflow_statuses"
    __table_args__ = (
        UniqueConstraint("workflow_id", "status_id"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_workflow_statuses_status_id", "status_id"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("statuses.id"), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    workflow: Mapped[Workflow] = relationship(back_populates="status_links")
    status: Mapped[Status] = relationship(lazy="joined", innerjoin=True)


class Transition(BaseModel):
    """Одно именованное ребро графа.

    `from_status_id IS NULL` означает переход «из любого статуса». Требуемые поля
    хранятся ссылками в JSONB: системное имя (`assignee`) либо ссылка кастомного поля
    (`severity`, `TRK.severity`). Значения в задаче остаются в своём владельце.
    """

    __tablename__ = "transitions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "from_status_id",
            "to_status_id",
            "name",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_transitions_to_status_id", "to_status_id"),
        Index("ix_transitions_from_status_id", "from_status_id"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("statuses.id"),
        default=None,
        nullable=True,
    )
    to_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("statuses.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_TRANSITION_NAME_LENGTH), nullable=False)
    required_fields: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    requires_resolution: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    workflow: Mapped[Workflow] = relationship(back_populates="transitions")
    from_status: Mapped[Status | None] = relationship(
        lazy="joined",
        foreign_keys=[from_status_id],
    )
    to_status: Mapped[Status] = relationship(
        lazy="joined",
        innerjoin=True,
        foreign_keys=[to_status_id],
    )

    @property
    def required_field_names(self) -> tuple[str, ...]:
        """Неизменяемый вид JSON-массива для доменного валидатора."""
        return tuple(self.required_fields)
