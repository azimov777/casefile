"""Эндпоинты акторов и токенов: доступ, оболочка ответа, полный цикл токена."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.domain.actors import ActorType
from app.services import actors as service

PROTECTED = [
    ("get", "/api/v1/actors"),
    ("post", "/api/v1/actors"),
    ("get", "/api/v1/actors/me"),
    ("get", "/api/v1/actors/owner/tokens"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_request_without_token_is_rejected(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    """Аутентификация объявлена на самом роутере, поэтому закрыт каждый маршрут."""
    response = await client.request(method, path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_unknown_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/actors/me",
        headers={"Authorization": "Bearer trk_nonsense"},
    )

    assert response.status_code == 401


async def test_non_bearer_scheme_is_rejected(client: AsyncClient) -> None:
    """Иначе `HTTPBearer` со значениями по умолчанию ответил бы 403 в чужом формате."""
    response = await client.get("/api/v1/actors/me", headers={"Authorization": "Basic abc"})

    assert response.status_code == 401
    assert response.json()["error"]["details"]["reason"] == "missing_token"


async def test_me_returns_the_token_owner(auth_client: AsyncClient, owner: Actor) -> None:
    response = await auth_client.get("/api/v1/actors/me")

    assert response.status_code == 200
    assert response.json()["data"]["key"] == owner.key


async def test_create_actor_returns_the_created_resource(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/actors",
        json={"type": "agent", "key": "release_bot", "display_name": "Релизный бот"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["key"] == "release_bot"
    assert data["type"] == "agent"
    assert data["is_active"] is True


async def test_bad_key_is_reported_with_allowed_pattern(auth_client: AsyncClient) -> None:
    """Схема Pydantic ловит шаблон раньше домена — ответ всё равно в общем конверте."""
    response = await auth_client.post(
        "/api/v1/actors",
        json={"type": "agent", "key": "Bad Key", "display_name": "Бот"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_reserved_key_is_reported_by_the_domain(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/actors",
        json={"type": "agent", "key": "me", "display_name": "Я"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_actor_key"


async def test_list_uses_the_collection_envelope(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/actors")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["data"], list)
    assert body["meta"] == {"next_cursor": None, "has_more": False}


async def test_cursor_walks_the_whole_collection(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Страницы не теряют и не дублируют записи — ради этого ключ сортировки составной."""
    for index in range(4):
        await service.create_actor(
            db_session,
            initiator=owner,
            actor_type=ActorType.AGENT,
            key=f"bot_{index}",
            display_name=f"Бот {index}",
        )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = (await auth_client.get("/api/v1/actors", params=params)).json()
        seen.extend(actor["key"] for actor in body["data"])
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen))
    assert {"system", "owner", "bot_0", "bot_1", "bot_2", "bot_3"} == set(seen)


async def test_broken_cursor_is_a_validation_error(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/actors", params={"cursor": "%%%broken"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_filter_by_type(auth_client: AsyncClient) -> None:
    await auth_client.post(
        "/api/v1/actors",
        json={"type": "agent", "key": "filtered_bot", "display_name": "Бот"},
    )

    body = (await auth_client.get("/api/v1/actors", params={"type": "agent"})).json()

    assert [actor["key"] for actor in body["data"]] == ["filtered_bot"]


async def test_patch_changes_only_passed_fields(auth_client: AsyncClient) -> None:
    await auth_client.post(
        "/api/v1/actors",
        json={"type": "agent", "key": "patched_bot", "display_name": "Бот"},
    )

    response = await auth_client.patch("/api/v1/actors/patched_bot", json={"is_active": False})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_active"] is False
    assert data["display_name"] == "Бот"


async def test_token_lifecycle(auth_client: AsyncClient, owner: Actor) -> None:
    """Выпуск, работа новым токеном, отзыв и отказ отозванному — один сквозной сценарий."""
    issued = await auth_client.post(
        f"/api/v1/actors/{owner.key}/tokens",
        json={"name": "laptop"},
    )
    assert issued.status_code == 201
    token = issued.json()["data"]
    assert token["secret"].startswith("trk_")
    assert token["revoked_at"] is None

    headers = {"Authorization": f"Bearer {token['secret']}"}
    assert (await auth_client.get("/api/v1/actors/me", headers=headers)).status_code == 200

    revoked = await auth_client.delete(f"/api/v1/actors/{owner.key}/tokens/{token['id']}")
    assert revoked.status_code == 204
    assert revoked.content == b""

    assert (await auth_client.get("/api/v1/actors/me", headers=headers)).status_code == 401
    # Отзыв идемпотентен: повторный запрос отвечает так же.
    assert (
        await auth_client.delete(f"/api/v1/actors/{owner.key}/tokens/{token['id']}")
    ).status_code == 204


async def test_issued_secret_is_never_returned_again(
    auth_client: AsyncClient,
    owner: Actor,
) -> None:
    await auth_client.post(f"/api/v1/actors/{owner.key}/tokens", json={"name": "laptop"})

    body = (await auth_client.get(f"/api/v1/actors/{owner.key}/tokens")).json()

    assert body["data"]
    assert all("secret" not in token for token in body["data"])


async def test_system_actor_is_protected_from_the_api(auth_client: AsyncClient) -> None:
    patched = await auth_client.patch("/api/v1/actors/system", json={"is_active": False})
    issued = await auth_client.post("/api/v1/actors/system/tokens", json={"name": "fake"})

    assert patched.status_code == 409
    assert patched.json()["error"]["code"] == "system_actor_protected"
    assert issued.status_code == 409


async def test_missing_actor_returns_domain_code(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/actors/ghost")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "actor_not_found"
