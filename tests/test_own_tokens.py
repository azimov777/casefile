"""Свои токены: человек выпускает их своим агентам, видит и отзывает только свои (TRK-114).

`docs/CONCEPT.md`, 3.1 и 5.4; решения `TRK-114#12` (что такое «свой») и `TRK-114#13`
(что отключение человека делает с его агентами). Люди входят настоящим
`POST /api/v1/session`, агент ходит в настоящий MCP-сервер теста: проверяется вся цепочка
«вошёл — выпустил — агент работает — отозвал — агент отклонён».
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import Connect, call, refuse

from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.domain.participants import ParticipantKind
from app.domain.passwords import hash_password
from app.domain.tokens import TokenScope
from app.services import accounts as accounts_module
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, authenticate

ACCOUNTS = "/api/v1/accounts"
SESSION = "/api/v1/session"
TOKENS = "/api/v1/tokens"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def cheap_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Дешёвый хеш новых паролей: цена scrypt логике токенов безразлична."""
    monkeypatch.setattr(
        accounts_module, "hash_password", lambda password: hash_password(password, n=16, r=1, p=1)
    )


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def person(client: AsyncClient, name: str) -> str:
    """Заводит человека без флага администратора и отдаёт токен его сеанса."""
    email = f"{name}@example.com"
    created = await client.post(ACCOUNTS, json={"email": email, "name": name, "password": PASSWORD})
    assert created.status_code == 201, created.text
    signed = await client.post(
        SESSION, json={"email": email, "password": PASSWORD}, headers={"Authorization": ""}
    )
    assert signed.status_code == 200, signed.text
    client.cookies.clear()
    token: str = signed.json()["data"]["token"]
    return token


async def issue(client: AsyncClient, secret: str, **body: Any) -> dict[str, Any]:
    response = await client.post(TOKENS, json=body, headers=bearer(secret))
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def listed_ids(client: AsyncClient, secret: str, **params: Any) -> set[str]:
    response = await client.get(TOKENS, headers=bearer(secret), params=params)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["data"]}


@pytest.fixture
async def alice(auth_client: AsyncClient) -> str:
    return await person(auth_client, "alice")


@pytest.fixture
async def bob(auth_client: AsyncClient) -> str:
    return await person(auth_client, "bob")


@pytest.fixture
async def agent(db_session: AsyncSession) -> Participant:
    """Агент-участник, которому люди выпускают ключи."""
    return await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )


# --- Проверка 1: два человека, у каждого свои ------------------------------------------


async def test_two_people_see_only_their_own_tokens_and_cannot_revoke_each_other(
    auth_client: AsyncClient, alice: str, bob: str, agent: Participant
) -> None:
    """Обзорная проверка 1."""
    alices = await issue(auth_client, alice, name="alice laptop", participant=agent.name)
    bobs = await issue(auth_client, bob, name="bob ci")

    assert alices["name"] == "alice laptop"
    assert alices["created_by"] == {"kind": "human", "signature": "alice"}
    alice_sees = await listed_ids(auth_client, alice)
    bob_sees = await listed_ids(auth_client, bob)
    assert alices["id"] in alice_sees and bobs["id"] not in alice_sees
    assert bobs["id"] in bob_sees and alices["id"] not in bob_sees

    refused = await auth_client.delete(f"{TOKENS}/{alices['id']}", headers=bearer(bob))

    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "permission_denied"
    assert refused.json()["error"]["details"] == {
        "action": "token.revoke",
        "reason": "not_own_token",
    }
    still = await auth_client.get("/api/v1/bootstrap", headers=bearer(alices["secret"]))
    assert still.status_code == 200, "a refused revoke must leave the token working"


async def test_own_tokens_include_the_ones_that_speak_for_the_person(
    auth_client: AsyncClient, alice: str, main_secret: str
) -> None:
    """Ключ, выданный администратором от имени человека, — тоже его: он его видит и отзывает."""
    given = await issue(auth_client, main_secret, name="given", participant="alice")

    seen = await listed_ids(auth_client, alice)

    assert given["id"] in seen
    revoked = await auth_client.delete(f"{TOKENS}/{given['id']}", headers=bearer(alice))
    assert revoked.status_code == 204


async def test_a_person_cannot_issue_a_token_that_speaks_for_someone_else(
    auth_client: AsyncClient, alice: str, bob: str
) -> None:
    refused = await auth_client.post(
        TOKENS, json={"name": "fake", "participant": "bob"}, headers=bearer(alice)
    )
    for_self = await auth_client.post(
        TOKENS, json={"name": "mine", "participant": "alice"}, headers=bearer(alice)
    )
    shared = await auth_client.post(TOKENS, json={"name": "shared"}, headers=bearer(alice))

    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {
        "action": "token.issue",
        "reason": "foreign_human",
    }
    assert (for_self.status_code, shared.status_code) == (201, 201)


async def test_an_agent_with_a_main_token_issues_no_tokens(
    client: AsyncClient, agent: Participant, db_session: AsyncSession
) -> None:
    """Выдача доступов остаётся за человеком: у агента нет учётной записи."""
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=agent, scope=TokenScope.MAIN, name="main"
    )

    refused = await client.post(TOKENS, json={"name": "child"}, headers=bearer(issued.secret))
    own = await client.get(TOKENS, headers=bearer(issued.secret))

    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {
        "action": "token.issue",
        "reason": "account_required",
    }
    assert [item["id"] for item in own.json()["data"]] == [str(issued.token.id)]


# --- Проверка 2: агент работает выпущенным токеном, после отзыва — нет ----------------


async def test_an_agent_works_over_mcp_with_the_issued_token_until_it_is_revoked(
    auth_client: AsyncClient, alice: str, agent: Participant, queue: Queue, mcp_session: Connect
) -> None:
    """Обзорная проверка 2: следующий же вызов после отзыва отклоняется."""
    issued = await issue(auth_client, alice, name="alice agent", participant=agent.name)

    async with mcp_session(issued["secret"]) as session:
        created = await call(
            session, "create_task", queue=queue.key, title="От агента", description="Проверка"
        )
        assert created["key"].startswith(queue.key)

        revoked = await auth_client.delete(f"{TOKENS}/{issued['id']}", headers=bearer(alice))
        assert revoked.status_code == 204

        failure = await refuse(session, "list_queues")

    assert "unauthorized" in failure
    assert "token_revoked" in failure


# --- Проверка 3: администратор видит и отзывает все ------------------------------------


async def test_the_administrator_sees_and_revokes_every_token(
    auth_client: AsyncClient, alice: str, bob: str, main_secret: str
) -> None:
    """Обзорная проверка 3. Владелец из общей фикстуры — администратор."""
    alices = await issue(auth_client, alice, name="alice agent")
    bobs = await issue(auth_client, bob, name="bob agent")

    everything = await listed_ids(auth_client, main_secret)
    own = await listed_ids(auth_client, main_secret, mine="true")

    assert {alices["id"], bobs["id"]} <= everything
    assert alices["id"] not in own and bobs["id"] not in own
    revoked = await auth_client.delete(f"{TOKENS}/{bobs['id']}", headers=bearer(main_secret))
    assert revoked.status_code == 204
    dead = await auth_client.get("/api/v1/bootstrap", headers=bearer(bobs["secret"]))
    assert dead.json()["error"]["details"] == {"reason": "token_revoked"}


# --- Проверка 4: отключение человека гасит его агентов ----------------------------------


async def account_id(client: AsyncClient, email: str) -> str:
    for item in (await client.get(ACCOUNTS)).json()["data"]:
        if item["email"] == email:
            identifier: str = item["id"]
            return identifier
    raise AssertionError(f"no account {email}")


async def test_disabling_a_person_stops_the_agents_and_enabling_does_not_revive_them(
    auth_client: AsyncClient,
    alice: str,
    bob: str,
    agent: Participant,
    queue: Queue,
    mcp_session: Connect,
) -> None:
    """Обзорная проверка 4, как записано в `TRK-114#13`, п. 1."""
    alices = await issue(auth_client, alice, name="alice agent", participant=agent.name)
    shared = await issue(auth_client, alice, name="alice shared")
    bobs = await issue(auth_client, bob, name="bob agent", participant=agent.name)
    alice_id = await account_id(auth_client, "alice@example.com")

    disabled = await auth_client.patch(f"{ACCOUNTS}/{alice_id}", json={"disabled": True})
    assert disabled.status_code == 200, disabled.text

    async with mcp_session(alices["secret"]) as session:
        failure = await refuse(session, "list_queues")
    assert "token_revoked" in failure
    async with mcp_session(shared["secret"], label="nightly") as session:
        failure = await refuse(session, "list_queues")
    assert "token_revoked" in failure
    async with mcp_session(bobs["secret"]) as session:
        await call(session, "list_queues")

    listed = (await auth_client.get(TOKENS)).json()["data"]
    revoked = {item["id"] for item in listed if item["revoked_at"] is not None}
    assert {alices["id"], shared["id"]} <= revoked
    assert bobs["id"] not in revoked

    await auth_client.patch(f"{ACCOUNTS}/{alice_id}", json={"disabled": False})
    still_dead = await auth_client.get("/api/v1/bootstrap", headers=bearer(alices["secret"]))
    assert still_dead.json()["error"]["details"] == {"reason": "token_revoked"}


async def test_a_token_issued_to_a_disabled_person_does_not_let_in_until_enabled(
    auth_client: AsyncClient, alice: str, db_session: AsyncSession
) -> None:
    """`TRK-114#13`, п. 2: риск из сводки TRK-113 — выпуск после отключения — закрыт."""
    alice_id = await account_id(auth_client, "alice@example.com")
    await auth_client.patch(f"{ACCOUNTS}/{alice_id}", json={"disabled": True})
    participant = await participants_service.get_participant(db_session, "alice")
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=participant, scope=TokenScope.MAIN, name="cli"
    )

    with pytest.raises(UnauthorizedError) as refusal:
        await authenticate(db_session, issued.secret)
    assert refusal.value.details == {"reason": "account_disabled"}

    await auth_client.patch(f"{ACCOUNTS}/{alice_id}", json={"disabled": False})
    actor = await authenticate(db_session, issued.secret)
    assert actor.author.signature == "alice"
