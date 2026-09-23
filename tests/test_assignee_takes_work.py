"""В работу задачу берёт её исполнитель (TRK-123, `CONCEPT.md`, 3.3).

Обзорная проверка 1 задачи через REST и через MCP: без исполнителя — `assignee_required`,
с другим исполнителем — `assignee_mismatch` и оба имени в `details`, совпавшая подпись —
имя участника или метка временного агента — проходит. Отказ не подшивает в дело ничего
и статуса не меняет.

Токены настоящие: подпись берётся из аутентификации, а не из структуры автора,
собранной тестом, — иначе проверялось бы сравнение строк, а не то, кого трекер считает
просящим.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import Connect, call, refuse

from app.db.models.queue import Queue
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR

READY: dict[str, Any] = {
    "queue": "TRK",
    "title": "Починить выдачу ключей задач",
    "description": "Ключ выдаётся до валидации и сгорает на неудачном запросе",
    "goal": "Ключи не сгорают",
    "context": "Номер выдаёт счётчик очереди",
    "constraints": "Счётчик не переписывать",
    "output": "Тест на несгоревший номер",
    "checks": ["Создание задачи без названия не тратит номер"],
}

SECTIONS = {key: READY[key] for key in ("goal", "context", "constraints", "output", "checks")}


@pytest.fixture
async def alice_secret(db_session: AsyncSession) -> str:
    """Второй участник со своим токеном: «другой исполнитель» в отказе."""
    alice = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="alice"
    )
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=alice, scope=TokenScope.TASK, name="alice"
    )
    return issued.secret


# --- REST -----------------------------------------------------------------------------


async def _opened(client: AsyncClient, **overrides: Any) -> str:
    created = await client.post("/api/v1/tasks", json={**READY, **overrides})
    assert created.status_code == 201, created.text
    key = str(created.json()["data"]["key"])
    opened = await client.post(f"/api/v1/tasks/{key}/transition", json={"to": "open"})
    assert opened.status_code == 200, opened.text
    return key


async def _state(client: AsyncClient, key: str) -> tuple[str, int, int]:
    """Статус, версия и длина дела: всё, что отказ обязан оставить как было."""
    card = await client.get(f"/api/v1/tasks/{key}")
    assert card.status_code == 200, card.text
    entries = await client.get(f"/api/v1/tasks/{key}/entries", params={"limit": 200})
    assert entries.status_code == 200, entries.text
    data = card.json()["data"]["task"]
    return data["status"], data["version"], len(entries.json()["data"])


async def _take(client: AsyncClient, key: str) -> Any:
    return await client.post(f"/api/v1/tasks/{key}/transition", json={"to": "in_progress"})


async def test_rest_refuses_a_task_without_an_assignee(
    auth_client: AsyncClient, queue: Queue
) -> None:
    key = await _opened(auth_client)
    before = await _state(auth_client, key)

    refused = await _take(auth_client, key)

    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "assignee_required"
    assert error["details"] == {"key": key, "from": "open", "to": "in_progress"}
    assert await _state(auth_client, key) == before


async def test_rest_refuses_someone_other_than_the_assignee(
    auth_client: AsyncClient, queue: Queue
) -> None:
    key = await _opened(auth_client, assignee="alice")
    before = await _state(auth_client, key)

    refused = await _take(auth_client, key)

    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "assignee_mismatch"
    assert error["details"]["assignee"] == "alice"
    assert error["details"]["requester"] == "owner"
    assert await _state(auth_client, key) == before


async def test_rest_lets_the_assignee_in_whatever_the_case(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Подпись канонична, `assignee` — свободная строка: `Owner` тот же участник."""
    key = await _opened(auth_client, assignee="Owner")

    taken = await _take(auth_client, key)

    assert taken.status_code == 200, taken.text
    assert taken.json()["data"]["status"] == "in_progress"


async def test_rest_lets_a_temporary_agent_in_by_its_label(
    auth_client: AsyncClient, shared_secret: str, queue: Queue
) -> None:
    """Метка временного агента сравнивается так же, как имя участника."""
    key = await _opened(auth_client, assignee="nightly_agent")
    auth_client.headers["Authorization"] = f"Bearer {shared_secret}"

    auth_client.headers["X-Actor-Label"] = "someone_else"
    refused = await _take(auth_client, key)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"]["requester"] == "someone_else"

    auth_client.headers["X-Actor-Label"] = "Nightly_Agent"
    taken = await _take(auth_client, key)
    assert taken.status_code == 200, taken.text

    last = (await auth_client.get(f"/api/v1/tasks/{key}/entries", params={"limit": 200})).json()
    assert last["data"][-1]["author"] == {"kind": "agent", "signature": "nightly_agent"}


# --- MCP ------------------------------------------------------------------------------


async def _index_length(session: Any, key: str) -> tuple[str, int]:
    package = await call(session, "get_task", key=key)
    return package["task"]["status"], len(package["index"])


async def test_mcp_refuses_without_an_assignee_and_for_another_one(
    mcp_session: Connect, task_secret: str, alice_secret: str, queue: Queue
) -> None:
    del queue
    async with mcp_session(task_secret) as session:
        created = await call(
            session,
            "create_task",
            queue="TRK",
            title="Без исполнителя",
            description="Есть",
            sections=SECTIONS,
        )
        key = str(created["key"])
        await call(session, "transition", key=key, to="open")
        before = await _index_length(session, key)

        unassigned = await refuse(session, "transition", key=key, to="in_progress")
        assert "assignee_required" in unassigned
        assert await _index_length(session, key) == before

        await call(session, "update_task", key=key, changes={"assignee": "owner"})
        before = await _index_length(session, key)

    async with mcp_session(alice_secret) as session:
        foreign = await refuse(session, "transition", key=key, to="in_progress")
        assert "assignee_mismatch" in foreign
        assert '"assignee": "owner"' in foreign
        assert '"requester": "alice"' in foreign
        assert await _index_length(session, key) == before

    async with mcp_session(task_secret) as session:
        taken = await call(session, "transition", key=key, to="in_progress")
        assert taken["status"] == "in_progress"


async def test_mcp_lets_a_temporary_agent_in_by_its_label(
    mcp_session: Connect, task_secret: str, shared_secret: str, queue: Queue
) -> None:
    del queue
    async with mcp_session(task_secret) as session:
        created = await call(
            session,
            "create_task",
            queue="TRK",
            title="Под метку",
            description="Есть",
            sections=SECTIONS,
            assignee="nightly_agent",
        )
        key = str(created["key"])
        await call(session, "transition", key=key, to="open")

    async with mcp_session(shared_secret, label="nightly_agent") as session:
        taken = await call(session, "transition", key=key, to="in_progress")
        assert taken["status"] == "in_progress"
