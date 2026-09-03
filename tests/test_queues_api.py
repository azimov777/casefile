"""Эндпоинты очередей: доступ по набору, неизменяемый ключ, частичное обновление."""

from httpx import AsyncClient

from app.db.models.queue import Queue


async def test_creation_answers_with_the_created_queue(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/queues",
        json={"key": "ops", "title": "Эксплуатация", "description": "Дежурства и выкладки"},
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["key"] == "OPS"
    assert data["last_task_number"] == 0
    assert data["created_by"] == {"kind": "human", "signature": "owner"}


async def test_creation_is_forbidden_for_the_task_scope(
    client: AsyncClient,
    task_secret: str,
    main_secret: str,
) -> None:
    """Обзорная проверка 2: тот же запрос отклоняется с `task` и проходит с `main`."""
    client.headers["Authorization"] = f"Bearer {task_secret}"
    forbidden = await client.post("/api/v1/queues", json={"key": "OPS", "title": "Эксплуатация"})

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "permission_denied"
    assert forbidden.json()["error"]["details"]["required_scope"] == "main"

    client.headers["Authorization"] = f"Bearer {main_secret}"
    created = await client.post("/api/v1/queues", json={"key": "OPS", "title": "Эксплуатация"})

    assert created.status_code == 201, created.text


async def test_reading_ignores_case_in_the_key(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.get("/api/v1/queues/trk")

    assert response.status_code == 200
    assert response.json()["data"]["key"] == "TRK"


async def test_an_unknown_queue_answers_with_its_own_code(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/queues/GHOST")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "queue_not_found"


async def test_the_list_is_a_collection_with_meta(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.get("/api/v1/queues")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload["data"]] == ["TRK"]
    assert payload["meta"] == {"next_cursor": None, "has_more": False}


async def test_patch_refuses_the_key_and_accepts_the_description(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорная проверка 4: `key` в теле — `422`, `description` меняет описание."""
    refused = await auth_client.patch("/api/v1/queues/TRK", json={"key": "OPS"})

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_error"

    changed = await auth_client.patch(
        "/api/v1/queues/TRK", json={"description": "Новый общий контекст"}
    )

    assert changed.status_code == 200, changed.text
    data = changed.json()["data"]
    assert data["description"] == "Новый общий контекст"
    assert data["key"] == "TRK"
    assert data["title"] == "Трекер", "an omitted field must stay as it was"


async def test_patch_requires_the_main_scope(
    client: AsyncClient,
    task_secret: str,
    queue: Queue,
) -> None:
    client.headers["Authorization"] = f"Bearer {task_secret}"

    response = await client.patch("/api/v1/queues/TRK", json={"title": "Нельзя"})

    assert response.status_code == 403
