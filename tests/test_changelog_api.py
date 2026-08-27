"""Эндпоинт истории изменений задачи.

Проверяется контракт: единая оболочка ответа, курсорная пагинация, ссылки строками.
Отдельно — что история появляется сама, без единого специального вызова: обычный
`POST` и обычный `PATCH` оставляют в ней записи, потому что подключены к единой точке
применения изменений.
"""

from httpx import AsyncClient

from app.domain.events import EventType


async def _create_issue(client: AsyncClient, summary: str = "Починить выдачу ключей") -> str:
    response = await client.post(
        "/api/v1/issues",
        json={"queue": "TRK", "summary": summary},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["key"]


async def test_the_history_of_a_fresh_issue_has_one_entry(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Первая запись — `issue.created`, и список изменений у неё пуст."""
    key = await _create_issue(auth_client)

    response = await auth_client.get(f"/api/v1/issues/{key}/changelog")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"] == {"next_cursor": None, "has_more": False}
    assert len(body["data"]) == 1
    entry = body["data"][0]
    assert entry["issue"] == key
    assert entry["actor"] == "owner"
    assert entry["event"] == EventType.ISSUE_CREATED
    assert entry["changes"] == []


async def test_an_update_shows_up_in_the_history(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Обычный `PATCH` оставляет запись сам: специального вызова для истории нет."""
    key = await _create_issue(auth_client, summary="Было")

    patch = await auth_client.patch(
        f"/api/v1/issues/{key}",
        json={"summary": "Стало", "status": "in_progress"},
    )
    assert patch.status_code == 200, patch.text

    body = (await auth_client.get(f"/api/v1/issues/{key}/changelog")).json()

    assert [entry["event"] for entry in body["data"]] == [
        EventType.ISSUE_CREATED,
        # Среди изменений есть статус, поэтому событие получило свой тип, а не общий.
        EventType.ISSUE_STATUS_CHANGED,
    ]
    changes = {change["field"]: change for change in body["data"][1]["changes"]}
    assert changes["summary"] == {"field": "summary", "before": "Было", "after": "Стало"}
    # Ссылка справочника — строкой на момент события, а не идентификатором строки,
    # которую могут переименовать или удалить.
    assert changes["status"] == {"field": "status", "before": "open", "after": "in_progress"}


async def test_the_history_is_paginated(auth_client: AsyncClient, queue: object) -> None:
    """Та же курсорная пагинация, что и у любой коллекции проекта."""
    key = await _create_issue(auth_client)
    for summary in ("Второе", "Третье"):
        await auth_client.patch(f"/api/v1/issues/{key}", json={"summary": summary})

    first = (await auth_client.get(f"/api/v1/issues/{key}/changelog?limit=2")).json()

    assert len(first["data"]) == 2
    assert first["meta"]["has_more"] is True

    cursor = first["meta"]["next_cursor"]
    second = (await auth_client.get(f"/api/v1/issues/{key}/changelog?cursor={cursor}")).json()

    assert len(second["data"]) == 1
    assert second["meta"]["has_more"] is False
    seen = [entry["id"] for entry in first["data"] + second["data"]]
    assert len(set(seen)) == 3


async def test_the_history_of_a_missing_issue_is_a_domain_error(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Несуществующая задача — `issue_not_found`, а не пустая коллекция."""
    response = await auth_client.get("/api/v1/issues/TRK-404/changelog")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "issue_not_found"


async def test_the_history_requires_a_token(client: AsyncClient, queue: object) -> None:
    """Маршрут защищён по умолчанию: аутентификация висит на роутере версии API."""
    response = await client.get("/api/v1/issues/TRK-1/changelog")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
