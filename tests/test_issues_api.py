"""Эндпоинты задач: оболочка ответа, частичное обновление, конфликт версий, наблюдатели.

Проверяется контракт, а не логика: логика — в `tests/test_issues_service.py`. Отдельно
стережётся то, что через HTTP видно только здесь: `null` в теле `PATCH` доезжает до
сценария как «очистить», а не как «не передано».
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.db.models.issue import Issue
from app.db.models.queue import Queue

MakeIssue = Callable[..., Awaitable[Issue]]

NEW_ISSUE = {"queue": "TRK", "summary": "Починить выдачу ключей"}


# --- Создание и чтение -----------------------------------------------------------


async def test_created_issue_comes_back_in_the_envelope(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.post("/api/v1/issues", json=NEW_ISSUE)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"data"}
    assert body["data"]["key"] == "TRK-1"
    assert body["data"]["queue"] == "TRK"
    assert body["data"]["status"] == "open"
    assert body["data"]["author"] == "owner"
    assert body["data"]["version"] == 1


async def test_issue_is_read_by_a_lowercase_key(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    """Адресация мягкая: `trk-1` находит ту же задачу, что и `TRK-1`."""
    await make_issue()

    response = await auth_client.get("/api/v1/issues/trk-1")

    assert response.status_code == 200
    assert response.json()["data"]["key"] == "TRK-1"


async def test_unknown_issue_is_a_domain_not_found(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.get("/api/v1/issues/TRK-404")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "issue_not_found"


async def test_malformed_key_explains_the_expected_format(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.get("/api/v1/issues/TRK-007")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_issue_key"
    assert error["details"]["expected"] == "<QUEUE>-<number>"


async def test_empty_listing_is_an_empty_collection_not_an_empty_body(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.get("/api/v1/issues")

    assert response.json() == {"data": [], "meta": {"next_cursor": None, "has_more": False}}


async def test_listing_pages_with_a_cursor(auth_client: AsyncClient, make_issue: MakeIssue) -> None:
    """Курсор берётся из общей пагинации: свой формат разошёлся бы с остальными коллекциями.

    Проверяются полнота и отсутствие пересечения страниц, а не конкретный порядок
    ключей. Причина в `now()`: это время начала транзакции, поэтому у всех задач,
    созданных внутри одного теста, `created_at` совпадает, и сортировка по паре
    `(created_at, id)` вырождается в сортировку по случайным UUID (см. `docs/notes/db.md`).
    Ради этого случая пара в ключе сортировки и нужна — без неё страницы теряли бы записи.
    """
    for _ in range(3):
        await make_issue()

    body = (await auth_client.get("/api/v1/issues", params={"limit": 2})).json()
    assert len(body["data"]) == 2
    assert body["meta"]["has_more"] is True

    second = await auth_client.get("/api/v1/issues", params={"cursor": body["meta"]["next_cursor"]})
    tail = second.json()
    assert tail["meta"]["has_more"] is False

    seen = [item["key"] for item in body["data"]] + [item["key"] for item in tail["data"]]
    assert sorted(seen) == ["TRK-1", "TRK-2", "TRK-3"]


async def test_listing_is_filtered_by_queue(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    await make_issue()
    await auth_client.post("/api/v1/queues", json={"key": "OPS", "name": "Эксплуатация"})
    await auth_client.post("/api/v1/issues", json={"queue": "OPS", "summary": "Чужая"})

    response = await auth_client.get("/api/v1/issues", params={"queue": "OPS"})

    assert [item["key"] for item in response.json()["data"]] == ["OPS-1"]


# --- Частичное обновление --------------------------------------------------------


async def test_patch_touches_only_the_given_fields(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    await make_issue(description="Исходное описание")

    response = await auth_client.patch("/api/v1/issues/TRK-1", json={"summary": "Новое название"})

    body = response.json()["data"]
    assert body["summary"] == "Новое название"
    assert body["description"] == "Исходное описание"
    assert body["version"] == 2


async def test_null_in_the_body_clears_the_field(
    auth_client: AsyncClient, make_issue: MakeIssue, owner_secret: str
) -> None:
    """Ровно то место, ради которого различаются «не передано» и «передано как null»."""
    await make_issue()
    await auth_client.put("/api/v1/issues/TRK-1/assignee", json={"assignee": "owner"})

    response = await auth_client.patch("/api/v1/issues/TRK-1", json={"assignee": None})

    assert response.json()["data"]["assignee"] is None


async def test_null_is_rejected_where_it_has_no_meaning(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    """У названия нет осмысленного `null`, и схема не даёт его прислать."""
    await make_issue()

    response = await auth_client.patch("/api/v1/issues/TRK-1", json={"summary": None})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_stale_version_is_a_conflict(auth_client: AsyncClient, make_issue: MakeIssue) -> None:
    await make_issue()
    await auth_client.patch("/api/v1/issues/TRK-1", json={"summary": "Первое"})

    response = await auth_client.patch(
        "/api/v1/issues/TRK-1", json={"summary": "Второе", "version": 1}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["actual"] == 2


async def test_unknown_field_in_the_body_is_rejected(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    """`extra="forbid"`: опечатка в имени поля не должна проходить молча."""
    await make_issue()

    response = await auth_client.patch("/api/v1/issues/TRK-1", json={"summry": "Опечатка"})

    assert response.status_code == 422


# --- Исполнитель и наблюдатели ---------------------------------------------------


async def test_assignee_is_set_and_cleared(auth_client: AsyncClient, make_issue: MakeIssue) -> None:
    await make_issue()

    assigned = await auth_client.put("/api/v1/issues/TRK-1/assignee", json={"assignee": "owner"})
    assert assigned.json()["data"]["assignee"] == "owner"

    cleared = await auth_client.put("/api/v1/issues/TRK-1/assignee", json={"assignee": None})
    assert cleared.json()["data"]["assignee"] is None


async def test_followers_are_added_and_removed(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    await make_issue()

    added = await auth_client.post("/api/v1/issues/TRK-1/followers", json={"actor": "owner"})
    assert added.json()["data"]["followers"] == ["owner"]

    removed = await auth_client.delete("/api/v1/issues/TRK-1/followers/owner")
    assert removed.status_code == 204

    remaining = await auth_client.get("/api/v1/issues/TRK-1")
    assert remaining.json()["data"]["followers"] == []


# --- Удаление --------------------------------------------------------------------


async def test_deleted_issue_answers_204_and_then_404(
    auth_client: AsyncClient, make_issue: MakeIssue
) -> None:
    await make_issue()

    deleted = await auth_client.delete("/api/v1/issues/TRK-1")
    assert deleted.status_code == 204
    assert deleted.content == b""

    assert (await auth_client.get("/api/v1/issues/TRK-1")).status_code == 404


# --- Доступ ----------------------------------------------------------------------


async def test_issues_require_a_token(client: AsyncClient, queue: Queue) -> None:
    """Аутентификация висит на роутере версии, поэтому новый маршрут защищён сам собой."""
    response = await client.get("/api/v1/issues")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
