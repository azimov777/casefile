"""Эндпоинт вопросов: «входящая» участника поперёк задач.

Вопрос — не отдельная сущность, а представление над делом, поэтому проверяется здесь
именно то, что из дела считается: открытость, адресат, признак `blocking`, очередь.
"""

from typing import Any

from httpx import AsyncClient
from tests.test_case_api import append, create

from app.db.models.queue import Queue


async def register(client: AsyncClient, name: str) -> None:
    response = await client.post(
        "/api/v1/participants",
        json={"kind": "agent", "name": name, "description": "Проверяющий"},
    )
    assert response.status_code == 201, response.text


async def ask(client: AsyncClient, key: str, title: str, *, to: str, blocking: bool) -> int:
    entry = await append(
        client,
        key,
        type="question",
        title=title,
        payload={"addressees": [to], "blocking": blocking},
    )
    return entry["no"]


async def questions(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/questions", params=params)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert sorted(payload) == ["data", "meta"]
    return payload["data"]


async def test_the_inbox_keeps_the_open_blocking_questions_of_the_current_participant(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 9."""
    await register(auth_client, "reviewer")
    await create(auth_client)
    blocking_no = await ask(auth_client, "TRK-1", "Ждёт ответа", to="owner", blocking=True)
    await ask(auth_client, "TRK-1", "Ждать не нужно", to="owner", blocking=False)
    await ask(auth_client, "TRK-1", "Чужой", to="reviewer", blocking=True)

    blocking = await questions(auth_client, blocking=True)
    assert [question["title"] for question in blocking] == ["Ждёт ответа"]
    assert blocking[0]["task_key"] == "TRK-1"
    assert blocking[0]["payload"] == {"addressees": ["owner"], "blocking": True}

    assert [question["title"] for question in await questions(auth_client)] == [
        "Ждёт ответа",
        "Ждать не нужно",
    ]

    await append(
        auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": blocking_no}
    )

    assert await questions(auth_client, blocking=True) == []
    assert [question["title"] for question in await questions(auth_client)] == ["Ждать не нужно"]


async def test_the_answered_questions_are_readable_too(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """`open=false` — вторая половина выдачи; «все вопросы задачи» читаются из её дела."""
    await create(auth_client)
    no = await ask(auth_client, "TRK-1", "Ждёт ответа", to="owner", blocking=False)
    await append(auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": no})

    assert await questions(auth_client) == []
    assert [question["title"] for question in await questions(auth_client, open=False)] == [
        "Ждёт ответа"
    ]


async def test_the_inbox_is_filtered_by_addressee_and_queue(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await register(auth_client, "reviewer")
    created = await auth_client.post(
        "/api/v1/queues", json={"key": "OPS", "title": "Эксплуатация", "description": ""}
    )
    assert created.status_code == 201, created.text
    await create(auth_client)
    await create(auth_client, queue="OPS")
    await ask(auth_client, "TRK-1", "Вопрос в TRK", to="reviewer", blocking=False)
    await ask(auth_client, "OPS-1", "Вопрос в OPS", to="reviewer", blocking=False)

    # Адресация мягкая по регистру — как и везде, где адресуют по имени.
    assert [q["title"] for q in await questions(auth_client, addressee="Reviewer")] == [
        "Вопрос в TRK",
        "Вопрос в OPS",
    ]
    assert [
        q["title"] for q in await questions(auth_client, addressee="reviewer", queue="ops")
    ] == ["Вопрос в OPS"]
    assert await questions(auth_client) == []


async def test_an_unknown_addressee_is_a_refusal_rather_than_an_empty_inbox(
    auth_client: AsyncClient, queue: Queue
) -> None:
    response = await auth_client.get("/api/v1/questions", params={"addressee": "ghost"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "participant_not_found"


async def test_a_shared_agent_token_must_name_the_addressee(
    client: AsyncClient, shared_secret: str, queue: Queue
) -> None:
    """У временного агента адресата нет: пустой список соврал бы, что вопросов не пришло."""
    client.headers["Authorization"] = f"Bearer {shared_secret}"
    client.headers["X-Actor-Label"] = "nightly_agent"

    refused = await client.get("/api/v1/questions")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "actor_not_addressable"

    named = await client.get("/api/v1/questions", params={"addressee": "owner"})
    assert named.status_code == 200, named.text
    assert named.json()["data"] == []
