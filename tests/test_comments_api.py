"""Эндпоинты обсуждения: оболочка ответа, упоминания, плашка удалённой реплики.

Проверяется контракт, который увидит фронтенд: единая оболочка, `body: null` у
удалённого комментария вместо его исчезновения из ленты, доменные отказы своими кодами.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.domain.actors import ActorType
from app.services import actors as actors_service


async def _create_issue(client: AsyncClient, summary: str = "Починить выдачу ключей") -> str:
    response = await client.post("/api/v1/issues", json={"queue": "TRK", "summary": summary})
    assert response.status_code == 201, response.text
    return response.json()["data"]["key"]


async def _comment(client: AsyncClient, issue: str, body: str) -> dict:
    response = await client.post(f"/api/v1/issues/{issue}/comments", json={"body": body})
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_a_comment_comes_back_wrapped_with_its_author_and_mentions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    queue: object,
    owner: Actor,
) -> None:
    """Оболочка `data`, автор ключом, упоминания отдельным полем."""
    await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="release_bot",
        display_name="Release bot",
    )
    issue = await _create_issue(auth_client)

    created = await _comment(auth_client, issue, "@release_bot собери, @nobody не в счёт")

    assert created["author"] == "owner"
    assert created["issue"] == issue
    assert created["mentions"] == ["release_bot"]
    assert created["is_deleted"] is False
    assert created["edited_at"] is None

    response = await auth_client.get(f"/api/v1/issues/{issue}/comments")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"] == {"next_cursor": None, "has_more": False}
    assert [item["id"] for item in body["data"]] == [created["id"]]


async def test_an_empty_comment_is_refused_by_the_schema(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client)

    response = await auth_client.post(f"/api/v1/issues/{issue}/comments", json={"body": ""})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_editing_replaces_the_text_and_marks_the_comment(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client)
    created = await _comment(auth_client, issue, "Было")

    response = await auth_client.patch(
        f"/api/v1/issues/{issue}/comments/{created['id']}",
        json={"body": "Стало"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["body"] == "Стало"
    assert data["edited_at"] is not None


async def test_a_deleted_comment_stays_in_the_feed_without_its_text(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Плашка вместо дыры: соседние реплики сохраняют контекст обсуждения."""
    issue = await _create_issue(auth_client)
    created = await _comment(auth_client, issue, "Ошибочная реплика")

    deleted = await auth_client.delete(f"/api/v1/issues/{issue}/comments/{created['id']}")
    assert deleted.status_code == 204, deleted.text

    response = await auth_client.get(f"/api/v1/issues/{issue}/comments")
    item = response.json()["data"][0]
    assert item["id"] == created["id"]
    assert item["body"] is None
    assert item["is_deleted"] is True
    assert item["mentions"] == []


async def test_deleting_twice_is_a_conflict(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Повтор здесь не идемпотентен: клиент видит не то состояние, и молчать об этом нельзя."""
    issue = await _create_issue(auth_client)
    created = await _comment(auth_client, issue, "Реплика")
    await auth_client.delete(f"/api/v1/issues/{issue}/comments/{created['id']}")

    response = await auth_client.delete(f"/api/v1/issues/{issue}/comments/{created['id']}")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "comment_deleted"


async def test_a_comment_of_another_issue_answers_not_found(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """«Есть, но не в этой задаче» для клиента то же самое, что «нет»."""
    discussed = await _create_issue(auth_client, "Первая")
    other = await _create_issue(auth_client, "Вторая")
    created = await _comment(auth_client, discussed, "Реплика")

    response = await auth_client.patch(
        f"/api/v1/issues/{other}/comments/{created['id']}",
        json={"body": "Правка"},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "comment_not_found"


async def test_the_feed_pages_with_a_cursor(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Лента листается общим механизмом проекта: курсор по паре `(created_at, id)`.

    Проверяются полнота страниц и отсутствие пересечения, а не конкретный порядок:
    отметка времени у комментариев одной транзакции идёт вперёд, но полагаться в тесте
    на её разрешение не стоит.
    """
    issue = await _create_issue(auth_client)
    for number in range(3):
        await _comment(auth_client, issue, f"Реплика {number}")

    first = await auth_client.get(f"/api/v1/issues/{issue}/comments?limit=2")
    body = first.json()
    assert len(body["data"]) == 2
    assert body["meta"]["has_more"] is True

    second = await auth_client.get(
        f"/api/v1/issues/{issue}/comments?limit=2&cursor={body['meta']['next_cursor']}"
    )
    rest = second.json()
    assert len(rest["data"]) == 1
    assert rest["meta"]["has_more"] is False
    seen = {item["body"] for item in body["data"] + rest["data"]}
    assert seen == {"Реплика 0", "Реплика 1", "Реплика 2"}
