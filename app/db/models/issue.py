"""Задача и её наблюдатели: центральная сущность трекера.

Системные поля — отдельные колонки, кастомные — в `values JSONB` (`docs/CONCEPT.md`).
Формат хранения значений зафиксирован в `app/domain/fields.py`, а не выводится из этой
таблицы: те же байты читают журнал изменений, поиск и автоматика.

Ключ задачи (`TRK-123`) неизменяем — в том числе если задачу однажды научатся
переносить между очередями. Поэтому ключ и очередь — две независимые колонки, а не
ключ, вычисляемый из очереди: перенос поменяет `queue_id` и не тронет `key`, и все
внешние ссылки на задачу останутся верными.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.queue import Queue
from app.domain.issues import IssuePriority
from app.domain.queues import MAX_ISSUE_KEY_LENGTH


class Issue(BaseModel):
    """Задача.

    Внешние ключи на очередь, справочники и акторов объявлены без `ondelete`, то есть с
    поведением `NO ACTION`: удалить очередь, статус или актора, на которых стоят задачи,
    база не даст. Это вторая линия обороны — первую держат сценарии
    (`queue_not_empty`, `status_in_use`), и они дают клиенту понятную ошибку вместо
    нарушения ограничения.

    Все связи загружаются стратегией `selectin`, а не `joined`. Причина в количестве:
    у задачи семь связанных объектов, и `joined` собрал бы страницу из пятидесяти задач
    одним запросом с двумя десятками соединений — очередь тянет за собой владельца и
    свои значения по умолчанию, а те — свои очереди. `selectin` даёт семь коротких
    запросов на страницу любого размера и переиспользует уже загруженные справочники.
    """

    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("key"),
        # Фильтрация «задачи очереди в таком-то статусе» — основной запрос досок и
        # списков, поэтому индекс составной и начинается с очереди: по одному
        # `queue_id` он работает тоже, обратное неверно.
        Index("ix_issues_queue_id_status_id", "queue_id", "status_id"),
        Index("ix_issues_assignee_id", "assignee_id"),
        Index("ix_issues_deadline", "deadline"),
        # Курсорная пагинация во всём проекте идёт по паре `(created_at, id)`. На
        # справочниках это не имело значения, на таблице задач — уже имеет: без
        # индекса каждая страница означала бы сортировку всей таблицы.
        Index("ix_issues_created_at_id", "created_at", "id"),
        # GIN по `values`: под него ложатся и `values ? :ref` (есть ли значение поля),
        # и `values @> :fragment` (равно ли значение) — на них держатся защита реестра
        # полей и поиск по кастомным полям. Сравнения диапазонов по JSONB этот индекс
        # не покрывает: `jsonb_ops` знает только про вхождение и наличие ключа.
        Index("ix_issues_values", "values", postgresql_using="gin"),
        # GIN по `tags`: фильтр `tags @> '["release"]'` — основной запрос поиска по
        # меткам. Без индекса он означал бы чтение всей таблицы, а метки стоят почти
        # на каждой задаче.
        Index("ix_issues_tags", "tags", postgresql_using="gin"),
        # Триграммные индексы под полнотекстовый поиск: `ILIKE '%...%'` не ложится ни
        # на один обычный индекс, потому что шаблон начинается с подстановки. GIN с
        # `gin_trgm_ops` покрывает именно этот случай — ценой размера индекса и
        # бесполезности на запросах короче трёх символов.
        Index(
            "ix_issues_summary_trgm",
            "summary",
            postgresql_using="gin",
            postgresql_ops={"summary": "gin_trgm_ops"},
        ),
        Index(
            "ix_issues_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        # Версия только растёт и начинается с единицы. Ноль или отрицательное значение
        # означали бы, что счётчик правили руками, и оптимистичная блокировка
        # перестала бы ловить конкурентную запись.
        CheckConstraint("version >= 1", name="version_positive"),
    )

    key: Mapped[str] = mapped_column(String(MAX_ISSUE_KEY_LENGTH), nullable=False)

    queue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("queues.id"), nullable=False)
    issue_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issue_types.id"), nullable=False)
    status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("statuses.id"), nullable=False)
    # Резолюция появляется при закрытии и снимается при возврате в работу, поэтому
    # nullable: «ещё не закрыта» — законное состояние, а не отсутствие данных.
    resolution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resolutions.id"),
        default=None,
        nullable=True,
    )

    # Приоритет — колонка с перечислением, а не справочник: он одинаков во всех
    # очередях и процесс команды не описывает. См. `app/domain/issues.py`.
    priority: Mapped[IssuePriority] = mapped_column(
        string_enum(IssuePriority, name="issue_priority", length=16),
        default=IssuePriority.NORMAL,
        server_default=text(f"'{IssuePriority.NORMAL.value}'"),
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    # Пустая строка вместо NULL: «описания нет» и «описание пустое» — одно состояние,
    # и два способа его выразить дали бы разное поведение у клиентов. Так же устроено
    # описание очереди.
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default=text("''"),
        nullable=False,
    )

    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("actors.id"),
        default=None,
        nullable=True,
    )

    # Дедлайн — момент времени с зоной, а не дата: соглашения требуют ISO 8601 с
    # таймзоной для всех дат контракта, и язык запросов из задачи 12 сравнивает его
    # диапазонами. Дата без времени осталась кастомным полям — там тип `date` есть.
    deadline: Mapped[datetime | None] = mapped_column(default=None, nullable=True)

    # Теги — плоский список строк в JSONB, а не таблица: тег не самостоятельный
    # объект, на него никто не ссылается по идентификатору, и отдельная таблица дала
    # бы соединение ради списка из трёх слов. Порядок значим — он виден в карточке.
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    # Значения кастомных полей. Ключ — ссылка на поле (`severity`, `TRK.severity`),
    # формат значения по каждому типу описан в `app/domain/fields.py`. Колонка
    # называется `values`, и это слово зарезервировано в SQL: в ORM обращаться через
    # `Issue.values` можно, а в метаданных — только `table.c["values"]`, потому что
    # `table.c.values` вернёт метод коллекции колонок, а не колонку.
    values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    # Версия для оптимистичной блокировки: растёт на единицу при каждом фактическом
    # изменении. Клиент присылает ту, которую видел; расхождение — `version_conflict`.
    version: Mapped[int] = mapped_column(
        BigInteger,
        default=1,
        server_default=text("1"),
        nullable=False,
    )

    queue: Mapped[Queue] = relationship(lazy="selectin")
    issue_type: Mapped[IssueType] = relationship(lazy="selectin")
    status: Mapped[Status] = relationship(lazy="selectin")
    resolution: Mapped[Resolution | None] = relationship(lazy="selectin")
    author: Mapped[Actor] = relationship(lazy="selectin", foreign_keys=[author_id])
    # `foreign_keys` обязателен у обеих связей на акторов: путей внешних ключей между
    # задачей и актором два, и выбрать между ними SQLAlchemy не может.
    assignee: Mapped[Actor | None] = relationship(lazy="selectin", foreign_keys=[assignee_id])

    # Наблюдатели — набор, а не список: порядок ничего не значит, поэтому сортировка
    # задана по ключу актора и одинакова в любом ответе.
    followers: Mapped[list[Actor]] = relationship(
        secondary="issue_followers",
        lazy="selectin",
        order_by=Actor.key,
    )


class IssueFollower(BaseModel):
    """Наблюдатель задачи: тот, кому идут уведомления, но кто за неё не отвечает.

    Отдельная таблица, а не список ключей в JSONB: наблюдатель — существующий актор, и
    ссылка на него должна держаться внешним ключом. Иначе отключённый и удалённый
    актор оставил бы в задаче ссылку в никуда, а движок уведомлений из задачи 14
    узнал бы об этом в момент рассылки.

    Каскад по обоим ключам. По `issue_id` он очевиден: наблюдение без задачи ничего не
    значит. По `actor_id` он допустим потому, что актора не удаляют — его отключают
    (`is_active = false`), и история от этого не страдает.
    """

    __tablename__ = "issue_followers"
    __table_args__ = (
        UniqueConstraint("issue_id", "actor_id"),
        # Уникальное ограничение начинается с `issue_id` и обратный вопрос — «за
        # какими задачами следит этот актор» — не обслуживает. А он и есть основной
        # запрос инбокса из задачи 14, поэтому индекс отдельный.
        Index("ix_issue_followers_actor_id", "actor_id"),
    )

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("actors.id", ondelete="CASCADE"),
        nullable=False,
    )
