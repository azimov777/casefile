"""REST настроек установки (TRK-744): список всем вошедшим, правка администратору, запись
«кто и когда изменил»."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.participants import ParticipantKind
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR

SETTINGS = "/api/v1/settings"
PAGE_SIZE = f"{SETTINGS}/mcp_page_size"
CREATE_BOB = {"email": "bob@example.com", "name": "bob", "password": "correct horse battery staple"}


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TRACKER_MCP_PAGE_SIZE", "TRACKER_RELEASE_CHECK"):
        monkeypatch.delenv(name, raising=False)


def row(listing: dict, name: str) -> dict:
    found: dict = next(item for item in listing["data"] if item["name"] == name)
    return found


async def test_a_signed_in_person_reads_the_seven_settings(auth_client: AsyncClient) -> None:
    response = await auth_client.get(SETTINGS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 7
    page = row(body, "mcp_page_size")
    assert page == {
        "name": "mcp_page_size",
        "env_var": "TRACKER_MCP_PAGE_SIZE",
        "kind": "integer",
        "value": None,
        "effective_value": "25",
        "source": "default",
        "default_value": "25",
        "default_source": "default",
        "minimum": 1,
        "maximum": 200,
        "updated_by": None,
        "updated_at": None,
    }


async def test_reading_without_signing_in_is_refused(client: AsyncClient) -> None:
    response = await client.get(SETTINGS)

    assert response.status_code == 401


async def test_an_administrator_changes_a_setting_and_the_list_shows_it_and_who(
    auth_client: AsyncClient,
) -> None:
    patched = await auth_client.patch(PAGE_SIZE, json={"value": 10})

    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["effective_value"] == "10"
    listed = row((await auth_client.get(SETTINGS)).json(), "mcp_page_size")
    assert listed["effective_value"] == "10"
    assert listed["source"] == "database"
    assert listed["value"] == "10"
    assert listed["updated_by"] == {"kind": "human", "signature": "owner"}
    assert listed["updated_at"] is not None


async def test_an_empty_value_returns_the_setting_to_the_environment_or_the_default(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await auth_client.patch(PAGE_SIZE, json={"value": "10"})

    back = await auth_client.patch(PAGE_SIZE, json={"value": ""})
    assert back.json()["data"]["source"] == "default"
    assert back.json()["data"]["value"] is None
    assert back.json()["data"]["updated_by"] == {"kind": "human", "signature": "owner"}

    monkeypatch.setenv("TRACKER_MCP_PAGE_SIZE", "40")
    again = await auth_client.patch(PAGE_SIZE, json={"value": None})
    data = again.json()["data"]
    assert (data["source"], data["effective_value"]) == ("environment", "40")
    assert (data["default_source"], data["default_value"]) == ("environment", "40")


async def test_a_boolean_and_a_number_in_the_wrong_form_are_checked_by_the_registry(
    auth_client: AsyncClient,
) -> None:
    flag = await auth_client.patch(f"{SETTINGS}/release_check", json={"value": False})
    assert flag.json()["data"]["effective_value"] == "false"

    too_big = await auth_client.patch(PAGE_SIZE, json={"value": 201})
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "installation_setting_invalid"
    assert too_big.json()["error"]["details"]["reason"] == "too_large"
    words = await auth_client.patch(PAGE_SIZE, json={"value": "many"})
    assert words.json()["error"]["details"]["reason"] == "not_an_integer"
    listed = row((await auth_client.get(SETTINGS)).json(), "mcp_page_size")
    assert listed["source"] == "default"


async def test_an_unknown_name_is_refused(auth_client: AsyncClient) -> None:
    response = await auth_client.patch(f"{SETTINGS}/secret_key", json={"value": "1"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "installation_setting_not_found"


async def test_an_account_without_the_admin_flag_reads_but_cannot_change(
    auth_client: AsyncClient,
) -> None:
    created = await auth_client.post("/api/v1/accounts", json=CREATE_BOB)
    assert created.status_code == 201, created.text
    signed = await auth_client.post(
        "/api/v1/session",
        json={"email": CREATE_BOB["email"], "password": CREATE_BOB["password"]},
        headers={"Authorization": ""},
    )
    secret = signed.json()["data"]["token"]
    auth_client.cookies.clear()

    read = await auth_client.get(SETTINGS, headers=bearer(secret))
    refused = await auth_client.patch(PAGE_SIZE, json={"value": 10}, headers=bearer(secret))
    unknown = await auth_client.patch(f"{SETTINGS}/nope", json={"value": 1}, headers=bearer(secret))

    assert read.status_code == 200
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "admin_required"
    assert unknown.json()["error"]["code"] == "admin_required"
    listed = row((await auth_client.get(SETTINGS)).json(), "mcp_page_size")
    assert listed["source"] == "default"


async def test_an_agent_key_reads_but_cannot_change(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    agent = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=agent, name="helper"
    )

    refused = await client.patch(PAGE_SIZE, json={"value": 10}, headers=bearer(issued.secret))

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "admin_required"
