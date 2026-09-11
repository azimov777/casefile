"""Ключ интерфейса выпускает установка: исходы команды `local-token`.

Проверяется целиком команда, а не один сценарий: половина её смысла живёт не в базе, а
в файле — права `0600`, побайтная неизменность при повторе и отсутствие секрета в
выводе. Ради этого `session_scope` подменён сессией теста: транзакция всё равно
откатится, а команда пройдёт своим настоящим путём, включая запись файла до коммита.

Набор ключа — `main` (решение владельца, `docs/DEVELOPMENT.md`, «Ключ для локального
интерфейса»), и годный ключ прежнего набора `task` в файле заменяется: так работающие
установки переходят на `main` при следующем подъёме.

Живой прогон в Docker эти проверки не заменяет и не заменяется ими: там команда идёт
через настоящий контур, здесь — через настоящую базу и настоящую файловую систему.
"""

import stat
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
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

#: Снимок токенов установки: идентификатор → момент отзыва. Снимаются значения, а не
#: объекты: сессия одна, и объект из «до» к моменту «после» показал бы уже новое состояние.
type TokenSnapshot = dict[uuid.UUID, datetime | None]


async def snapshot(session: AsyncSession) -> TokenSnapshot:
    page = await tokens_service.list_tokens(session, actor=TRACKER_ACTOR)
    return {token.id: token.revoked_at for token in page.items}


def write_secret(path: Path, secret: str) -> None:
    """Кладёт секрет в файл так, как его оставил бы прежний запуск команды."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret, encoding="utf-8")
    path.chmod(0o600)


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


async def test_an_empty_installation_gets_an_owner_and_a_main_token_in_a_file(
    db_session: AsyncSession,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Пустая установка: владелец заведён, ключ набора `main` в файле `0600`, ключ работает."""
    code = await run(token_file)

    assert code == 0
    secret = token_file.read_text(encoding="utf-8")
    assert secret.startswith(TOKEN_PREFIX)
    # Только секрет: перевода строки в конце нет, чтобы файл читался как есть.
    assert secret == secret.strip()
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    actor = await authenticate(db_session, secret)
    assert actor.scope is TokenScope.MAIN
    assert actor.participant is not None
    assert actor.participant.name == "owner"
    assert actor.participant.kind is ParticipantKind.HUMAN

    printed = capsys.readouterr()
    assert TOKEN_PREFIX not in printed.out + printed.err, printed


async def test_a_second_run_keeps_the_main_key_and_issues_or_revokes_nothing(
    db_session: AsyncSession,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Годный ключ `main` в файле: тот же файл побайтно, не выпущено и не отозвано ничего."""
    await run(token_file)
    first = token_file.read_bytes()
    before = await snapshot(db_session)
    capsys.readouterr()

    code = await run(token_file)

    assert code == 0
    assert token_file.read_bytes() == first
    # Сравнивается снимок целиком: число токенов ловит лишний выпуск, момент отзыва —
    # лишний отзыв, которого по числу не видно.
    assert await snapshot(db_session) == before

    printed = capsys.readouterr()
    assert "already has a working local token" in printed.out, printed.out
    assert "revoked" not in printed.out, printed.out
    assert TOKEN_PREFIX not in printed.out + printed.err, printed


async def test_a_working_task_key_is_replaced_by_a_main_key_and_revoked(
    db_session: AsyncSession,
    owner: Participant,
    token_file: Path,
    run: RunCommand,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Файл с годным ключом `task`, каким его выпускала команда до смены набора.

    Одним запуском: выпущен ключ `main`, прежний отозван, и больше не тронуто ничего —
    доступ `init` владельца остаётся действующим. Действующих секретов, которых никто не
    знает, после замены нет: единственный отозванный — ровно тот, что лежал в файле.
    """
    human = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=owner, scope=TokenScope.MAIN, name="bootstrap"
    )
    previous = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.TASK,
        name=DEFAULT_LOCAL_TOKEN_NAME,
    )
    write_secret(token_file, previous.secret)
    before = await snapshot(db_session)

    code = await run(token_file)

    assert code == 0
    fresh = token_file.read_text(encoding="utf-8")
    assert fresh != previous.secret
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    actor = await authenticate(db_session, fresh)
    assert actor.scope is TokenScope.MAIN
    assert actor.participant is not None
    assert actor.participant.id == owner.id

    with pytest.raises(UnauthorizedError) as refusal:
        await authenticate(db_session, previous.secret)
    assert refusal.value.details["reason"] == "token_revoked"
    assert (await authenticate(db_session, human.secret)).scope is TokenScope.MAIN

    after = await snapshot(db_session)
    assert len(after) == len(before) + 1
    newly_revoked = {
        token_id
        for token_id, revoked_at in after.items()
        if revoked_at is not None and before.get(token_id) is None
    }
    assert newly_revoked == {previous.token.id}

    printed = capsys.readouterr()
    assert "had another scope" in printed.out, printed.out
    assert "revoked:     1 previous token(s)" in printed.out, printed.out
    assert "token scope: main" in printed.out, printed.out
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
    assert actor.scope is TokenScope.MAIN

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


async def test_a_valid_main_secret_keeps_the_installation_untouched(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Сценарий: годный секрет `main` — это `KEPT` без выпуска, даже если токен выпущен не им.

    Проверяется признак годности как таковой: найден по хешу, не отозван, за ним
    участник, набор `main`. Имя токена в него не входит — файл это собственная копия
    установки, и лишние условия дали бы перевыпуск на ровном месте.
    """
    issued = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name="spare",
    )

    result = await ensure_local_token(db_session, known_secret=issued.secret)

    assert result.outcome is LocalTokenOutcome.KEPT
    assert result.secret is None
    assert result.revoked == 0
    assert result.token.id == issued.token.id


async def test_a_working_task_key_under_another_name_is_revoked_too(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Ключ `task` в файле отзывается, как бы он ни назывался.

    Одноимённых под отзыв здесь нет вовсе: без отзыва самого ключа из файла его секрет
    остался бы действующим, а файл, где он лежал, уже переписан новым.
    """
    spare = await tokens_service.issue_token(
        db_session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.TASK,
        name="spare",
    )

    result = await ensure_local_token(db_session, known_secret=spare.secret)

    assert result.outcome is LocalTokenOutcome.RESCOPED
    assert result.secret is not None
    assert result.revoked == 1
    assert spare.token.is_revoked
    assert result.token.scope is TokenScope.MAIN
    assert result.token.name == DEFAULT_LOCAL_TOKEN_NAME
    assert result.token.participant is not None
    assert result.token.participant.id == owner.id


async def test_a_task_key_among_its_namesakes_is_revoked_once(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Ключ из файла стоит и среди одноимённых: отзывается один раз, счёт честный."""
    in_file, namesake = [
        await tokens_service.issue_token(
            db_session,
            actor=TRACKER_ACTOR,
            participant=owner,
            scope=TokenScope.TASK,
            name=DEFAULT_LOCAL_TOKEN_NAME,
        )
        for _ in range(2)
    ]

    result = await ensure_local_token(db_session, known_secret=in_file.secret)

    assert result.outcome is LocalTokenOutcome.RESCOPED
    assert result.revoked == 2
    assert in_file.token.is_revoked
    assert namesake.token.is_revoked


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

    # Отозванный ключ `task` — не «ключ другого набора», а негодный: смена набора тут ни
    # при чём, и заменять нечего.
    assert result.outcome is LocalTokenOutcome.REISSUED
    assert result.secret is not None
    assert result.token.scope is TokenScope.MAIN
    # Отзывать нечего: прежний токен с этим именем уже отозван.
    assert result.revoked == 0


async def test_only_the_token_with_the_same_name_is_revoked(
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Замена отзывает свою предшественницу, а не всё, чем владелец ходит в трекер.

    Токен `init` — секрет владельца в руках, для `curl` и терминала, того же набора
    `main`, что и ключ интерфейса, — и подъём контура не должен его гасить.
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
