"""Эндпоинты инбокса и подписок: оболочка ответа, коды ошибок, доступ к чужому.

Smoke-уровень по соглашениям: подробная логика адресации проверена на сервисном слое,
здесь — что маршрут есть, что он отвечает в единой оболочке и что чужое недоступно.
"""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.domain.actors import ActorType
from app.domain.notifications import SubscriptionScope
from app.services import actors as actors_service
from app.services import notifications as service


@pytest.fixture
async def bob(db_session: AsyncSession) -> Actor:
    actor, _ = await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="bob",
        display_name="Bob",
    )
    return actor


@pytest.fixture
async def bob_client(
    client: AsyncClient,
    db_session: AsyncSession,
    system_actor: Actor,
    bob: Actor,
) -> AsyncClient:
    """Клиент, ходящий токеном второго актора: инбокс всегда принадлежит владельцу токена."""
    issued = await actors_service.issue_token(db_session, bob, initiator=system_actor, name="tests")
    client.headers["Authorization"] = f"Bearer {issued.secret}"
    return client


class TestInboxEndpoints:
    async def test_an_empty_inbox_is_an_empty_collection(self, auth_client: AsyncClient) -> None:
        """Пустая коллекция — это `data: []`, а не пустое тело."""
        response = await auth_client.get("/api/v1/notifications")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["meta"]["has_more"] is False

    async def test_a_notification_carries_identifiers_next_to_the_text(
        self,
        db_session: AsyncSession,
        bob: Actor,
        bob_client: AsyncClient,
        make_issue: Callable[..., Awaitable[object]],
    ) -> None:
        issue = await make_issue()
        await service.notify_actor(
            db_session,
            actor=bob,
            body="Deadline is tomorrow",
            issue=issue,
            details={"reason": "deadline"},
        )

        response = await bob_client.get("/api/v1/notifications")

        (item,) = response.json()["data"]
        assert item["body"] == "Deadline is tomorrow"
        assert item["issue"] == issue.key
        assert item["event_type"] == "notification.direct"
        assert item["details"]["reason"] == "deadline"
        assert item["is_read"] is False

    async def test_marking_the_inbox_read_needs_no_identifiers(
        self,
        db_session: AsyncSession,
        bob: Actor,
        bob_client: AsyncClient,
    ) -> None:
        await service.notify_actor(db_session, actor=bob, body="First")
        await service.notify_actor(db_session, actor=bob, body="Second")

        response = await bob_client.post("/api/v1/notifications/read", json={})

        assert response.status_code == 200
        assert response.json()["data"]["marked"] == 2

    async def test_marking_someone_elses_notification_is_not_found(
        self,
        db_session: AsyncSession,
        bob: Actor,
        auth_client: AsyncClient,
    ) -> None:
        theirs = await service.notify_actor(db_session, actor=bob, body="Not yours")
        assert theirs is not None

        response = await auth_client.post(
            "/api/v1/notifications/read",
            json={"notifications": [str(theirs.id)]},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "notification_not_found"

    async def test_waiting_returns_an_empty_result_on_timeout(
        self,
        auth_client: AsyncClient,
    ) -> None:
        """Таймаут — не ошибка: клиент отличает его по полю, а не по коду ответа."""
        response = await auth_client.get("/api/v1/notifications/wait", params={"timeout": 1})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["notifications"] == []
        assert data["timed_out"] is True

    async def test_waiting_beyond_the_ceiling_is_rejected(
        self,
        auth_client: AsyncClient,
    ) -> None:
        response = await auth_client.get(
            "/api/v1/notifications/wait",
            params={"timeout": 100_000},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_wait_timeout"


class TestSubscriptionEndpoints:
    async def test_a_subscription_is_created_and_listed(self, auth_client: AsyncClient) -> None:
        created = await auth_client.post(
            "/api/v1/notifications/subscriptions",
            json={"scope": "queue", "scope_key": "TRK", "event_types": ["issue.created"]},
        )

        assert created.status_code == 201
        assert created.json()["data"]["scope"] == "queue"

        listed = await auth_client.get("/api/v1/notifications/subscriptions")
        assert [item["scope_key"] for item in listed.json()["data"]] == ["TRK"]

    async def test_a_target_scope_without_a_key_is_rejected(
        self,
        auth_client: AsyncClient,
    ) -> None:
        response = await auth_client.post(
            "/api/v1/notifications/subscriptions",
            json={"scope": "queue"},
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "invalid_subscription"
        assert error["details"]["field"] == "scope_key"

    async def test_an_unknown_event_type_is_rejected(self, auth_client: AsyncClient) -> None:
        """Опечатка иначе дала бы подписку, которая молча никогда не срабатывает."""
        response = await auth_client.post(
            "/api/v1/notifications/subscriptions",
            json={"scope": "all", "event_types": ["issue.updted"]},
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"]["unknown"] == ["issue.updted"]

    async def test_a_duplicate_scope_is_a_conflict(self, auth_client: AsyncClient) -> None:
        payload = {"scope": "issue", "scope_key": "TRK-1"}
        await auth_client.post("/api/v1/notifications/subscriptions", json=payload)

        response = await auth_client.post("/api/v1/notifications/subscriptions", json=payload)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "subscription_exists"

    async def test_a_subscription_is_switched_off_rather_than_deleted(
        self,
        auth_client: AsyncClient,
    ) -> None:
        created = await auth_client.post(
            "/api/v1/notifications/subscriptions",
            json={"scope": "assignee"},
        )
        subscription_id = created.json()["data"]["id"]

        response = await auth_client.patch(
            f"/api/v1/notifications/subscriptions/{subscription_id}",
            json={"is_enabled": False},
        )

        assert response.status_code == 200
        assert response.json()["data"]["is_enabled"] is False

    async def test_someone_elses_subscription_is_not_found(
        self,
        db_session: AsyncSession,
        bob: Actor,
        auth_client: AsyncClient,
    ) -> None:
        theirs = await service.create_subscription(
            db_session,
            initiator=bob,
            scope=SubscriptionScope.ALL,
        )

        response = await auth_client.patch(
            f"/api/v1/notifications/subscriptions/{theirs.id}",
            json={"is_enabled": False},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "subscription_not_found"

    async def test_deleting_a_subscription_answers_204(self, auth_client: AsyncClient) -> None:
        created = await auth_client.post(
            "/api/v1/notifications/subscriptions",
            json={"scope": "follower"},
        )
        subscription_id = created.json()["data"]["id"]

        response = await auth_client.delete(
            f"/api/v1/notifications/subscriptions/{subscription_id}"
        )

        assert response.status_code == 204
        assert response.content == b""

    async def test_an_unknown_subscription_is_not_found(self, auth_client: AsyncClient) -> None:
        response = await auth_client.delete(f"/api/v1/notifications/subscriptions/{uuid.uuid4()}")

        assert response.status_code == 404
