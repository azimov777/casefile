"""Учётная запись администратора, которую установка заводит себе сама, и перенос пароля.

`docs/CONCEPT.md`, 5.4; `app/services/setup.py`, раздел «Учётная запись администратора
заводится здесь же» (TRK-113). Команда `local-token` запускается на сессии теста, как в
`tests/test_local_token.py`: проверяется и сценарий, и то, что команда берёт прежний
`TRACKER_PASSWORD_HASH` из настроек и не печатает его.
"""

import ipaddress
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.db.models.account import Account
from app.db.repositories import AccountRepository, ParticipantRepository
from app.db.session import transaction
from app.domain.participants import ParticipantKind
from app.domain.passwords import hash_password
from app.domain.tokens import TokenScope
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from app.services.login import PasswordLogin
from app.services.setup import ensure_agent_token, initialize_installation

OLD_PASSWORD = "the password of the old installation"
OLD_HASH = hash_password(OLD_PASSWORD, n=2**4, r=1, p=1).render()

type RunCommand = Callable[..., Awaitable[tuple[int, str, str]]]


async def owner_account(db_session: AsyncSession) -> Account | None:
    participant = await ParticipantRepository(db_session).get_by_name("owner")
    assert participant is not None
    return await AccountRepository(db_session).get_by_participant(participant.id)


@pytest.fixture
def run(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> RunCommand:
    """`python -m app.cli local-token` на сессии теста с данным `TRACKER_PASSWORD_HASH`."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        await db_session.commit()
        async with transaction(db_session):
            yield db_session

    monkeypatch.setattr(cli, "session_scope", scope)

    async def call(password_hash: str | None = None) -> tuple[int, str, str]:
        monkeypatch.setattr(cli, "get_settings", lambda: Settings(password_hash=password_hash))
        args = cli._build_parser().parse_args(
            ["local-token", "--output", str(tmp_path / "ui-token")]
        )
        code = await cli._local_token(args)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return call


async def signs_in(db_session: AsyncSession, email: str, password: str) -> bool:
    """Пускает ли вход по почте и паролю — тем же сценарием, что `POST /api/v1/session`."""
    login = PasswordLogin(session_ttl=timedelta(hours=1))
    try:
        await login.open(
            db_session, email=email, password=password, client=ipaddress.ip_address("127.0.0.1")
        )
    except UnauthorizedError:
        return False
    return True


# --- Своя машина ------------------------------------------------------------------------


async def test_a_fresh_installation_gets_an_administrator_without_a_password(
    db_session: AsyncSession, run: RunCommand
) -> None:
    """Обзорная проверка 1, сценарий: вводить нечего — пароля нет, ключ в файле."""
    code, out, _ = await run()

    account = await owner_account(db_session)
    assert code == 0, out
    assert account is not None
    assert account.email == "owner@localhost"
    assert account.is_admin
    assert account.password_hash is None
    assert "account:     owner@localhost (administrator, password: none)" in out


async def test_init_makes_the_owner_an_administrator_too(db_session: AsyncSession) -> None:
    issued = await initialize_installation(db_session)

    assert issued is not None
    account = await owner_account(db_session)
    assert account is not None and account.is_admin


async def test_the_agent_step_on_an_empty_installation_starts_with_the_administrator(
    db_session: AsyncSession,
) -> None:
    await ensure_agent_token(db_session, known_secret=None)

    account = await owner_account(db_session)
    assert account is not None and account.is_admin


async def test_an_owner_from_before_accounts_gets_one_on_the_next_start(
    db_session: AsyncSession, run: RunCommand
) -> None:
    """Установка, поднятая до учётных записей: владелец и ключ есть, учётной записи нет."""
    owner = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.HUMAN, name="owner"
    )
    await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name="bootstrap",
    )
    assert await owner_account(db_session) is None

    code, out, _ = await run()

    account = await owner_account(db_session)
    assert code == 0, out
    assert account is not None and account.is_admin


# --- Перенос пароля установки -----------------------------------------------------------


async def test_the_old_installation_password_keeps_signing_in(
    db_session: AsyncSession, run: RunCommand
) -> None:
    """Обзорная проверка 4, сценарий: хеш из `.env` становится паролем администратора."""
    await run()  # установка поднята до переноса: учётная запись без пароля
    code, out, err = await run(OLD_HASH)

    account = await owner_account(db_session)
    assert code == 0, err
    assert account is not None and account.password_hash == OLD_HASH
    assert "password: imported from TRACKER_PASSWORD_HASH" in out
    assert OLD_HASH not in out + err
    assert await signs_in(db_session, "owner@localhost", OLD_PASSWORD)


async def test_a_password_set_later_is_not_overwritten_by_the_old_hash(
    db_session: AsyncSession, run: RunCommand
) -> None:
    await run(OLD_HASH)
    account = await owner_account(db_session)
    assert account is not None
    newer = hash_password("a password chosen later", n=2**4, r=1, p=1).render()
    account.password_hash = newer
    await db_session.flush()

    await run(OLD_HASH)

    assert (await owner_account(db_session)) is not None
    assert account.password_hash == newer
    assert not await signs_in(db_session, "owner@localhost", OLD_PASSWORD)


async def test_a_malformed_old_hash_stops_the_step_without_printing_it(
    db_session: AsyncSession, run: RunCommand
) -> None:
    """Испорченный хеш роняет подъём, а не оставляет владельца молча без пароля."""
    broken = "$scrypt$" + OLD_HASH

    code, out, err = await run(broken)

    assert code == 1
    assert "TRACKER_PASSWORD_HASH" in err
    assert broken not in out + err
