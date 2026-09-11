"""Токен агента выпускает установка: команда `agent-token`.

Близнец `test_local_token.py`, и проверяется тем же способом — командой целиком, через
её настоящую границу транзакции и настоящий файл. Здесь только то, чем агент отличается
от интерфейса: набор `main`, участник-агент, заводимый на работающей установке, и
владелец, которого команда заводит сама, если пришла на пустую установку первой.
"""

import stat
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.db.session import transaction
from app.domain.participants import ParticipantKind
from app.domain.tokens import TOKEN_PREFIX, TokenScope
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, authenticate
from app.services.setup import (
    DEFAULT_LOCAL_TOKEN_NAME,
    DEFAULT_OWNER_NAME,
    LocalTokenOutcome,
    ensure_agent_token,
)

#: Как тест зовёт команду: имя команды, путь к файлу и, если нужно, остальные ключи.
type RunCommand = Callable[..., Awaitable[int]]


@pytest.fixture
def secrets(tmp_path: Path) -> Path:
    """Каталог секретов установки. Заранее его нет — команда заводит его сама."""
    return tmp_path / "secrets"


@pytest.fixture
def run(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> RunCommand:
    """Запуск `python -m app.cli <команда> --output <файл>` на сессии теста.

    Подмена та же, что в `test_local_token.py`: команда проходит через боевую границу
    транзакции, а коммит закрывает вложенную точку сохранения, а не прогон.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        await db_session.commit()
        async with transaction(db_session):
            yield db_session

    monkeypatch.setattr(cli, "session_scope", scope)

    async def call(command: str, path: Path, *extra: str) -> int:
        args = cli._build_parser().parse_args([command, "--output", str(path), *extra])
        return await args.handler(args)

    return call


async def test_the_agent_gets_a_main_token_in_a_file_and_the_secret_is_never_printed(
    db_session: AsyncSession,
    secrets: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Токен набора `main` у участника-агента, в файле `0600` и больше нигде."""
    await run("local-token", secrets / "ui-token")
    capsys.readouterr()

    code = await run("agent-token", secrets / "agent-token")

    assert code == 0
    token_file = secrets / "agent-token"
    secret = token_file.read_text(encoding="utf-8")
    assert secret.startswith(TOKEN_PREFIX)
    assert secret == secret.strip()
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    actor = await authenticate(db_session, secret)
    assert actor.scope is TokenScope.MAIN
    assert actor.participant is not None
    assert actor.participant.name == "agent"
    assert actor.participant.kind is ParticipantKind.AGENT

    printed = capsys.readouterr()
    assert TOKEN_PREFIX not in printed.out + printed.err, printed


async def test_on_an_empty_installation_the_owner_comes_first_and_the_ui_key_still_works(
    db_session: AsyncSession,
    secrets: Path,
    run: RunCommand,
) -> None:
    """Порядок двух команд не важен: пришедшая первой заводит владельца-человека.

    Без этого `local-token` после `agent-token` упёрся бы в `participant_not_found`:
    установка уже непуста, а человека в ней нет, — и контур, поднятый в другом порядке,
    остался бы без интерфейса.
    """
    assert await run("agent-token", secrets / "agent-token") == 0

    assert await run("local-token", secrets / "ui-token") == 0

    ui = await authenticate(db_session, (secrets / "ui-token").read_text(encoding="utf-8"))
    assert ui.participant is not None
    assert ui.participant.name == DEFAULT_OWNER_NAME
    assert ui.participant.kind is ParticipantKind.HUMAN
    assert ui.scope is TokenScope.TASK


async def test_a_second_run_keeps_the_same_token_and_issues_nothing(
    db_session: AsyncSession,
    secrets: Path,
    run: RunCommand,
) -> None:
    """Повторный подъём контура не выпускает ничего: файл тот же побайтно."""
    token_file = secrets / "agent-token"
    await run("agent-token", token_file)
    first = token_file.read_bytes()
    before = await tokens_service.list_tokens(db_session, actor=TRACKER_ACTOR)

    assert await run("agent-token", token_file) == 0

    assert token_file.read_bytes() == first
    after = await tokens_service.list_tokens(db_session, actor=TRACKER_ACTOR)
    assert len(after.items) == len(before.items)


async def test_a_lost_file_gives_a_new_token_and_the_old_one_stops_working(
    db_session: AsyncSession,
    secrets: Path,
    run: RunCommand,
) -> None:
    """Потерянный файл не оставляет на машине действующего секрета, которого никто не знает."""
    token_file = secrets / "agent-token"
    await run("agent-token", token_file)
    lost = token_file.read_text(encoding="utf-8")
    token_file.unlink()

    assert await run("agent-token", token_file) == 0

    fresh = token_file.read_text(encoding="utf-8")
    assert fresh != lost
    assert (await authenticate(db_session, fresh)).scope is TokenScope.MAIN
    with pytest.raises(UnauthorizedError) as refusal:
        await authenticate(db_session, lost)
    assert refusal.value.details["reason"] == "token_revoked"


async def test_the_ui_key_is_left_alone_when_the_agent_token_is_reissued(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Замена отзывает предшественницу агента, а не ключ интерфейса владельца."""
    ui = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.TASK,
        name=DEFAULT_LOCAL_TOKEN_NAME,
    )
    first = await ensure_agent_token(db_session, known_secret=None)

    second = await ensure_agent_token(db_session, known_secret=None)

    assert second.outcome is LocalTokenOutcome.REISSUED
    assert second.revoked == 1
    assert first.token.is_revoked
    assert not ui.token.is_revoked
    assert (await authenticate(db_session, ui.secret)).scope is TokenScope.TASK
