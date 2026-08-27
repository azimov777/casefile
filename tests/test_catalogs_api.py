"""Эндпоинты справочников: адресация ссылками, области действия, защита от удаления."""

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.services import issue_usage


@pytest.fixture
def issues_in_status(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Подменяет счётчик задач в статусе: таблицы `issues` ещё нет (см. `issue_usage`)."""

    def _set(count: int) -> None:
        async def _count(session: AsyncSession, status_id: object) -> int:
            return count

        monkeypatch.setattr(issue_usage, "count_issues_with_status", _count)

    return _set


async def test_global_catalog_is_listed_without_a_queue(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/statuses")

    body = response.json()
    assert [item["key"] for item in body["data"]] == ["open", "in_progress", "closed"]
    assert all(item["queue"] is None for item in body["data"])
    assert all(item["ref"] == item["key"] for item in body["data"])
    assert body["meta"] == {"next_cursor": None, "has_more": False}


async def test_local_entry_is_created_and_addressed_with_a_prefix(
    auth_client: AsyncClient, queue: Queue
) -> None:
    created = await auth_client.post(
        "/api/v1/statuses",
        json={"key": "in_review", "name": "Ревью", "category": "in_progress", "queue": "TRK"},
    )

    assert created.status_code == 201
    data = created.json()["data"]
    assert (data["key"], data["queue"], data["ref"]) == ("in_review", "TRK", "TRK.in_review")

    read = await auth_client.get("/api/v1/statuses/TRK.in_review")
    assert read.json()["data"]["name"] == "Ревью"


async def test_queue_filter_shows_global_and_local_entries_together(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Это и есть ответ на вопрос «чем можно пользоваться в этой очереди»."""
    await auth_client.post(
        "/api/v1/statuses",
        json={"key": "in_review", "name": "Ревью", "category": "in_progress", "queue": "TRK"},
    )

    without_queue = await auth_client.get("/api/v1/statuses")
    with_queue = await auth_client.get("/api/v1/statuses", params={"queue": "TRK"})

    assert "in_review" not in [item["key"] for item in without_queue.json()["data"]]
    assert [item["ref"] for item in with_queue.json()["data"]] == [
        "open",
        "in_progress",
        "closed",
        "TRK.in_review",
    ]


async def test_status_without_a_category_is_rejected(auth_client: AsyncClient) -> None:
    """Категория обязательна на уровне схемы: она часть контракта, а не рекомендация."""
    response = await auth_client.post(
        "/api/v1/statuses", json={"key": "waiting", "name": "Ожидание"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unknown_category_is_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/statuses",
        json={"key": "waiting", "name": "Ожидание", "category": "almost_done"},
    )

    assert response.status_code == 422


async def test_duplicate_key_in_one_scope_is_a_conflict(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/statuses", json={"key": "open", "name": "Ещё один", "category": "new"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "status_key_taken"


async def test_unknown_reference_is_not_found(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/statuses/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "status_not_found"


async def test_malformed_reference_explains_the_expected_format(
    auth_client: AsyncClient,
) -> None:
    """Ошибка домена полезнее проверки по шаблону: в `details` написано, что ожидалось."""
    response = await auth_client.get("/api/v1/statuses/TRK.a.b")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_catalog_ref"
    assert "expected" in body["details"]


async def test_rename_and_disable(auth_client: AsyncClient) -> None:
    renamed = await auth_client.patch("/api/v1/statuses/closed", json={"name": "Готово"})
    assert renamed.json()["data"] == {**renamed.json()["data"], "key": "closed", "name": "Готово"}

    disabled = await auth_client.patch("/api/v1/statuses/closed", json={"is_active": False})
    assert disabled.json()["data"]["is_active"] is False


async def test_disabled_entry_disappears_from_the_queue_configuration(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await auth_client.patch("/api/v1/resolutions/duplicate", json={"is_active": False})

    config = await auth_client.get("/api/v1/queues/TRK/config")

    assert [item["key"] for item in config.json()["data"]["resolutions"]] == ["done", "rejected"]


async def test_status_with_issues_is_not_deleted(
    auth_client: AsyncClient, issues_in_status: Callable[[int], None]
) -> None:
    issues_in_status(4)

    response = await auth_client.delete("/api/v1/statuses/open")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "status_in_use"
    assert error["details"]["issues"] == 4


async def test_status_is_deleted_after_its_issues_are_moved(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Полный сценарий из задачи: перенести задачи, затем удалить опустевший статус."""
    moved_from: dict[str, object] = {}

    async def _move(session: AsyncSession, **kwargs: object) -> int:
        moved_from.update(kwargs)
        return 4

    async def _count(session: AsyncSession, status_id: object) -> int:
        return 0 if moved_from else 4

    monkeypatch.setattr(issue_usage, "move_issues_to_status", _move)
    monkeypatch.setattr(issue_usage, "count_issues_with_status", _count)

    rejected = await auth_client.delete("/api/v1/statuses/in_progress")
    assert rejected.status_code == 409

    moved = await auth_client.post(
        "/api/v1/statuses/in_progress/move-issues", json={"target_status": "open"}
    )
    assert moved.json()["data"] == {
        "source_status": "in_progress",
        "target_status": "open",
        "moved": 4,
    }

    deleted = await auth_client.delete("/api/v1/statuses/in_progress")
    assert deleted.status_code == 204


async def test_status_used_by_a_queue_by_default_is_not_deleted(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.delete("/api/v1/statuses/open")

    assert response.status_code == 409
    assert response.json()["error"]["details"]["queues"] == ["TRK"]


async def test_issue_types_and_resolutions_share_the_same_shape(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Три справочника — один контракт: клиент работает с ними одним кодом."""
    issue_type = await auth_client.post(
        "/api/v1/issue-types",
        json={"key": "incident", "name": "Инцидент", "icon": "fire", "queue": "TRK"},
    )
    resolution = await auth_client.post(
        "/api/v1/resolutions", json={"key": "wont_fix", "name": "Отложено"}
    )

    assert issue_type.json()["data"]["ref"] == "TRK.incident"
    assert issue_type.json()["data"]["icon"] == "fire"
    assert resolution.json()["data"]["ref"] == "wont_fix"
    assert (await auth_client.get("/api/v1/issue-types/TRK.incident")).status_code == 200
    assert (await auth_client.delete("/api/v1/resolutions/wont_fix")).status_code == 204
