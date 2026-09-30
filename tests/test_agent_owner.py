"""Хозяин агента: `agent_of`, выпуск ключа чужому агенту, поле `owner` в REST (TRK-476).

Решение `TRK-475#14`: у агента человека имя `<клиент>_<человек>`, а ключ чужого агента
выпускает только администратор.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.domain.participants import ParticipantKind
from app.services import accounts as accounts_service
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR

PASSWORD = "correct horse battery staple"


async def _person(db_session: AsyncSession, name: str) -> Participant:
    created = await accounts_service.create_account(
        db_session,
        actor=TRACKER_ACTOR,
        email=f"{name}@example.com",
        name=name,
        password=PASSWORD,
    )
    return created.account.participant


async def _secret(db_session: AsyncSession, person: Participant) -> dict[str, str]:
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=person, name="session"
    )
    return {"Authorization": f"Bearer {issued.secret}"}


async def test_agent_of_finds_or_creates_the_agent_of_a_person(db_session: AsyncSession) -> None:
    alice = await _person(db_session, "alice")
    bob = await _person(db_session, "bob")

    first = await participants_service.agent_of(db_session, client="claude", owner=alice)
    again = await participants_service.agent_of(db_session, client="claude", owner=alice)
    other = await participants_service.agent_of(db_session, client="claude", owner=bob)
    generic = await participants_service.agent_of(db_session, client="cursor", owner=alice)
    codex = await participants_service.agent_of(db_session, client="Codex", owner=alice)

    assert first.name == "claude_alice"
    assert again.id == first.id
    assert first.kind is ParticipantKind.AGENT
    assert first.owner_id == alice.id
    assert first.created_by_signature == "alice"
    assert other.name == "claude_bob" and other.owner_id == bob.id
    assert generic.name == "agent_alice"
    assert codex.name == "codex_alice"


async def test_a_name_held_by_someone_else_gets_a_numbered_suffix(
    db_session: AsyncSession,
) -> None:
    alice = await _person(db_session, "alice")
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="claude_alice"
    )

    agent = await participants_service.agent_of(db_session, client="claude", owner=alice)
    repeated = await participants_service.agent_of(db_session, client="claude", owner=alice)

    assert agent.name == "claude_alice_2"
    assert agent.owner_id == alice.id
    assert repeated.id == agent.id


async def test_a_long_name_is_cut_to_the_limit(db_session: AsyncSession) -> None:
    person = await _person(db_session, "p" + "x" * 62)

    agent = await participants_service.agent_of(db_session, client="claude", owner=person)
    taken = await participants_service.agent_of(db_session, client="codex", owner=person)

    assert len(agent.name) == 64 and agent.name.startswith("claude_p")
    assert len(taken.name) == 64 and taken.name.startswith("codex_p")


async def test_issuing_to_a_foreign_agent_is_refused_with_a_new_code(
    client: AsyncClient, auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    alice = await _person(db_session, "alice")
    bob = await _person(db_session, "bob")
    await participants_service.agent_of(db_session, client="claude", owner=alice)
    await participants_service.agent_of(db_session, client="claude", owner=bob)
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="claude"
    )
    headers = await _secret(db_session, alice)

    own = await client.post(
        "/api/v1/tokens", json={"name": "k", "participant": "claude_alice"}, headers=headers
    )
    foreign = await client.post(
        "/api/v1/tokens", json={"name": "k", "participant": "claude_bob"}, headers=headers
    )
    ownerless = await client.post(
        "/api/v1/tokens", json={"name": "k", "participant": "claude"}, headers=headers
    )
    by_admin = await auth_client.post(
        "/api/v1/tokens", json={"name": "k", "participant": "claude_bob"}
    )

    assert own.status_code == 201, own.text
    assert foreign.status_code == 403
    error = foreign.json()["error"]
    assert error["code"] == "agent_owned_by_another"
    assert error["details"] == {
        "action": "token.issue",
        "agent": "claude_bob",
        "owner": "bob",
    }
    assert ownerless.status_code == 201, ownerless.text
    assert by_admin.status_code == 201, by_admin.text


async def test_participants_list_shows_the_owner(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    alice = await _person(db_session, "alice")
    await participants_service.agent_of(db_session, client="claude", owner=alice)

    listed = await auth_client.get("/api/v1/participants")
    bootstrap = await auth_client.get("/api/v1/bootstrap")

    owners = {item["name"]: item["owner"] for item in listed.json()["data"]}
    assert owners["claude_alice"] == "alice"
    assert owners["alice"] is None
    assert bootstrap.json()["data"]["participant"]["owner"] is None
