"""Эндпоинты токенов: секрет виден один раз, отзыв идемпотентен, запись только с `main`.

Здесь же проверяется работа общего агентского токена через HTTP — заголовок
`X-Actor-Label` и подпись, которая из него получается.
"""

from httpx import AsyncClient

from app.db.models.participant import Participant


async def test_the_secret_is_shown_once_and_never_in_the_list(
    auth_client: AsyncClient,
    owner: Participant,
) -> None:
    """Обзорная проверка 7."""
    issued = await auth_client.post(
        "/api/v1/tokens",
        json={"name": "ci", "scope": "task", "participant": "owner"},
    )

    assert issued.status_code == 201, issued.text
    body = issued.json()["data"]
    assert body["secret"].startswith("trk_")
    assert body["participant"] == "owner"
    assert body["scope"] == "task"

    listed = await auth_client.get("/api/v1/tokens")

    assert listed.status_code == 200
    assert listed.json()["data"], "the issued token must appear in the list"
    for token in listed.json()["data"]:
        assert "secret" not in token
    assert body["secret"] not in listed.text


async def test_a_token_without_a_participant_is_shared(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/api/v1/tokens", json={"name": "agents"})

    assert response.status_code == 201, response.text
    assert response.json()["data"]["participant"] is None


async def test_issuing_for_an_unknown_participant_is_not_found(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/api/v1/tokens", json={"name": "ci", "participant": "ghost"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "participant_not_found"


async def test_revoking_is_idempotent_and_keeps_the_record(
    auth_client: AsyncClient,
    owner: Participant,
) -> None:
    issued = await auth_client.post("/api/v1/tokens", json={"name": "ci", "participant": "owner"})
    token_id = issued.json()["data"]["id"]

    first = await auth_client.delete(f"/api/v1/tokens/{token_id}")
    second = await auth_client.delete(f"/api/v1/tokens/{token_id}")

    assert (first.status_code, second.status_code) == (204, 204)
    listed = await auth_client.get("/api/v1/tokens")
    revoked = [item for item in listed.json()["data"] if item["id"] == token_id]
    assert len(revoked) == 1, "revoking marks the row, it does not delete it"
    assert revoked[0]["revoked_at"] is not None


async def test_writing_requires_the_main_scope(client: AsyncClient, task_secret: str) -> None:
    client.headers["Authorization"] = f"Bearer {task_secret}"

    forbidden = await client.post("/api/v1/tokens", json={"name": "ci"})
    readable = await client.get("/api/v1/tokens")

    assert forbidden.status_code == 403
    assert readable.status_code == 200


# --- Общий агентский токен через HTTP ----------------------------------------------


async def test_a_shared_token_without_the_header_is_refused(
    client: AsyncClient,
    shared_secret: str,
) -> None:
    """Обзорная проверка 3, первая половина: код назван в `docs/ERRORS.md`."""
    client.headers["Authorization"] = f"Bearer {shared_secret}"

    response = await client.get("/api/v1/queues")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "actor_label_required"


async def test_a_shared_token_with_the_header_signs_with_the_label(
    client: AsyncClient,
    main_secret: str,
) -> None:
    """Обзорная проверка 3, вторая половина: автор создающего вызова — метка и род `agent`.

    Выпускать очередь общим токеном нельзя (нужен `main`), поэтому создающий вызов здесь
    — регистрация участника: она тоже пишет автора, и общий токен для неё выпускается
    с набором `main`.
    """
    client.headers["Authorization"] = f"Bearer {main_secret}"
    issued = await client.post("/api/v1/tokens", json={"name": "agents", "scope": "main"})
    shared_main = issued.json()["data"]["secret"]

    client.headers["Authorization"] = f"Bearer {shared_main}"
    client.headers["X-Actor-Label"] = "Nightly_Agent"
    created = await client.post(
        "/api/v1/participants",
        json={"kind": "agent", "name": "helper"},
    )

    assert created.status_code == 201, created.text
    assert created.json()["data"]["created_by"] == {
        "kind": "agent",
        "signature": "nightly_agent",
    }


async def test_a_malformed_label_answers_with_its_own_code(
    client: AsyncClient,
    shared_secret: str,
) -> None:
    """Проверяет домен, а не схема заголовка: MCP получит ту же ошибку с тем же кодом."""
    client.headers["Authorization"] = f"Bearer {shared_secret}"
    client.headers["X-Actor-Label"] = "nightly agent"

    response = await client.get("/api/v1/queues")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_actor_label"
