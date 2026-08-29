"""Эндпоинты вебхуков: оболочка ответа, секрет один раз, журнал, переотправка.

Отдельная проверка здесь — порядок маршрутов. `GET /webhooks/deliveries` обязан
доставаться журналу, а не маршруту `/{subscription_id}`: FastAPI сопоставляет пути в
порядке объявления, и перестановка строк в роутере превратила бы журнал в `422`.
Комментарий в коде такую перестановку не остановит, а этот тест — остановит.
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.event import OutboxEvent
from app.db.models.issue import Issue
from app.db.models.webhook import WebhookDelivery
from app.domain.webhooks import SECRET_PREFIX, DeliveryStatus
from app.services import webhooks as webhooks_service
from app.services.event_bus import EventEnvelope

MakeIssue = Callable[..., Awaitable[Issue]]

PAYLOAD = {
    "name": "release-bot",
    "url": "https://ci.example.test/hooks/tracker",
}


async def create(client: AsyncClient, **overrides: object) -> dict:
    """Заводит подписку и отдаёт её представление вместе с секретом."""
    response = await client.post("/api/v1/webhooks", json=PAYLOAD | overrides)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def queue_delivery(session: AsyncSession, issue: Issue) -> WebhookDelivery:
    """Ставит задание из настоящего события задачи — так же, как это делает воркер."""
    statement = select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)
    event = (await session.scalars(statement)).unique().first()
    assert event is not None
    (delivery,) = await webhooks_service.dispatch_event(
        session,
        EventEnvelope(
            id=event.id,
            event_type=event.event_type,
            object_type=event.object_type,
            object_id=event.object_id,
            object_key=event.object_key,
            actor_key=event.actor_key,
            payload=event.payload,
            created_at=event.created_at,
        ),
    )
    return delivery


async def test_creating_a_subscription_returns_its_secret_once(auth_client: AsyncClient) -> None:
    """Секрет нужен получателю для проверки подписи, и повторить его API не сможет."""
    data = await create(auth_client)

    assert data["secret"].startswith(SECRET_PREFIX)
    assert data["secret_hint"].endswith(data["secret"][-4:])

    listed = await auth_client.get("/api/v1/webhooks")
    (item,) = listed.json()["data"]
    assert "secret" not in item
    assert item["secret_hint"] == data["secret_hint"]


async def test_a_subscription_can_be_created_with_a_secret_already_wired_elsewhere(
    auth_client: AsyncClient,
) -> None:
    """Получатель часто уже знает секрет: отвергать его значило бы запрещать подключение."""
    data = await create(auth_client, secret="already-known-shared-secret")

    assert data["secret"] == "already-known-shared-secret"


async def test_an_address_that_could_never_be_called_is_refused(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/api/v1/webhooks", json=PAYLOAD | {"url": "ftp://x/y"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_webhook_subscription"
    assert error["details"]["field"] == "url"


async def test_a_duplicate_name_is_a_conflict(auth_client: AsyncClient) -> None:
    """По имени подписку адресует правило автоматики, и двух одинаковых быть не может."""
    await create(auth_client)

    response = await auth_client.post("/api/v1/webhooks", json=PAYLOAD)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "webhook_subscription_name_taken"


async def test_a_queue_subscription_without_a_key_is_refused(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/webhooks",
        json=PAYLOAD | {"scope": "queue"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "scope_key"


async def test_the_deliveries_route_is_not_swallowed_by_the_subscription_route(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Перестановка строк в роутере превратила бы журнал в `422` о неверном UUID."""
    await create(auth_client)
    issue = await make_issue()
    await queue_delivery(db_session, issue)

    response = await auth_client.get("/api/v1/webhooks/deliveries")

    assert response.status_code == 200, response.text
    (delivery,) = response.json()["data"]
    assert delivery["object_key"] == issue.key
    assert delivery["status"] == DeliveryStatus.PENDING
    assert delivery["payload"]["delivery"] == delivery["id"]


async def test_the_log_can_be_narrowed_to_one_subscription_and_state(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    subscription = await create(auth_client)
    issue = await make_issue()
    await queue_delivery(db_session, issue)

    response = await auth_client.get(
        "/api/v1/webhooks/deliveries",
        params={"subscription": subscription["id"], "delivery_status": "delivered"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_a_finished_delivery_can_be_sent_again_as_a_new_one(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Ответ `201`: создаётся новая запись, а старая остаётся в журнале нетронутой."""
    await create(auth_client)
    issue = await make_issue()
    delivery = await queue_delivery(db_session, issue)
    delivery.status = DeliveryStatus.FAILED
    await db_session.flush()

    response = await auth_client.post(f"/api/v1/webhooks/deliveries/{delivery.id}/retry")

    assert response.status_code == 201, response.text
    repeated = response.json()["data"]
    assert repeated["id"] != str(delivery.id)
    assert repeated["event"] == str(delivery.event_id)
    assert repeated["payload"]["delivery"] == repeated["id"]


async def test_a_pending_delivery_cannot_be_sent_again(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    await create(auth_client)
    issue = await make_issue()
    delivery = await queue_delivery(db_session, issue)

    response = await auth_client.post(f"/api/v1/webhooks/deliveries/{delivery.id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "webhook_delivery_not_retryable"


async def test_updating_a_subscription_keeps_the_secret_out_of_the_answer(
    auth_client: AsyncClient,
) -> None:
    data = await create(auth_client)

    response = await auth_client.patch(
        f"/api/v1/webhooks/{data['id']}",
        json={"url": "https://ci.example.test/hooks/v2", "is_enabled": False},
    )

    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert updated["url"] == "https://ci.example.test/hooks/v2"
    assert updated["is_enabled"] is False
    assert "secret" not in updated


async def test_scope_cannot_be_moved_by_an_update(auth_client: AsyncClient) -> None:
    """«Подписка на очередь» и «подписка на проект» — разные подписки, а не одна."""
    data = await create(auth_client)

    response = await auth_client.patch(
        f"/api/v1/webhooks/{data['id']}",
        json={"scope": "queue", "scope_key": "TRK"},
    )

    assert response.status_code == 422


async def test_deleting_a_subscription_takes_its_log_with_it(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    make_issue: MakeIssue,
) -> None:
    """Журнал описывает работу конкретного адреса: без подписки отвечать ему не на что."""
    data = await create(auth_client)
    issue = await make_issue()
    await queue_delivery(db_session, issue)

    response = await auth_client.delete(f"/api/v1/webhooks/{data['id']}")

    assert response.status_code == 204
    remaining = await auth_client.get("/api/v1/webhooks/deliveries")
    assert remaining.json()["data"] == []


async def test_an_unknown_subscription_is_not_found(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/webhooks/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhook_subscription_not_found"
