"""Эндпоинты участников: оболочка ответа, доступ по набору, канонизация имени."""

from httpx import AsyncClient

from app.db.models.participant import Participant


async def test_registration_answers_with_the_created_participant(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/participants",
        json={"kind": "agent", "name": "release_bot", "description": "Релизный бот"},
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["name"] == "release_bot"
    assert data["kind"] == "agent"
    assert data["created_by"] == {"kind": "human", "signature": "owner"}


async def test_a_name_differing_only_in_case_is_a_conflict(
    auth_client: AsyncClient,
    owner: Participant,
) -> None:
    """Обзорная проверка 1: именно `409`, а не `422` от шаблона схемы."""
    response = await auth_client.post(
        "/api/v1/participants",
        json={"kind": "human", "name": "OWNER"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "participant_name_taken"


async def test_a_malformed_name_is_a_schema_error(auth_client: AsyncClient) -> None:
    """Форму имени проверяет схема: сюда домен уже не зовут."""
    response = await auth_client.post(
        "/api/v1/participants",
        json={"kind": "human", "name": "release-bot"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_reading_ignores_case(auth_client: AsyncClient, owner: Participant) -> None:
    response = await auth_client.get("/api/v1/participants/OWNER")

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "owner"


async def test_an_unknown_participant_answers_with_its_own_code(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/participants/ghost")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "participant_not_found"


async def test_the_list_is_a_collection_with_meta(
    auth_client: AsyncClient,
    owner: Participant,
) -> None:
    response = await auth_client.get("/api/v1/participants")

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload["data"]] == ["owner"]
    assert payload["meta"] == {"next_cursor": None, "has_more": False, "total": None}


async def test_patch_changes_the_description(auth_client: AsyncClient, owner: Participant) -> None:
    response = await auth_client.patch(
        "/api/v1/participants/owner",
        json={"description": "Отвечает на вопросы по вечерам"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["description"] == "Отвечает на вопросы по вечерам"


async def test_patch_refuses_to_rename(auth_client: AsyncClient, owner: Participant) -> None:
    """Имя стоит подписью в делах: схема отвергает лишнее поле, а не глотает его."""
    response = await auth_client.patch("/api/v1/participants/owner", json={"name": "boss"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_patch_refuses_an_explicit_null(auth_client: AsyncClient, owner: Participant) -> None:
    """Молча отбросить `null` хуже отказа: клиент решил бы, что поле изменено."""
    response = await auth_client.patch("/api/v1/participants/owner", json={"description": None})

    assert response.status_code == 422


async def test_writing_requires_the_main_scope(client: AsyncClient, task_secret: str) -> None:
    client.headers["Authorization"] = f"Bearer {task_secret}"

    forbidden = await client.post("/api/v1/participants", json={"kind": "human", "name": "new_one"})
    readable = await client.get("/api/v1/participants")

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "permission_denied"
    assert readable.status_code == 200
