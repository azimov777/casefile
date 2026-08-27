"""Журнал изменений и outbox: две таблицы, на которых держатся аудит, автоматика и уведомления.

Обе заполняются **в той же транзакции**, что и само изменение (`app/services/events.py`).
Смысл именно в этом: событие обязано появиться тогда и только тогда, когда изменение
зафиксировано. Прямая рассылка из обработчика запроса дала бы уведомление об изменении,
которого не случилось, — и это не гипотетическая проблема, а первое, что ломается.

## Почему у события нет внешнего ключа на задачу

`OutboxEvent` адресует объект парой «тип + идентификатор», а не ссылкой. Внешний ключ
здесь невозможен: событие `issue.deleted` обязано пережить саму задачу, а `ON DELETE
CASCADE` унёс бы вместе с задачей ровно то событие, ради которого подписчик и нужен.
У `ChangelogEntry` ключ, наоборот, есть и с каскадом: история удалённой задачи не имеет
ни владельца, ни способа её прочитать — эндпоинт истории адресуется ключом задачи.

## Время создания ставит clock_timestamp(), а не now()

Единственное отступление от `TimestampsMixin` во всём проекте, и оно намеренное.
`now()` — время начала транзакции, поэтому все записи одной транзакции получают одну
отметку, а сортировка по паре `(created_at, id)` вырождается в сортировку по случайным
UUID. Для справочников это косметика, для истории изменений и очереди событий — нет:
история задачи показывалась бы в произвольном порядке, а события уходили бы подписчику
не в том порядке, в каком происходили. `clock_timestamp()` идёт вперёд внутри
транзакции и обе сортировки чинит.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.actor import Actor
from app.domain.events import OutboxStatus

#: Потолок длины типа события и типа объекта. Тип события — строка, а не перечисление
#: с проверкой значений: словарь открытый и растёт почти каждой задачей, см.
#: `app/domain/events.py`, `EventType`.
MAX_EVENT_TYPE_LENGTH = 64
MAX_OBJECT_TYPE_LENGTH = 32

#: Ключ объекта в событии: у задачи это `TRK-123`, у статуса — ссылка `TRK.open`.
MAX_OBJECT_KEY_LENGTH = 128

#: Совпадает с длиной ключа в таблице акторов.
MAX_ACTOR_KEY_LENGTH = 64


class ChangelogEntry(BaseModel):
    """Запись истории изменений задачи: кто, когда, что и с какого значения на какое.

    `changes` хранит список `{"field", "before", "after"}` — уже в JSON-виде, каким его
    отдаёт единая точка применения изменений: ссылка справочника строкой, актор ключом,
    время строкой ISO 8601. Именно поэтому переименование или удаление статуса не
    ломает историю задним числом: в записи лежит ссылка на момент события, а не
    указатель на строку справочника, которая может исчезнуть.

    Пустой `changes` законен ровно у одного типа записи — `issue.created`: у создания
    нет «было», а состояние созданной задачи целиком уезжает в полезную нагрузку
    события. Заполнять его псевдоизменениями «было пусто, стало значение» по каждому
    полю значило бы удваивать карточку задачи в её же истории.
    """

    __tablename__ = "changelog_entries"
    __table_args__ = (
        # Основной и единственный запрос: история одной задачи страницами. Порядок
        # колонок повторяет `WHERE issue_id = ? ORDER BY created_at, id` — курсорная
        # пагинация проекта идёт по паре `(created_at, id)`.
        Index("ix_changelog_entries_issue_id_created_at_id", "issue_id", "created_at", "id"),
        # «Что делал этот актор» — запрос аудита; отдельный индекс, потому что
        # предыдущий начинается с задачи и на этот вопрос не отвечает.
        Index("ix_changelog_entries_actor_id", "actor_id"),
    )

    # `ondelete="CASCADE"`: задача удаляется насовсем, и её история вместе с ней.
    # Выглядит как потеря аудита, но это не так: факт удаления остаётся событием
    # `issue.deleted` в outbox, у которого ссылки на задачу нет и который переживает её.
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Без `ondelete`: акторов не удаляют, их отключают, — и запись истории обязана
    # остаться читаемой даже после отключения агента.
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    event_type: Mapped[str] = mapped_column(String(MAX_EVENT_TYPE_LENGTH), nullable=False)

    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    # Отметка времени идёт вперёд внутри транзакции: см. шапку модуля.
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    # Ключ актора нужен каждой странице истории, а `selectin` берёт всех акторов
    # страницы одним запросом и переиспользует уже загруженных.
    actor: Mapped[Actor] = relationship(lazy="selectin")


class OutboxEvent(BaseModel):
    """Событие, ждущее рассылки подписчикам.

    Полезная нагрузка самодостаточна: в ней и состояние объекта после изменения, и
    список «было → стало». Подписчику не нужно лезть в базу за контекстом — и не нужно
    не из экономии: пока событие лежит в очереди, задача успевает измениться дальше, и
    поход в базу вернул бы не то состояние, о котором событие.

    Доставка отслеживается по каждому подписчику отдельно (`delivered_to`). Иначе
    повтор после падения одного подписчика заново дёрнул бы всех остальных, и
    автоматика отработала бы дважды из-за упавшего вебхука.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        # Выборка воркера целиком: «необработанные, которым пришло время», в порядке
        # появления. Все три колонки участвуют в одном запросе.
        Index(
            "ix_outbox_events_status_available_at_created_at",
            "status",
            "available_at",
            "created_at",
        ),
        Index("ix_outbox_events_object_type_object_id", "object_type", "object_id"),
        Index("ix_outbox_events_event_type", "event_type"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
    )

    event_type: Mapped[str] = mapped_column(String(MAX_EVENT_TYPE_LENGTH), nullable=False)

    # Пара «тип + идентификатор» вместо внешнего ключа: см. шапку модуля.
    object_type: Mapped[str] = mapped_column(String(MAX_OBJECT_TYPE_LENGTH), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    object_key: Mapped[str] = mapped_column(String(MAX_OBJECT_KEY_LENGTH), nullable=False)

    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)
    # Ключ актора рядом с идентификатором — по той же причине, что и `object_key` рядом
    # с `object_id`: воркер читает событие в транзакции с заблокированной строкой, и
    # каждое соединение ради одной строки там лишнее. Ключ актора неизменяем
    # (`app/services/actors.py` его не правит), поэтому копия не разъедется с оригиналом.
    actor_key: Mapped[str] = mapped_column(String(MAX_ACTOR_KEY_LENGTH), nullable=False)

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    status: Mapped[OutboxStatus] = mapped_column(
        string_enum(OutboxStatus, name="outbox_status", length=16),
        default=OutboxStatus.PENDING,
        server_default=text(f"'{OutboxStatus.PENDING.value}'"),
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    # Имена подписчиков, уже отработавших по этому событию. Повтор идёт только по
    # оставшимся: подписчик, сделавший свою работу, не должен делать её второй раз
    # из-за соседа, который упал.
    delivered_to: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    # Когда событие можно брать в работу. У нового — сразу, у повторяемого — после
    # нарастающей паузы.
    available_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    # Последняя ошибка с именем подписчика: без имени по тексту исключения не понять,
    # чей обработчик упал, а именно это и нужно знать первым.
    last_error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )
