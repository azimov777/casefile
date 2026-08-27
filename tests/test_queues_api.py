"""Эндпоинты очередей: оболочка ответа, цикл жизни, конфигурация одним запросом."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind, StatusCategory
from app.services import catalogs as catalogs_service


async def test_queue_endpoints_require_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/queues")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_create_queue_returns_the_created_resource(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/queues",
        json={"key": "OPS", "name": "Эксплуатация", "description": "Дежурства"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["key"] == "OPS"
    assert data["owner"] == "owner"
    assert data["default_status"] == "open"
    assert data["default_issue_type"] == "task"
    assert data["last_issue_number"] == 0
    assert data["is_archived"] is False


async def test_duplicate_key_is_a_conflict(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.post("/api/v1/queues", json={"key": "TRK", "name": "Второй"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "queue_key_taken"


async def test_malformed_key_is_rejected_by_the_schema(auth_client: AsyncClient) -> None:
    """Создание строгое: придумать ключ с разделителем нельзя."""
    response = await auth_client.post("/api/v1/queues", json={"key": "trk-2", "name": "Плохой"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_queue_is_addressed_case_insensitively(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Адресация мягкая: `trk` находит ту же очередь, что и `TRK`, как и в MCP."""
    response = await auth_client.get("/api/v1/queues/trk")

    assert response.status_code == 200
    assert response.json()["data"]["key"] == "TRK"


async def test_unknown_queue_is_not_found(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/queues/NOPE")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "queue_not_found"


async def test_list_returns_a_collection_with_meta(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.get("/api/v1/queues")

    body = response.json()
    assert [item["key"] for item in body["data"]] == ["TRK"]
    assert body["meta"] == {"next_cursor": None, "has_more": False}


async def test_patch_changes_only_what_is_passed(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.patch("/api/v1/queues/TRK", json={"name": "Разработка"})

    data = response.json()["data"]
    assert data["name"] == "Разработка"
    assert data["description"] == "Задачи по разработке трекера"


async def test_patch_rejects_an_explicit_null(auth_client: AsyncClient, queue: Queue) -> None:
    """У полей очереди нет осмысленного `null`; описание очищается пустой строкой."""
    response = await auth_client.patch("/api/v1/queues/TRK", json={"name": None})

    assert response.status_code == 422


async def test_patch_cannot_change_the_key(auth_client: AsyncClient, queue: Queue) -> None:
    """Ключ неизменяем: на нём построены ключи уже заведённых задач."""
    response = await auth_client.patch("/api/v1/queues/TRK", json={"key": "OPS"})

    assert response.status_code == 422


async def test_queue_renders_a_local_default_status(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    """Ссылка на локальный статус собирается при сборке ответа — из связи, а не из контекста.

    Проверка живая: связь `queue` у справочника грузится стратегией `selectin`, и
    обращение к незагруженной связи в асинхронной сессии упало бы `MissingGreenlet`
    ровно здесь — на сборке ответа, а не в сценарии.
    """
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="backlog",
        name="Бэклог",
        queue=queue,
        category=StatusCategory.NEW,
    )
    await auth_client.patch("/api/v1/queues/TRK", json={"default_status": "TRK.backlog"})

    response = await auth_client.get("/api/v1/queues/TRK")

    assert response.json()["data"]["default_status"] == "TRK.backlog"


async def test_config_returns_the_whole_process_in_one_request(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.get("/api/v1/queues/TRK/config")

    data = response.json()["data"]
    assert data["queue"]["key"] == "TRK"
    assert [issue_type["key"] for issue_type in data["issue_types"]] == ["task", "bug", "epic"]
    assert [status["key"] for status in data["statuses"]] == ["open", "in_progress", "closed"]
    assert [status["category"] for status in data["statuses"]] == ["new", "in_progress", "done"]
    assert [item["key"] for item in data["resolutions"]] == ["done", "rejected", "duplicate"]
    # Ключи-заглушки присутствуют с самого начала: клиент, написанный сегодня, не
    # должен переписываться, когда в задачах 04 и 07 они наполнятся.
    assert data["fields"] == []
    assert data["workflows"] == []


async def test_issue_types_are_replaced_wholesale(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.put(
        "/api/v1/queues/TRK/issue-types", json={"issue_types": ["task", "bug"]}
    )

    assert response.status_code == 200
    assert [item["key"] for item in response.json()["data"]] == ["task", "bug"]


async def test_dropping_the_default_issue_type_is_rejected(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.put(
        "/api/v1/queues/TRK/issue-types", json={"issue_types": ["bug"]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["reason"] == "default_issue_type_must_stay"


async def test_archive_and_unarchive(auth_client: AsyncClient, queue: Queue) -> None:
    archived = await auth_client.post("/api/v1/queues/TRK/archive")
    assert archived.json()["data"]["is_archived"] is True
    assert archived.json()["data"]["archived_at"] is not None

    restored = await auth_client.post("/api/v1/queues/TRK/unarchive")
    assert restored.json()["data"]["is_archived"] is False
    assert restored.json()["data"]["archived_at"] is None


async def test_empty_queue_is_deleted(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.delete("/api/v1/queues/TRK")

    assert response.status_code == 204
    assert response.content == b""
    assert (await auth_client.get("/api/v1/queues/TRK")).status_code == 404


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {"key": "OPS", "name": "Плохой тип", "default_issue_type": "nope"},
            "issue_type_not_found",
        ),
        ({"key": "OPS", "name": "Плохой статус", "default_status": "nope"}, "status_not_found"),
        # Локальная ссылка при создании невозможна независимо от того, есть ли такая
        # очередь: у создаваемой очереди своих справочников ещё нет.
        (
            {"key": "OPS", "name": "Чужой", "issue_types": ["OTHER.task"]},
            "catalog_entry_unavailable",
        ),
    ],
)
async def test_unknown_references_are_reported_precisely(
    auth_client: AsyncClient, payload: dict[str, object], code: str
) -> None:
    """Фронтенд отличает `status_not_found` от `issue_type_not_found` по коду, а не по тексту."""
    response = await auth_client.post("/api/v1/queues", json=payload)

    assert response.json()["error"]["code"] == code
