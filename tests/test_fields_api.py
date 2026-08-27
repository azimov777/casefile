"""Эндпоинты реестра полей: адресация ссылками, области действия, конфигурация очереди."""

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.services import issue_usage


@pytest.fixture
def issues_with_field(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Подменяет счётчик задач со значением поля: таблицы `issues` ещё нет."""

    def _set(count: int) -> None:
        async def _count(session: AsyncSession, field_ref: str) -> int:
            return count

        monkeypatch.setattr(issue_usage, "count_issues_with_field", _count)

    return _set


SEVERITY = {
    "key": "severity",
    "name": "Серьёзность",
    "value_type": "enum",
    "options": [{"key": "minor", "name": "Мелкая"}, {"key": "critical", "name": "Критическая"}],
}


async def test_empty_registry_is_an_empty_collection_not_an_empty_body(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get("/api/v1/fields")

    assert response.json() == {"data": [], "meta": {"next_cursor": None, "has_more": False}}


async def test_local_field_is_created_and_addressed_with_a_prefix(
    auth_client: AsyncClient, queue: Queue
) -> None:
    created = await auth_client.post("/api/v1/fields", json=SEVERITY | {"queue": "TRK"})

    assert created.status_code == 201
    data = created.json()["data"]
    assert (data["key"], data["queue"], data["ref"]) == ("severity", "TRK", "TRK.severity")

    read = await auth_client.get("/api/v1/fields/trk.SEVERITY")
    assert read.json()["data"]["name"] == "Серьёзность"


async def test_global_field_is_addressed_by_a_bare_key(auth_client: AsyncClient) -> None:
    created = await auth_client.post("/api/v1/fields", json=SEVERITY)

    data = created.json()["data"]
    assert (data["queue"], data["ref"]) == (None, "severity")


async def test_unknown_field_answers_with_its_own_code(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/fields/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "field_not_found"


async def test_broken_reference_explains_the_expected_format(auth_client: AsyncClient) -> None:
    """Ошибка домена полезнее нарушения шаблона: она говорит, какой формат ожидался."""
    response = await auth_client.get("/api/v1/fields/TRK.a.b")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_field_ref"
    assert body["details"]["expected"] == "<QUEUE>.<key> or <key>"


async def test_reserved_key_is_rejected(auth_client: AsyncClient) -> None:
    """`status` — колонка задачи: кастомное поле с таким ключом было бы недостижимо поиском."""
    response = await auth_client.post(
        "/api/v1/fields", json={"key": "status", "name": "Статус", "value_type": "string"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_field_key"


async def test_malformed_key_is_rejected_by_the_schema(auth_client: AsyncClient) -> None:
    """Ключ придумывают при создании — здесь шаблон строгий."""
    response = await auth_client.post(
        "/api/v1/fields", json={"key": "Severity!", "name": "x", "value_type": "string"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_enum_without_options_is_rejected_with_the_reason(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/fields", json={"key": "severity", "name": "Серьёзность", "value_type": "enum"}
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert (body["code"], body["details"]["reason"]) == (
        "invalid_field_definition",
        "enum_requires_options",
    )


# --- Фильтры и применимость ------------------------------------------------------


async def test_queue_filter_shows_global_and_local_fields_together(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await auth_client.post(
        "/api/v1/fields",
        json={**SEVERITY, "key": "business_value", "value_type": "number", "options": []},
    )
    await auth_client.post("/api/v1/fields", json=SEVERITY | {"queue": "TRK"})

    without_queue = await auth_client.get("/api/v1/fields")
    with_queue = await auth_client.get("/api/v1/fields", params={"queue": "TRK"})

    assert [item["ref"] for item in without_queue.json()["data"]] == ["business_value"]
    assert sorted(item["ref"] for item in with_queue.json()["data"]) == [
        "TRK.severity",
        "business_value",
    ]


async def test_issue_type_filter_answers_what_applies_to_the_pair(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await auth_client.post(
        "/api/v1/fields", json=SEVERITY | {"queue": "TRK", "issue_types": ["bug"]}
    )
    await auth_client.post(
        "/api/v1/fields",
        json={"key": "business_value", "name": "Ценность", "value_type": "number", "queue": "TRK"},
    )

    for_bug = await auth_client.get("/api/v1/fields", params={"queue": "TRK", "issue_type": "bug"})
    for_task = await auth_client.get(
        "/api/v1/fields", params={"queue": "TRK", "issue_type": "task"}
    )

    assert sorted(item["ref"] for item in for_bug.json()["data"]) == [
        "TRK.business_value",
        "TRK.severity",
    ]
    assert [item["ref"] for item in for_task.json()["data"]] == ["TRK.business_value"]


async def test_queue_configuration_carries_the_real_fields(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Ключ `fields` был заглушкой с пустым списком — клиент рассчитывает на него."""
    await auth_client.post(
        "/api/v1/fields",
        json=SEVERITY | {"queue": "TRK", "issue_types": ["bug"], "display_order": 5},
    )

    config = await auth_client.get("/api/v1/queues/TRK/config")

    fields = config.json()["data"]["fields"]
    assert [item["ref"] for item in fields] == ["TRK.severity"]
    assert fields[0]["issue_types"] == ["bug"]
    assert fields[0]["options"] == SEVERITY["options"]


async def test_hidden_field_disappears_from_the_configuration(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await auth_client.post("/api/v1/fields", json=SEVERITY | {"queue": "TRK"})

    hidden = await auth_client.patch("/api/v1/fields/TRK.severity", json={"is_hidden": True})
    config = await auth_client.get("/api/v1/queues/TRK/config")

    assert hidden.json()["data"]["is_hidden"] is True
    assert config.json()["data"]["fields"] == []


# --- Изменение и удаление --------------------------------------------------------


async def test_partial_update_touches_only_what_was_sent(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await auth_client.post(
        "/api/v1/fields", json=SEVERITY | {"queue": "TRK", "default_value": "minor"}
    )

    updated = await auth_client.patch("/api/v1/fields/TRK.severity", json={"name": "Критичность"})

    data = updated.json()["data"]
    assert (data["name"], data["default_value"]) == ("Критичность", "minor")


async def test_default_value_is_dropped_by_an_explicit_null(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """«Не передано» и «передано как null» обязаны различаться."""
    await auth_client.post(
        "/api/v1/fields", json=SEVERITY | {"queue": "TRK", "default_value": "minor"}
    )

    updated = await auth_client.patch("/api/v1/fields/TRK.severity", json={"default_value": None})

    assert updated.json()["data"]["default_value"] is None


async def test_key_cannot_be_changed_through_the_update(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Под ключом лежат значения в задачах: переименование порвало бы все ссылки."""
    await auth_client.post("/api/v1/fields", json=SEVERITY | {"queue": "TRK"})

    response = await auth_client.patch("/api/v1/fields/TRK.severity", json={"key": "other"})

    assert response.status_code == 422


async def test_issue_type_restrictions_are_replaced_wholesale(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await auth_client.post(
        "/api/v1/fields", json=SEVERITY | {"queue": "TRK", "issue_types": ["bug"]}
    )

    widened = await auth_client.patch("/api/v1/fields/TRK.severity", json={"issue_types": []})

    assert widened.json()["data"]["issue_types"] == []
    for_task = await auth_client.get(
        "/api/v1/fields", params={"queue": "TRK", "issue_type": "task"}
    )
    assert [item["ref"] for item in for_task.json()["data"]] == ["TRK.severity"]


async def test_unused_field_is_deleted_and_a_used_one_is_not(
    auth_client: AsyncClient, queue: Queue, issues_with_field: Callable[[int], None]
) -> None:
    await auth_client.post("/api/v1/fields", json=SEVERITY | {"queue": "TRK"})

    issues_with_field(4)
    refused = await auth_client.delete("/api/v1/fields/TRK.severity")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "field_in_use"

    issues_with_field(0)
    deleted = await auth_client.delete("/api/v1/fields/TRK.severity")
    assert deleted.status_code == 204
    assert (await auth_client.get("/api/v1/fields/TRK.severity")).status_code == 404


async def test_registry_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/fields")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
