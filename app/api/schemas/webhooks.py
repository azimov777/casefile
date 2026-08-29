"""Схемы подписок вебхуков и журнала доставок.

Главная особенность здесь одна: **секрет отдаётся ровно один раз** — в ответе на
создание подписки. Дальше он живёт только в базе и в подписи; в списке и в карточке
подписки на его месте маска. Причина простая: подписи проверяет получатель, и любой,
кто прочитал секрет, может подделать вызов от имени трекера.

Отсюда две модели ответа вместо одной. Схема с секретом — отдельный тип, а не поле
`secret: str | None` в общей: с необязательным полем сгенерированный клиент разрешал бы
фронтенду читать секрет там, где его никогда не бывает, и разница между «не пришёл» и
«не бывает» стёрлась бы.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.api.schemas.events import EventViewRead
from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.domain.webhooks import (
    MAX_NAME_LENGTH,
    MAX_SECRET_LENGTH,
    MAX_URL_LENGTH,
    MIN_SECRET_LENGTH,
    DeliveryStatus,
    WebhookScope,
    masked_secret,
)

ScopeKeyDescription = (
    "Key of the object the subscription follows: queue key for `queue`, project or "
    "portfolio key for `project`. Must be empty for `all`"
)
EventTypesDescription = (
    "Event types delivered to this address. An empty list means every type; unknown "
    "types are rejected, because a typo would give a subscription that never fires. "
    "Use `webhook.direct` to receive calls made by automation rules"
)
SecretDescription = (
    "Signing secret. Generated when omitted and returned once, in this response only: "
    "anyone who reads it can forge a call that looks like ours"
)
UrlDescription = (
    "Address receiving `POST` requests. Only `http` and `https`; redirects are not followed"
)

NameField = Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
UrlField = Annotated[
    str, Field(min_length=1, max_length=MAX_URL_LENGTH, description=UrlDescription)
]
SecretField = Annotated[
    str,
    Field(
        min_length=MIN_SECRET_LENGTH, max_length=MAX_SECRET_LENGTH, description=SecretDescription
    ),
]


class WebhookSubscriptionRead(BaseModel):
    """Подписка в ответе. Секрета здесь нет и не будет — только его маска."""

    id: uuid.UUID
    name: str = Field(
        examples=["release-bot"],
        description="Unique name; automation rules address the subscription by it",
    )
    url: str = Field(examples=["https://ci.example.com/hooks/tracker"], description=UrlDescription)
    scope: WebhookScope
    scope_key: str | None = Field(default=None, description=ScopeKeyDescription)
    event_types: list[str] = Field(default_factory=list, description=EventTypesDescription)
    is_enabled: bool = Field(
        description=(
            "Disabled subscriptions receive nothing. A subscription switched off by the "
            "server after repeated failures carries `disabled_at` and `disabled_reason`"
        )
    )
    secret_hint: str = Field(
        examples=["…a1b2"],
        description=(
            "Last characters of the secret: enough to tell two secrets apart during a "
            "rotation, not enough to sign with"
        ),
    )
    consecutive_failures: int = Field(
        examples=[0],
        description="Failed attempts in a row; any successful delivery resets it to zero",
    )
    disabled_at: datetime | None = Field(
        default=None,
        description="When the server switched the subscription off; null if a human did",
    )
    disabled_reason: str | None = Field(
        default=None,
        examples=["delivery_failures"],
        description="Why the server switched it off; null if a human did",
    )
    created_at: datetime

    @classmethod
    def of(cls, subscription: WebhookSubscription) -> WebhookSubscriptionRead:
        return cls(
            id=subscription.id,
            name=subscription.name,
            url=subscription.url,
            scope=subscription.scope,
            scope_key=subscription.scope_key,
            event_types=list(subscription.event_types),
            is_enabled=subscription.is_enabled,
            secret_hint=masked_secret(subscription.secret),
            consecutive_failures=subscription.consecutive_failures,
            disabled_at=subscription.disabled_at,
            disabled_reason=subscription.disabled_reason,
            created_at=subscription.created_at,
        )


class WebhookSubscriptionCreated(WebhookSubscriptionRead):
    """Только что созданная подписка — единственный ответ, несущий секрет.

    Отдельный тип, а не необязательное поле в общей схеме: клиент должен видеть по
    типу, что секрет бывает здесь и больше нигде.
    """

    secret: str = Field(description=SecretDescription)

    @classmethod
    def of(cls, subscription: WebhookSubscription) -> WebhookSubscriptionCreated:
        base = WebhookSubscriptionRead.of(subscription)
        return cls(**base.model_dump(), secret=subscription.secret)


class WebhookSubscriptionCreate(BaseModel):
    """Новая подписка."""

    model_config = ConfigDict(extra="forbid")

    name: NameField = Field(examples=["release-bot"])
    url: UrlField
    scope: WebhookScope = WebhookScope.ALL
    scope_key: str | None = Field(default=None, description=ScopeKeyDescription)
    event_types: list[str] = Field(default_factory=list, description=EventTypesDescription)
    secret: SecretField | None = Field(default=None, description=SecretDescription)
    is_enabled: bool = True


class WebhookSubscriptionUpdate(BaseModel):
    """Правка подписки.

    Области и её ключа здесь нет намеренно: «подписка на очередь TRK» и «подписка на
    проект alpha» — разные подписки, а не одна с другим значением поля. Переезд области
    означал бы, что идентификатор подписки перестал что-либо значить.

    Включение вручную снимает автоматическое отключение целиком — счётчик неудач
    обнуляется. Иначе подписка, включённая после починки адреса, погасла бы на первой
    же неудаче.

    Ни у адреса, ни у секрета, ни у набора типов нет осмысленного `null`, поэтому все
    поля объявлены не-nullable: передать `null` схема не даст. Молча отбросить его было
    бы хуже отказа — клиент получил бы `200` и уверенность, что поле изменено.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = unset_field(
        min_length=1,
        max_length=MAX_URL_LENGTH,
        description=UrlDescription,
    )
    event_types: list[str] = unset_field(description=EventTypesDescription)
    secret: str = unset_field(
        min_length=MIN_SECRET_LENGTH,
        max_length=MAX_SECRET_LENGTH,
        description="New signing secret. The response does not repeat it back",
    )
    is_enabled: bool = unset_field(
        description=(
            "Switching it back on clears the automatic shutdown: the failure counter, "
            "the timestamp and the reason are reset"
        ),
    )


class WebhookPayloadRead(EventViewRead):
    """Тело доставки: событие в общем виде плюс идентификатор самой доставки.

    `delivery` не совпадает с `event.id`: одно событие уходит на несколько адресов, и у
    каждой доставки свой идентификатор. Получатель отбрасывает по нему автоматические
    повторы; ручную переотправку он распознаёт по `event.id`, потому что она приходит
    новой доставкой с новым идентификатором — иначе добросовестный получатель отбросил
    бы её как дубль, и переотправка ничего бы не дала.
    """

    delivery: uuid.UUID = Field(description="Id of this delivery, unique per address")


class WebhookDeliveryRead(BaseModel):
    """Запись журнала доставок.

    Несёт и адрес, и код ответа, и число попыток — то есть всё, с чего начинается разбор
    «получатель не получил». Адрес здесь тот, по которому вызов уходил **тогда**: у
    подписки его могли с тех пор поменять.
    """

    id: uuid.UUID
    subscription: uuid.UUID = Field(description="Subscription this delivery belongs to")
    event: uuid.UUID | None = Field(
        default=None,
        description="Bus event the delivery was built from; null for automation rule calls",
    )
    event_type: str = Field(examples=["issue.status_changed"])
    object_type: str = Field(examples=["issue"])
    object_key: str = Field(examples=["TRK-123"])
    url: str = Field(description="Address the request went to at the time it was queued")
    status: DeliveryStatus
    attempts: int = Field(examples=[1], description="Attempts made so far")
    response_status: int | None = Field(
        default=None,
        examples=[200],
        description=(
            "HTTP status of the last attempt. Null means there was no response at all — "
            "timeout, refused connection, unresolved host"
        ),
    )
    last_error: str | None = Field(default=None, description="Why the last attempt failed")
    available_at: datetime = Field(description="When the next attempt may start")
    delivered_at: datetime | None = None
    created_at: datetime
    payload: WebhookPayloadRead = Field(
        description="Exact body that was sent, byte for byte the one covered by the signature",
    )

    @classmethod
    def of(cls, delivery: WebhookDelivery) -> WebhookDeliveryRead:
        return cls(
            id=delivery.id,
            subscription=delivery.subscription_id,
            event=delivery.event_id,
            event_type=delivery.event_type,
            object_type=delivery.object_type,
            object_key=delivery.object_key,
            url=delivery.url,
            status=delivery.status,
            attempts=delivery.attempts,
            response_status=delivery.response_status,
            last_error=delivery.last_error,
            available_at=delivery.available_at,
            delivered_at=delivery.delivered_at,
            created_at=delivery.created_at,
            payload=WebhookPayloadRead(**delivery.payload),
        )
