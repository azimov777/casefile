"""Ключ интерфейса выпускает установка: четыре исхода команды `local-token`.

Проверяется целиком команда, а не один сценарий: половина её смысла живёт не в базе, а
в файле — права `0600`, побайтная неизменность при повторе и отсутствие секрета в
выводе. Ради этого `session_scope` подменён сессией теста: транзакция всё равно
откатится, а команда пройдёт своим настоящим путём, включая запись файла до коммита.

Живой прогон в Docker эти проверки не заменяет и не заменяется ими: там команда идёт
через настоящий контур, здесь — через настоящую базу и настоящую файловую систему.
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
from app.domain.errors import ParticipantNotFoundError
from app.domain.participants import ParticipantKind
from app.domain.tokens import TOKEN_PREFIX, TokenScope
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, authenticate
from app.services.setup import (
    DEFAULT_LOCAL_TOKEN_NAME,
    LocalTokenOutcome,
    ensure_local_token,
    initialize_installation,
)

#: Как тест зовёт команду: путь к файлу и, если нужно, остальные ключи командной строки.
type RunCommand = Callable[..., Awaitable[int]]


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    """Файл, в котором живёт ключ. Каталога заранее нет — команда заводит его сама."""
    return tmp_path / "secrets" / "ui-token"


@pytest.fixture
def run(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> RunCommand:
    """Запуск `python -m app.cli local-token` на сессии теста.

    Подменяется `session_scope`, а не сама сессия: команда обязана пройти через свою
    границу транзакции — именно внутри неё она пишет файл, до коммита. Граница берётся
    боевая (`transaction`), как у фикстуры MCP-сервера: своя копия была бы зелёной и
    там, где боевая сломана. Коммит на сессии теста закрывает вложенную точку
    сохранения, а не транзакцию прогона.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        await db_session.commit()
        async with transaction(db_session):
            yield db_session

    monkeypatch.setattr(cli, "session_scope", scope)

    async def call(path: Path, *extra: str) -> int:
        args = cli._build_parser().parse_args(["local-token", "--output", str(path), *extra])
        return await cli._local_token(args)

    return call


async def test_an_empty_installation_gets_an_owner_and_a_task_token_in_a_file(
    db_session: AsyncSession,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Исход 2 и обзорная проверка 1: пустая установка, файл `0600`, ключ работает."""
    code = await run(token_file)

    assert code == 0
    secret = token_file.read_text(encoding="utf-8")
    assert secret.startswith(TOKEN_PREFIX)
    # Только секрет: перевода строки в конце нет, чтобы файл читался как есть.
    assert secret == secret.strip()
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    actor = await authenticate(db_session, secret)
    assert actor.scope is TokenScope.TASK
    assert actor.participant is not None
    assert actor.participant.name == "owner"
    assert actor.participant.kind is ParticipantKind.HUMAN

    printed = capsys.readouterr()
    assert TOKEN_PREFIX not in printed.out + printed.err, printed


async def test_a_second_run_keeps_the_same_key_and_issues_nothing(
    db_session: AsyncSession,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Исход 1 и обзорная проверка 2: тот же файл побайтно, число токенов не выросло."""
    await run(token_file)
    first = token_file.read_bytes()
    before = await tokens_service.list_tokens(db_session, actor=TRACKER_ACTOR)
    capsys.readouterr()

    code = await run(token_file)

    assert code == 0
    assert token_file.read_bytes() == first
    after = await tokens_service.list_tokens(db_session, actor=TRACKER_ACTOR)
    assert len(after.items) == len(before.items)

    printed = capsys.readouterr()
    assert "already has a working local token" in printed.out, printed.out
    assert TOKEN_PREFIX not in printed.out + printed.err, printed


async def test_a_lost_file_gives_a_new_key_and_revokes_the_old_one(
    db_session: AsyncSession,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Исход 3 и обзорная проверка 3: старым секретом уже не пройти.

    Главное здесь — не то, что новый ключ работает, а то, что старый перестал: иначе на
    машине оставался бы действующий секрет, которого не знает никто.
    """
    await run(token_file)
    lost = token_file.read_text(encoding="utf-8")
    token_file.unlink()
    capsys.readouterr()

    code = await run(token_file)

    assert code == 0
    fresh = token_file.read_text(encoding="utf-8")
    assert fresh != lost

    actor = await authenticate(db_session, fresh)
    assert actor.scope is TokenScope.TASK

    with pytest.raises(UnauthorizedError) as refusal:
        await authenticate(db_session, lost)
    assert refusal.value.details["reason"] == "token_revoked"

    printed = capsys.readouterr()
    assert "a new one is issued" in printed.out, printed.out
    assert TOKEN_PREFIX not in printed.out + printed.err, printed


async def test_an_unknown_participant_on_a_live_installation_is_refused(
    db_session: AsyncSession,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Исход 4: отказ с ненулевым кодом возврата, а не второй участник молча.

    Зовётся через `_run` — обёртку, которая и превращает доменную ошибку в сообщение и
    код: проверяется судьба отказа целиком, а не только то, что исключение вылетело.
    """
    assert await initialize_installation(db_session) is not None
    args = cli._build_parser().parse_args(
        ["local-token", "--output", str(token_file), "--participant", "ownre"]
    )

    code = await cli._run(cli._local_token, args)

    assert code == 1
    assert not token_file.exists()
    printed = capsys.readouterr()
    assert "participant_not_found" in printed.err, printed.err
    assert "ownre" in printed.err, printed.err


async def test_a_garbled_file_is_replaced_rather_than_read_as_an_error(
    token_file: Path,
    run: RunCommand,
) -> None:
    """Испорченный файл — это исход 3, а не падение: годность решает база, а не разбор.

    Байты заведомо не UTF-8: файл мог остаться от оборванной записи или чужого
    инструмента, и разбирать его командной строке нечем.
    """
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_bytes(b"\xff\xfe not a token \x00")

    code = await run(token_file)

    assert code == 0
    assert token_file.read_text(encoding="utf-8").startswith(TOKEN_PREFIX)


async def test_an_existing_file_is_brought_back_to_owner_only_rights(
    token_file: Path,
    run: RunCommand,
) -> None:
    """Права приводятся к `0600` и у файла, оставшегося от прежнего запуска.

    Создание с нужным режимом само по себе этого не даёт: `os.open` существующему файлу
    режим не меняет, и ключ лёг бы в файл, читаемый всей машиной.
    """
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("trk_stale", encoding="utf-8")
    token_file.chmod(0o644)

    await run(token_file)

    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


async def test_a_valid_secret_keeps_the_installation_untouched(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Сценарий: годный секрет — это `KEPT` без выпуска, даже если токен выпущен не им.

    Проверяется признак годности как таковой: найден по хешу, не отозван, за ним
    участник. Ни набор, ни имя токена в него не входят — файл это собственная копия
    установки, и лишние условия дали бы перевыпуск на ровном месте.
    """
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.TASK,
        name="spare",
    )

    result = await ensure_local_token(db_session, known_secret=issued.secret)

    assert result.outcome is LocalTokenOutcome.KEPT
    assert result.secret is None
    assert result.revoked == 0
    assert result.token.id == issued.token.id


async def test_a_revoked_secret_counts_as_no_secret_at_all(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Отозванный токен в файле — это исход 3: перевыпуск, а не молчаливое согласие."""
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.TASK,
        name=DEFAULT_LOCAL_TOKEN_NAME,
    )
    await tokens_service.revoke_token(db_session, issued.token.id, actor=TRACKER_ACTOR)

    result = await ensure_local_token(db_session, known_secret=issued.secret)

    assert result.outcome is LocalTokenOutcome.REISSUED
    assert result.secret is not None
    assert result.token.scope is TokenScope.TASK
    # Отзывать нечего: прежний токен с этим именем уже отозван.
    assert result.revoked == 0


async def test_only_the_token_with_the_same_name_is_revoked(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Замена отзывает свою предшественницу, а не всё, чем владелец ходит в трекер.

    Токен `init` набора `main` — единственный доступ человека к управлению установкой,
    и подъём контура не должен его гасить.
    """
    human = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name="bootstrap",
    )
    first = await ensure_local_token(db_session, known_secret=None)

    second = await ensure_local_token(db_session, known_secret=None)

    assert second.revoked == 1
    assert first.token.is_revoked
    assert not human.token.is_revoked
    actor = await authenticate(db_session, human.secret)
    assert actor.scope is TokenScope.MAIN


async def test_the_scenario_names_the_participant_it_could_not_find(
    db_session: AsyncSession,
    main_secret: str,
) -> None:
    """Отказ приходит с именем в подробностях: читателю видно, что именно не нашлось."""
    with pytest.raises(ParticipantNotFoundError) as refusal:
        await ensure_local_token(db_session, known_secret=None, participant_name="release_bot")

    assert refusal.value.details == {"name": "release_bot"}
