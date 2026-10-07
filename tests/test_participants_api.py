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


async def test_the_list_is_a_collection_with_meta(
    auth_client: AsyncClient,
    owner: Participant,
) -> None:
    response = await auth_client.get("/api/v1/participants")

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload["data"]] == ["owner"]
    assert payload["meta"] == {"next_cursor": None, "has_more": False, "total": None}


async def test_a_single_participant_has_no_rest_route(
    auth_client: AsyncClient, owner: Participant
) -> None:
    """Интерфейс не читает и не правит участника по имени (TRK#53): ручек нет, есть MCP."""
    read = await auth_client.get("/api/v1/participants/owner")
    patch = await auth_client.patch("/api/v1/participants/owner", json={"description": "x"})

    assert read.status_code in (404, 405)
    assert patch.status_code in (404, 405)
