"""Схемы инбокса и подписок.

Актор в ответах не фигурирует вовсе: и лента, и подписки принадлежат тому, чьим токеном
сделан запрос. Поле `actor` в ответе означало бы, что бывает и чужой инбокс, а его нет —
лента это рабочая очередь конкретного актора, и вычитать её со стороны значило бы
отмечать прочитанным то, чего адресат не видел.

Уведомление отдаёт и текст, и идентификаторы. Текст — человеку, идентификаторы
(`event_type`, `issue`, `details`) — агенту: по ним он решает, браться ли за задачу, не
разбирая строку, которую завтра перепишут.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.notification import Notification, Subscription
from app.domain.notifications import (
    MAX_TEXT_LENGTH,
    DeliveryChannel,
    SubscriptionScope,
)

ScopeKeyDescription = (
    "Key of the object the subscription follows: queue key for `queue`, project or "
    "portfolio key for `project`, issue key for `issue`. Must be empty for the role "
    "scopes (`author`, `assignee`, `follower`, `mention`, `member`) and for `all`"
)
EventTypesDescription = (
    "Event types this subscription reacts to. An empty list means every type; unknown "
    "types are rejected, because a typo would give a subscription that never fires"
)
OwnActionsDescription = (
    "Whether the actor is notified about changes they made themselves. Off by default: "
    "otherwise an agent that updated an issue immediately wakes itself up"
)


class NotificationRead(BaseModel):
    """Запись инбокса."""

    id: uuid.UUID
    event_type: str = Field(
        examples=["issue.status_changed"],
        description="Type of the event this notification was built from",
    )
    object_type: str = Field(examples=["issue"], description="Kind of the object involved")
    object_key: str = Field(examples=["TRK-123"], description="Key of the object involved")
    issue: str | None = Field(
        default=None,
        examples=["TRK-123"],
        description=(
            "Key of the issue the notification is about; null for project, board and "
            "bulk status transfer events, which have no single issue"
        ),
    )
    body: str = Field(
        examples=["TRK-123 status: TRK.open -> TRK.in_progress"],
        description="Ready text, composed when the notification was created and stored as is",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Identifiers for programmatic decisions: changed fields, status transition, "
            "assignee, mentioned actors. Shape depends on the event type"
        ),
    )
    count: int = Field(
        examples=[1],
        description=(
            "How many events were merged into this record. Repeats of the same event on "
            "the same object within the merge window grow this counter instead of adding rows"
        ),
    )
    is_read: bool
    created_at: datetime
    read_at: datetime | None = Field(
        default=None,
        description="When it was first marked as read; a repeated mark does not move it",
    )

    @classmethod
    def of(cls, notification: Notification) -> NotificationRead:
        return cls(
            id=notification.id,
            event_type=notification.event_type,
            object_type=notification.object_type,
            object_key=notification.object_key,
            issue=notification.issue_key,
            body=notification.body,
            details=dict(notification.details),
            count=notification.count,
            is_read=notification.is_read,
            created_at=notification.created_at,
            read_at=notification.read_at,
        )


class InboxWaitRead(BaseModel):
    """Итог ожидания новых уведомлений.

    Пустой список с `timed_out: true` — нормальный ответ, а не ошибка: по коду ответа
    отличить «ничего не пришло» от сбоя нельзя, он в обоих случаях успешный.
    """

    notifications: list[NotificationRead] = Field(default_factory=list)
    waited: float = Field(
        examples=[25.0],
        description="Seconds actually spent waiting",
    )
    timed_out: bool = Field(
        description="True when the wait ended by timeout with an empty inbox",
    )


class NotificationsReadRequest(BaseModel):
    """Отметка прочитанным.

    Пустое тело (или отсутствие `notifications`) означает «весь инбокс»: агент,
    разобравший ленту целиком, не должен перечислять полсотни идентификаторов, которые
    ему пришлось бы собрать отдельным запросом.
    """

    model_config = ConfigDict(extra="forbid")

    notifications: list[uuid.UUID] | None = Field(
        default=None,
        description="Ids to mark as read; omit or send null to mark the whole inbox",
    )


class NotificationsReadResult(BaseModel):
    """Сколько записей фактически отмечено.

    Ноль — не ошибка: уже прочитанные не пересчитываются, и повтор запроса отвечает
    нулём, ничего не ломая.
    """

    marked: int = Field(examples=[3], description="How many notifications changed state")


class SubscriptionRead(BaseModel):
    """Подписка в ответе."""

    id: uuid.UUID
    scope: SubscriptionScope
    scope_key: str | None = Field(default=None, description=ScopeKeyDescription)
    event_types: list[str] = Field(default_factory=list, description=EventTypesDescription)
    channel: DeliveryChannel
    is_enabled: bool = Field(
        description=(
            "A disabled subscription on a role scope is how an actor opts out of the "
            "default notifications: deleting it brings them back"
        )
    )
    notify_own_actions: bool = Field(description=OwnActionsDescription)
    created_at: datetime

    @classmethod
    def of(cls, subscription: Subscription) -> SubscriptionRead:
        return cls(
            id=subscription.id,
            scope=subscription.scope,
            scope_key=subscription.scope_key,
            event_types=list(subscription.event_types),
            channel=subscription.channel,
            is_enabled=subscription.is_enabled,
            notify_own_actions=subscription.notify_own_actions,
            created_at=subscription.created_at,
        )


class SubscriptionCreate(BaseModel):
    """Новая подписка текущего актора."""

    model_config = ConfigDict(extra="forbid")

    scope: SubscriptionScope = Field(
        description=(
            "What the actor follows. Role scopes already notify by default; a row is "
            "needed only to narrow them by event type or to switch them off"
        )
    )
    scope_key: str | None = Field(default=None, description=ScopeKeyDescription)
    event_types: list[str] = Field(default_factory=list, description=EventTypesDescription)
    channel: DeliveryChannel = DeliveryChannel.INBOX
    is_enabled: bool = True
    notify_own_actions: bool = Field(default=False, description=OwnActionsDescription)


class SubscriptionUpdate(BaseModel):
    """Правка подписки.

    Область и её ключ здесь отсутствуют намеренно: «подписка на очередь TRK» и
    «подписка на проект alpha» — разные подписки, а не одна с другим значением поля.
    Переезд области означал бы, что идентификатор подписки перестал что-либо значить.
    """

    model_config = ConfigDict(extra="forbid")

    event_types: list[str] | None = Field(default=None, description=EventTypesDescription)
    is_enabled: bool | None = None
    notify_own_actions: bool | None = Field(default=None, description=OwnActionsDescription)


#: Текст адресного уведомления ограничен тем же потолком, что и собранный из события:
#: инбокс читается страницами, и абзац в каждой записи съел бы контекст агента.
DirectBodyField = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]
