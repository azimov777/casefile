"""Учётные записи: управление людьми в REST и командой на сервере, пароли, отключение.

`docs/CONCEPT.md`, 3.1 и 5.4 (TRK-113). Владелец из общей фикстуры — администратор
`owner@localhost` без пароля, как у установки, заведшей себя сама; его токен набора `main`
стоит в `auth_client`. Вход людей идёт настоящим `POST /api/v1/session` того же
приложения: так проверяется вся цепочка «завёл — вошёл — подписал своим именем».
"""

import io
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.repositories import AccountRepository
from app.db.session import transaction
from app.domain.participants import ParticipantKind
from app.domain.passwords import MIN_PASSWORD_LENGTH, hash_password
from app.domain.tokens import TokenScope
from app.services import accounts as accounts_module
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR

ACCOUNTS = "/api/v1/accounts"
SESSION = "/api/v1/session"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def cheap_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Хеш новых паролей — дешёвый: логике учётных записей стоимость scrypt безразлична,
    она читает параметры из строки хеша, а полная цена стоила бы секунд на каждый тест."""
    monkeypatch.setattr(
        accounts_module, "hash_password", lambda password: hash_password(password, n=16, r=1, p=1)
    )


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def create(client: AsyncClient, **body: Any) -> Response:
    return await client.post(ACCOUNTS, json=body)


async def sign_in(client: AsyncClient, email: str, password: str) -> str:
    """Вход без куки в клиенте: токен сеанса из ответа — ключ этого человека."""
    response = await client.post(
        SESSION, json={"email": email, "password": password}, headers={"Authorization": ""}
    )
    assert response.status_code == 200, response.text
    client.cookies.clear()
    token: str = response.json()["data"]["token"]
    return token


# --- Заведение -------------------------------------------------------------------------


async def test_an_admin_creates_a_person_who_signs_in_with_the_generated_password(
    auth_client: AsyncClient,
) -> None:
    """Пароль, сгенерированный трекером, приходит один раз и пускает этого человека."""
    response = await create(auth_client, email="Bob@Example.com", name="bob")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["email"] == "bob@example.com"
    assert data["participant"] == "bob"
    assert data["is_admin"] is False
    assert data["has_password"] is True
    assert data["disabled_at"] is None
    assert data["created_by"] == {"kind": "human", "signature": "owner"}
    password = data["password"]
    assert len(password) >= MIN_PASSWORD_LENGTH

    token = await sign_in(auth_client, "bob@example.com", password)
    me = await auth_client.get("/api/v1/bootstrap", headers=bearer(token))
    assert me.json()["data"]["participant"] == {
        **me.json()["data"]["participant"],
        "name": "bob",
        "kind": "human",
    }
    listed = await auth_client.get(ACCOUNTS)
    assert all("password" not in item for item in listed.json()["data"])


async def test_a_typed_password_is_not_echoed_back(auth_client: AsyncClient) -> None:
    response = await create(auth_client, email="bob@example.com", name="bob", password=PASSWORD)

    assert response.status_code == 201, response.text
    assert response.json()["data"]["password"] is None
    await sign_in(auth_client, "bob@example.com", PASSWORD)


async def test_an_existing_human_without_an_account_gets_one(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Человек, заведённый до учётных записей, получает её под своим именем, а не нового."""
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.HUMAN, name="carol"
    )

    response = await create(auth_client, email="carol@example.com", name="Carol")
    participants = await auth_client.get("/api/v1/participants")

    assert response.status_code == 201, response.text
    assert response.json()["data"]["participant"] == "carol"
    assert [item["name"] for item in participants.json()["data"]].count("carol") == 1


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"email": "owner@localhost", "name": "bob"}, 409, "account_email_taken"),
        ({"email": "OWNER@localhost", "name": "bob"}, 409, "account_email_taken"),
        ({"email": "bob@example.com", "name": "owner"}, 409, "participant_has_account"),
        ({"email": "no-at-sign", "name": "bob"}, 422, "invalid_email"),
        ({"email": "two@@example.com", "name": "bob"}, 422, "invalid_email"),
        ({"email": "bob@example.com", "name": "bob", "password": "short"}, 422, "weak_password"),
    ],
)
async def test_creating_an_account_refuses_with_a_reason(
    auth_client: AsyncClient, body: dict[str, str], status: int, code: str
) -> None:
    response = await create(auth_client, **body)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


async def test_an_agent_gets_no_account(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="release_bot"
    )

    response = await create(auth_client, email="bot@example.com", name="release_bot")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "account_requires_human"


async def test_a_repeated_creation_with_the_same_key_answers_the_same_password(
    auth_client: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "create-bob"}
    body = {"email": "bob@example.com", "name": "bob"}

    first = await auth_client.post(ACCOUNTS, json=body, headers=headers)
    second = await auth_client.post(ACCOUNTS, json=body, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


# --- Кто вправе ------------------------------------------------------------------------


@pytest.fixture
async def bob_token(auth_client: AsyncClient) -> str:
    """Токен сеанса Боба — человека без флага администратора."""
    created = await create(auth_client, email="bob@example.com", name="bob", password=PASSWORD)
    assert created.status_code == 201, created.text
    return await sign_in(auth_client, "bob@example.com", PASSWORD)


async def test_only_an_administrator_manages_people(
    auth_client: AsyncClient, bob_token: str
) -> None:
    """Без флага — `403 admin_required` на каждом маршруте управления, с `main` тоже."""
    owner = (await auth_client.get(ACCOUNTS)).json()["data"][0]
    calls = [
        ("GET", ACCOUNTS, None),
        ("POST", ACCOUNTS, {"email": "eve@example.com", "name": "eve"}),
        ("GET", f"{ACCOUNTS}/{owner['id']}", None),
        ("PATCH", f"{ACCOUNTS}/{owner['id']}", {"disabled": True}),
        ("POST", f"{ACCOUNTS}/{owner['id']}/password-reset", {}),
    ]
    for method, url, body in calls:
        response = await auth_client.request(method, url, json=body, headers=bearer(bob_token))

        assert response.status_code == 403, f"{method} {url}: {response.text}"
        assert response.json()["error"]["code"] == "admin_required"


async def test_the_flag_gives_no_rights_on_tasks_and_its_absence_takes_none(
    auth_client: AsyncClient, bob_token: str, queue: Queue
) -> None:
    """Все вошедшие видят всё: человек без флага заводит задачу и читает чужие."""
    created = await auth_client.post(
        "/api/v1/tasks",
        json={"queue": queue.key, "title": "Задача Боба", "description": "Боб завёл сам"},
        headers=bearer(bob_token),
    )
    listed = await auth_client.get("/api/v1/tasks", headers=bearer(bob_token))

    assert created.status_code == 201, created.text
    assert created.json()["data"]["key"] in [item["key"] for item in listed.json()["data"]]


async def test_a_task_scope_token_of_an_admin_is_refused_by_scope(
    client: AsyncClient, task_secret: str
) -> None:
    response = await client.get(ACCOUNTS, headers=bearer(task_secret))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_an_agent_token_is_no_administrator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    agent = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=agent, scope=TokenScope.MAIN, name="t"
    )

    response = await client.get(ACCOUNTS, headers=bearer(issued.secret))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"


# --- Изменение и отключение ------------------------------------------------------------


async def account_id(client: AsyncClient, email: str) -> str:
    for item in (await client.get(ACCOUNTS)).json()["data"]:
        if item["email"] == email:
            identifier: str = item["id"]
            return identifier
    raise AssertionError(f"no account {email}")


async def test_disabling_revokes_every_token_and_enabling_lets_the_person_back_in(
    auth_client: AsyncClient, bob_token: str, db_session: AsyncSession
) -> None:
    """Отключённый не входит, его токены мертвы; включённый снова входит, но старые мертвы."""
    bob = await account_id(auth_client, "bob@example.com")

    disabled = await auth_client.patch(f"{ACCOUNTS}/{bob}", json={"disabled": True})
    tab = await auth_client.get("/api/v1/bootstrap", headers=bearer(bob_token))
    refused = await auth_client.post(
        SESSION, json={"email": "bob@example.com", "password": PASSWORD}
    )

    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["disabled_at"] is not None
    assert tab.json()["error"]["details"] == {"reason": "token_revoked"}
    assert refused.json()["error"]["details"] == {"reason": "account_disabled"}
    participants = await auth_client.get("/api/v1/participants")
    assert "bob" in [item["name"] for item in participants.json()["data"]]

    enabled = await auth_client.patch(f"{ACCOUNTS}/{bob}", json={"disabled": False})
    assert enabled.json()["data"]["disabled_at"] is None
    await sign_in(auth_client, "bob@example.com", PASSWORD)
    still_dead = await auth_client.get("/api/v1/bootstrap", headers=bearer(bob_token))
    assert still_dead.status_code == 401


@pytest.mark.parametrize("change", [{"disabled": True}, {"is_admin": False}])
async def test_the_last_active_administrator_stays(
    auth_client: AsyncClient, change: dict[str, bool]
) -> None:
    owner = await account_id(auth_client, "owner@localhost")

    response = await auth_client.patch(f"{ACCOUNTS}/{owner}", json=change)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_admin"


async def test_with_a_second_administrator_the_first_can_step_down(
    auth_client: AsyncClient,
) -> None:
    await create(auth_client, email="bob@example.com", name="bob", is_admin=True)
    owner = await account_id(auth_client, "owner@localhost")

    response = await auth_client.patch(f"{ACCOUNTS}/{owner}", json={"is_admin": False})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["is_admin"] is False


async def test_a_new_email_is_what_the_person_signs_in_with(
    auth_client: AsyncClient, bob_token: str
) -> None:
    bob = await account_id(auth_client, "bob@example.com")

    changed = await auth_client.patch(f"{ACCOUNTS}/{bob}", json={"email": "Robert@Example.com"})
    taken = await auth_client.patch(f"{ACCOUNTS}/{bob}", json={"email": "owner@localhost"})

    assert changed.json()["data"]["email"] == "robert@example.com"
    assert taken.json()["error"]["code"] == "account_email_taken"
    await sign_in(auth_client, "robert@example.com", PASSWORD)


@pytest.mark.parametrize("body", [{"email": None}, {"disabled": None}, {"role": "admin"}])
async def test_an_update_takes_no_null_and_no_unknown_field(
    auth_client: AsyncClient, body: dict[str, Any]
) -> None:
    owner = await account_id(auth_client, "owner@localhost")

    response = await auth_client.patch(f"{ACCOUNTS}/{owner}", json=body)

    assert response.status_code == 422


# --- Пароли ----------------------------------------------------------------------------


async def test_a_reset_gives_a_new_password_and_ends_the_old_sessions(
    auth_client: AsyncClient, bob_token: str
) -> None:
    bob = await account_id(auth_client, "bob@example.com")

    reset = await auth_client.post(f"{ACCOUNTS}/{bob}/password-reset", json={})

    assert reset.status_code == 200, reset.text
    new_password = reset.json()["data"]["password"]
    tab = await auth_client.get("/api/v1/bootstrap", headers=bearer(bob_token))
    assert tab.json()["error"]["details"] == {"reason": "token_revoked"}
    old = await auth_client.post(SESSION, json={"email": "bob@example.com", "password": PASSWORD})
    assert old.status_code == 401
    await sign_in(auth_client, "bob@example.com", new_password)


async def test_a_person_changes_the_own_password_knowing_the_current_one(
    auth_client: AsyncClient, bob_token: str
) -> None:
    """Неверный прежний — отказ; верный — новый пароль, прочие сеансы гаснут, этот живёт."""
    bob = await account_id(auth_client, "bob@example.com")
    other_tab = await sign_in(auth_client, "bob@example.com", PASSWORD)
    url = f"{ACCOUNTS}/{bob}/password"

    wrong = await auth_client.put(
        url,
        json={"current_password": "not it at all", "new_password": "a brand new password"},
        headers=bearer(bob_token),
    )
    changed = await auth_client.put(
        url,
        json={"current_password": PASSWORD, "new_password": "a brand new password"},
        headers=bearer(bob_token),
    )

    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "current_password_mismatch"
    assert changed.status_code == 200, changed.text
    assert (
        await auth_client.get("/api/v1/bootstrap", headers=bearer(bob_token))
    ).status_code == 200
    gone = await auth_client.get("/api/v1/bootstrap", headers=bearer(other_tab))
    assert gone.json()["error"]["details"] == {"reason": "token_revoked"}
    await sign_in(auth_client, "bob@example.com", "a brand new password")


async def test_nobody_changes_someone_elses_password_this_way(
    auth_client: AsyncClient, bob_token: str
) -> None:
    owner = await account_id(auth_client, "owner@localhost")

    response = await auth_client.put(
        f"{ACCOUNTS}/{owner}/password",
        json={"new_password": "a brand new password"},
        headers=bearer(bob_token),
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "not_own_account"


async def test_the_local_administrator_sets_a_first_password_without_a_current_one(
    auth_client: AsyncClient,
) -> None:
    """Учётной записи без пароля сверять не с чем: так владелец готовит установку к сети."""
    owner = await account_id(auth_client, "owner@localhost")

    response = await auth_client.put(
        f"{ACCOUNTS}/{owner}/password", json={"new_password": "owner password here"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["has_password"] is True
    await sign_in(auth_client, "owner@localhost", "owner password here")


# --- Два человека одной команды --------------------------------------------------------


async def test_two_people_see_the_same_tasks_and_sign_their_own_entries(
    auth_client: AsyncClient, bob_token: str, queue: Queue
) -> None:
    """Обзорная проверка 2 на уровне API: одна команда, все видят всё, подпись своя."""
    await create(auth_client, email="carol@example.com", name="carol", password=PASSWORD)
    carol_token = await sign_in(auth_client, "carol@example.com", PASSWORD)

    created = await auth_client.post(
        "/api/v1/tasks",
        json={"queue": queue.key, "title": "Общая задача", "description": "Видна всем"},
        headers=bearer(bob_token),
    )
    key = created.json()["data"]["key"]
    for token, title in [(bob_token, "Боб нашёл"), (carol_token, "Кэрол нашла")]:
        entry = await auth_client.post(
            f"/api/v1/tasks/{key}/entries",
            json={"type": "finding", "title": title},
            headers=bearer(token),
        )
        assert entry.status_code == 201, entry.text

    seen_by_carol = await auth_client.get(
        f"/api/v1/tasks/{key}/entries", headers=bearer(carol_token)
    )
    authors = {
        item["title"]: item["author"]["signature"]
        for item in seen_by_carol.json()["data"]
        if item["type"] == "finding"
    }
    assert authors == {"Боб нашёл": "bob", "Кэрол нашла": "carol"}


# --- Команда на сервере ----------------------------------------------------------------

type RunCommand = Callable[..., Awaitable[tuple[int, str, str]]]


@pytest.fixture
def run(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> RunCommand:
    """Запуск `python -m app.cli account-...` на сессии теста, со вводом из трубы.

    Подменяется `session_scope`, а не сама сессия: команда обязана пройти через свою
    границу транзакции (как в `tests/test_local_token.py`).
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        await db_session.commit()
        async with transaction(db_session):
            yield db_session

    monkeypatch.setattr(cli, "session_scope", scope)

    async def call(*argv: str, stdin: str = "") -> tuple[int, str, str]:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        args = cli._build_parser().parse_args(list(argv))
        code = await cli._run(args.handler, args)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return call


async def test_the_command_creates_a_person_and_prints_the_password_once(
    run: RunCommand, auth_client: AsyncClient, owner: Participant
) -> None:
    """Обзорная проверка 2, половина «командой»: заведённый командой входит своей почтой."""
    code, out, _ = await run("account-create", "--email", "dave@example.com", "--name", "dave")

    assert code == 0, out
    assert "account:     dave@example.com" in out
    password = out.strip().splitlines()[-1].strip()
    token = await sign_in(auth_client, "dave@example.com", password)
    me = await auth_client.get("/api/v1/bootstrap", headers=bearer(token))
    assert me.json()["data"]["participant"]["name"] == "dave"


async def test_the_command_takes_a_typed_password_from_a_pipe_and_prints_none(
    run: RunCommand, auth_client: AsyncClient, owner: Participant
) -> None:
    code, out, _ = await run(
        "account-create",
        "--email",
        "dave@example.com",
        "--name",
        "dave",
        "--admin",
        "--set-password",
        stdin=f"{PASSWORD}\n",
    )

    assert code == 0, out
    assert PASSWORD not in out
    assert "admin:       yes" in out
    await sign_in(auth_client, "dave@example.com", PASSWORD)


async def test_the_command_lists_updates_and_resets(
    run: RunCommand, auth_client: AsyncClient, owner: Participant, db_session: AsyncSession
) -> None:
    await run("account-create", "--email", "dave@example.com", "--name", "dave")

    _, listed, _ = await run("account-list")
    _, disabled, _ = await run("account-update", "--email", "dave@example.com", "--disable")
    _, _, refused_err = await run("account-update", "--email", "owner@localhost", "--no-admin")
    code, reset, _ = await run("account-password", "--email", "dave@example.com")

    assert "owner@localhost  owner  [admin, no password]" in listed
    assert "dave@example.com  dave" in listed
    assert "state:       disabled" in disabled
    assert "last_admin" in refused_err
    assert code == 0
    assert "Generated password, shown once" in reset
    account = await AccountRepository(db_session).get_by_email("dave@example.com")
    assert account is not None and account.is_disabled


async def test_the_command_refuses_a_short_typed_password(
    run: RunCommand, owner: Participant
) -> None:
    short = "x" * (MIN_PASSWORD_LENGTH - 1)
    code, out, err = await run(
        "account-create",
        "--email",
        "dave@example.com",
        "--name",
        "dave",
        "--set-password",
        stdin=f"{short}\n",
    )

    assert code == 1
    assert "weak_password" in err
    assert short not in out + err
