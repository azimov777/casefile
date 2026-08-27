"""Очередь: контейнер конфигурации процесса и владелец нумерации задач.

Очередь — не папка, а центральная единица настройки: свой набор типов задач, свои
значения по умолчанию, свои локальные справочники. Ключ очереди входит в ключ задачи
(`TRK-123`), поэтому после создания он не меняется.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Status
from app.domain.queues import MAX_QUEUE_KEY_LENGTH


class Queue(BaseModel):
    """Очередь задач.

    Внешние ключи на справочники объявлены без `ondelete`, то есть с поведением
    `NO ACTION`: удалить статус или тип, назначенный очереди по умолчанию, база не
    даст. Именно `NO ACTION`, а не `RESTRICT`: проверка `NO ACTION` откладывается до
    конца оператора, и потому удаление самой очереди проходит — её локальные
    справочники уносит каскад, а ссылка на них к моменту проверки уже исчезла.
    С `RESTRICT` тот же каскад падал бы на собственной очереди.
    """

    __tablename__ = "queues"
    __table_args__ = (
        UniqueConstraint("key"),
        # Счётчик только растёт. Отрицательное значение означало бы, что кто-то
        # правил его руками, и следующая же выданная нумерация налезла бы на выданные.
        CheckConstraint("last_issue_number >= 0", name="last_issue_number_non_negative"),
    )

    key: Mapped[str] = mapped_column(String(MAX_QUEUE_KEY_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Пустая строка вместо NULL: «описания нет» и «описание пустое» — одно и то же
    # состояние, а два способа его выразить дали бы разное поведение у клиентов.
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default=text("''"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    # Счётчик номеров задач. Выдача — единственным атомарным UPDATE ... RETURNING,
    # см. `QueueRepository.allocate_issue_number`. Хранится номер последней выданной
    # задачи, поэтому пустая очередь держит 0.
    last_issue_number: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    # `use_alter=True` — из-за кольца ссылок: очередь ссылается на свои справочники,
    # а локальные справочники — на свою очередь. Без него SQLAlchemy не может
    # упорядочить таблицы («unresolvable cycles») и молча выбрасывает внешние ключи
    # из сортировки, а миграция получается неприменимой. С флагом ключ создаётся
    # отдельным ALTER TABLE после обеих таблиц.
    default_issue_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issue_types.id", use_alter=True),
        nullable=False,
    )
    default_status_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statuses.id", use_alter=True),
        nullable=False,
    )

    is_archived: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(default=None)

    owner: Mapped[Actor] = relationship(lazy="joined", innerjoin=True)
    # `foreign_keys` обязателен: между очередью и справочником два пути внешних ключей
    # (этот и обратный `statuses.queue_id`), и выбрать между ними SQLAlchemy не может.
    default_issue_type: Mapped[IssueType] = relationship(
        lazy="joined",
        innerjoin=True,
        foreign_keys=[default_issue_type_id],
    )
    default_status: Mapped[Status] = relationship(
        lazy="joined",
        innerjoin=True,
        foreign_keys=[default_status_id],
    )

    @property
    def is_active(self) -> bool:
        """Очередь принимает новые задачи, пока не убрана в архив."""
        return not self.is_archived


class QueueIssueType(BaseModel):
    """Разрешённый в очереди тип задачи.

    Отдельная таблица связи, а не список ключей в очереди: в задаче 07 к паре
    «очередь + тип задачи» привяжется воркфлоу, и вешать его будет некуда, если связь
    останется неявной.

    Каскад по обоим ключам: удаление очереди уносит её привязки, удаление типа задачи —
    тоже. Второе безопасно, потому что тип, которым пользуются задачи или который
    назначен очереди по умолчанию, удалить и так нельзя.
    """

    __tablename__ = "queue_issue_types"
    __table_args__ = (UniqueConstraint("queue_id", "issue_type_id"),)

    queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issue_types.id", ondelete="CASCADE"),
        nullable=False,
    )

    issue_type: Mapped[IssueType] = relationship(lazy="joined", innerjoin=True)
