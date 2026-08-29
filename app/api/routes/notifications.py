"""Инбокс актора и его подписки.

Всё здесь работает с актором, чьим токеном сделан запрос. Параметра «чей инбокс» нет и
не будет: лента — это рабочая очередь конкретного актора, и вычитать её со стороны
значило бы отмечать прочитанным то, чего адресат не видел.

Маршрута `GET /notifications/{id}` тут нет намеренно, и заводить его нельзя: он забрал
бы себе путь `/notifications/subscriptions`, разбирая `subscriptions` как идентификатор.
Порядок подключения роутеров от этого не спасает — он зависит от порядка строк в
`app/api/router.py`. Одно уведомление всё равно незачем читать по адресу: его отдают
лента и ожидание.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.notifications import (
    InboxWaitRead,
    NotificationRead,
    NotificationsReadRequest,
    NotificationsReadResult,
    SubscriptionCreate,
    SubscriptionRead,
    SubscriptionUpdate,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import issues as issues_service
from app.services import notifications as service

router = APIRouter(prefix="/notifications", tags=["notifications"])

SubscriptionIdPath = Annotated[uuid.UUID, Path(description="Subscription UUID")]
UnreadQuery = Annotated[
    bool | None,
    Query(description="Filter by read state; omit to get the whole history"),
]
IssueQuery = Annotated[
    str | None,
    Query(description="Issue key: only notifications about this issue"),
]
EventTypeQuery = Annotated[
    str | None,
    Query(description="Event type: only notifications built from this kind of event"),
]
TimeoutQuery = Annotated[
    float | None,
    Query(
        gt=0,
        description=(
            "Seconds to block waiting for new notifications. Bounded from above by the "
            "installation setting; a value beyond it is an error, not a silent clamp"
        ),
    ),
]


@router.get("", summary="List inbox notifications")
async def list_notifications(
    session: SessionDep,
    current_actor: CurrentActorDep,
    is_read: UnreadQuery = None,
    issue: IssueQuery = None,
    event_type: EventTypeQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[NotificationRead]:
    """Лента текущего актора, от старого к новому.

    Порядок хронологический, а не «новые сверху»: агент разбирает очередь подряд и
    отмечает прочитанным то, что обработал.
    """
    page = await service.list_notifications(
        session,
        initiator=current_actor,
        is_read=is_read,
        issue=None if issue is None else await issues_service.get_issue_by_key(session, issue),
        event_type=event_type,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[NotificationRead].of(
        [NotificationRead.of(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("/read", summary="Mark notifications as read")
async def mark_notifications_read(
    payload: NotificationsReadRequest,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[NotificationsReadResult]:
    """Отмечает прочитанными перечисленные уведомления или весь инбокс.

    `POST`, а не `PATCH` по каждому уведомлению: отметка обычно накрывает страницу
    целиком, и полсотни запросов ради неё были бы дороже самой работы. Повтор
    отвечает `marked: 0` и ошибкой не считается — уже прочитанные не пересчитываются.
    """
    marked = await service.mark_read(
        session,
        initiator=current_actor,
        notification_ids=payload.notifications,
    )
    return DataResponse[NotificationsReadResult](data=NotificationsReadResult(marked=marked))


@router.get("/wait", summary="Wait for new notifications")
async def wait_for_notifications(
    session: SessionDep,
    current_actor: CurrentActorDep,
    timeout: TimeoutQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
) -> DataResponse[InboxWaitRead]:
    """Блокируется до появления непрочитанных уведомлений или до истечения таймаута.

    Основа инструмента ожидания в MCP. Возвращает управление сразу, как только
    уведомление появилось: оповещение идёт средствами PostgreSQL, а редкий контрольный
    опрос страхует от потерянного сигнала (`app/db/wakeup.py`).

    Пустой ответ с `timed_out: true` — нормальный исход, а не ошибка. Соединение с
    базой на время ожидания не удерживается: транзакция закрывается, пока вызов спит.
    """
    outcome = await service.wait_for_notifications(
        session,
        initiator=current_actor,
        timeout=timeout,
        limit=limit,
    )
    return DataResponse[InboxWaitRead](
        data=InboxWaitRead(
            notifications=[NotificationRead.of(item) for item in outcome.notifications],
            waited=round(outcome.waited, 3),
            timed_out=outcome.timed_out,
        )
    )


@router.get("/subscriptions", summary="List notification subscriptions")
async def list_subscriptions(
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[SubscriptionRead]:
    """Подписки текущего актора.

    Пустой список означает «всё по умолчанию», а не «мне ничего не приходит»: автор,
    исполнитель, наблюдатель, упомянутый и участник проекта уведомляются правилом, без
    строки в базе.
    """
    page = await service.list_subscriptions(
        session,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[SubscriptionRead].of(
        [SubscriptionRead.of(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/subscriptions",
    status_code=status.HTTP_201_CREATED,
    summary="Create a notification subscription",
)
async def create_subscription(
    payload: SubscriptionCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SubscriptionRead]:
    """Заводит подписку: расширяет набор событий областью или настраивает роль.

    Подписка на свою ролевую область с `is_enabled: false` — это отказ от уведомлений
    по умолчанию. Отключить их иначе нечем: правило по умолчанию строки в базе не имеет.
    """
    subscription = await service.create_subscription(
        session,
        initiator=current_actor,
        scope=payload.scope,
        scope_key=payload.scope_key,
        event_types=payload.event_types,
        channel=payload.channel,
        is_enabled=payload.is_enabled,
        notify_own_actions=payload.notify_own_actions,
    )
    return DataResponse[SubscriptionRead](data=SubscriptionRead.of(subscription))


@router.patch("/subscriptions/{subscription_id}", summary="Update a notification subscription")
async def update_subscription(
    subscription_id: SubscriptionIdPath,
    payload: SubscriptionUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SubscriptionRead]:
    """Меняет только переданные поля подписки.

    Своей подписки: чужую поменять нельзя — иначе один актор перенастроил бы поток
    уведомлений другому.
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
        event_types=payload.event_types,
        is_enabled=payload.is_enabled,
        notify_own_actions=payload.notify_own_actions,
    )
    return DataResponse[SubscriptionRead](data=SubscriptionRead.of(updated))


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification subscription",
)
async def delete_subscription(
    subscription_id: SubscriptionIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет подписку.

    Удаление **выключенной** подписки на ролевую область возвращает уведомления по
    умолчанию: строки, которая их гасила, больше нет. Чтобы перестать их получать,
    подписку держат выключенной, а не удаляют.
    """
    subscription = await service.get_subscription(
        session,
        subscription_id,
        initiator=current_actor,
    )
    await service.delete_subscription(session, subscription, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
