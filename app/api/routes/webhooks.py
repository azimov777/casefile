"""Подписки вебхуков и журнал доставок.

Подписки здесь общие для установки, а не персональные, в отличие от инбокса: вебхук —
канал наружу, и адрес, заведённый одним администратором, обязан быть виден другому.

Порядок маршрутов в этом файле важен, и нарушать его нельзя. `GET /webhooks/deliveries`
объявлен **до** `GET /webhooks/{subscription_id}`: FastAPI сопоставляет пути в порядке
объявления, и при обратном порядке слово `deliveries` уехало бы в параметр пути,
не разобралось как UUID и превратилось бы в `422` вместо журнала. Порядок стережёт тест
`tests/test_webhooks_api.py`, а не только этот комментарий.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.webhooks import (
    WebhookDeliveryRead,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.webhooks import DeliveryStatus
from app.services import webhooks as service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SubscriptionIdPath = Annotated[uuid.UUID, Path(description="Webhook subscription UUID")]
DeliveryIdPath = Annotated[uuid.UUID, Path(description="Webhook delivery UUID")]
EnabledQuery = Annotated[
    bool | None,
    Query(description="Filter by state; omit to list every subscription"),
]
SubscriptionQuery = Annotated[
    uuid.UUID | None,
    Query(description="Only deliveries of this subscription"),
]
StatusQuery = Annotated[
    DeliveryStatus | None,
    Query(description="Only deliveries in this state"),
]
EventTypeQuery = Annotated[
    str | None,
    Query(description="Only deliveries built from this kind of event"),
]


@router.get("", summary="List webhook subscriptions")
async def list_webhook_subscriptions(
    session: SessionDep,
    current_actor: CurrentActorDep,
    is_enabled: EnabledQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[WebhookSubscriptionRead]:
    """Подписки установки. Секрета в выдаче нет — только маска, по которой их различают."""
    page = await service.list_subscriptions(
        session,
        initiator=current_actor,
        is_enabled=is_enabled,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[WebhookSubscriptionRead].of(
        [WebhookSubscriptionRead.of(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook subscription",
)
async def create_webhook_subscription(
    payload: WebhookSubscriptionCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WebhookSubscriptionCreated]:
    """Заводит подписку и **единственный раз** отдаёт её секрет.

    Секрет нужен получателю, чтобы проверять подпись. Повторить его API не сможет:
    дальше он живёт только в базе, а в остальных ответах на его месте маска. Потерянный
    секрет заменяется новым (`PATCH`), а не восстанавливается.
    """
    subscription = await service.create_subscription(
        session,
        initiator=current_actor,
        name=payload.name,
        url=payload.url,
        scope=payload.scope,
        scope_key=payload.scope_key,
        event_types=payload.event_types,
        secret=payload.secret,
        is_enabled=payload.is_enabled,
    )
    return DataResponse[WebhookSubscriptionCreated](
        data=WebhookSubscriptionCreated.of(subscription)
    )


@router.get("/deliveries", summary="List webhook deliveries")
async def list_webhook_deliveries(
    session: SessionDep,
    current_actor: CurrentActorDep,
    subscription: SubscriptionQuery = None,
    delivery_status: StatusQuery = None,
    event_type: EventTypeQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[WebhookDeliveryRead]:
    """Журнал доставок: что уходило, куда, с каким ответом и сколькими попытками.

    Объявлен до маршрута с параметром пути — иначе `deliveries` разбиралось бы как
    идентификатор подписки.
    """
    page = await service.list_deliveries(
        session,
        initiator=current_actor,
        subscription_id=subscription,
        status=delivery_status,
        event_type=event_type,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[WebhookDeliveryRead].of(
        [WebhookDeliveryRead.of(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/deliveries/{delivery_id}/retry",
    status_code=status.HTTP_201_CREATED,
    summary="Send a delivery again",
)
async def retry_webhook_delivery(
    delivery_id: DeliveryIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WebhookDeliveryRead]:
    """Ставит завершённую доставку заново — новой записью с новым идентификатором.

    Ответ `201`, а не `200`, потому что создаётся новая запись журнала, а старая
    остаётся нетронутой. Так и надо: идентификатор доставки лежит внутри тела и служит
    получателю признаком повтора, и отправка того же тела второй раз была бы им
    законно отброшена как дубль.

    Ожидающую доставку переотправить нельзя (`409`): она и так в очереди, а вторая
    постановка удвоила бы вызов у получателя. Выключенную подписку — тоже (`409`):
    сначала её чинят и включают.
    """
    delivery = await service.get_delivery(session, delivery_id, initiator=current_actor)
    created = await service.retry_delivery(session, delivery, initiator=current_actor)
    return DataResponse[WebhookDeliveryRead](data=WebhookDeliveryRead.of(created))


@router.get("/{subscription_id}", summary="Read a webhook subscription")
async def read_webhook_subscription(
    subscription_id: SubscriptionIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WebhookSubscriptionRead]:
    subscription = await service.get_subscription(
        session,
        subscription_id,
        initiator=current_actor,
    )
    return DataResponse[WebhookSubscriptionRead](data=WebhookSubscriptionRead.of(subscription))


@router.patch("/{subscription_id}", summary="Update a webhook subscription")
async def update_webhook_subscription(
    subscription_id: SubscriptionIdPath,
    payload: WebhookSubscriptionUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WebhookSubscriptionRead]:
    """Правит адрес, набор типов, секрет и включённость.

    Включение вручную снимает автоматическое отключение целиком: счётчик неудач
    обнуляется, отметка и причина стираются. Иначе подписка, включённая после починки
    адреса, погасла бы на первой же неудаче — счётчик остался бы на пороге.
    """
    subscription = await service.get_subscription(
        session,
        subscription_id,
        initiator=current_actor,
    )
    updated = await service.update_subscription(
        session,
        subscription,
        initiator=current_actor,
        url=payload.url,
        event_types=payload.event_types,
        secret=payload.secret,
        is_enabled=payload.is_enabled,
    )
    return DataResponse[WebhookSubscriptionRead](data=WebhookSubscriptionRead.of(updated))


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a webhook subscription",
)
async def delete_webhook_subscription(
    subscription_id: SubscriptionIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет подписку вместе с её журналом доставок.

    Нужен след — подписку выключают, а не удаляют: журнал описывает работу конкретного
    адреса и в отрыве от подписки отвечать ему не на что.
    """
    subscription = await service.get_subscription(
        session,
        subscription_id,
        initiator=current_actor,
    )
    await service.delete_subscription(session, subscription, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
