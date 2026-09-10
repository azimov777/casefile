"""Гонка создающих вызовов: проигравший получает доменный отказ, а не сырую ошибку базы.

Создающие сценарии устроены как «проверить и вставить»: занятость ключа проверяется
запросом, а разводит одновременные попытки уникальное ограничение в базе. Проверка
поэтому обязательно проходит у обеих транзакций, и вторая узнаёт правду от `INSERT`.
Так и задумано — но `IntegrityError` наружу выпускать нельзя: у REST его переводил
обработчик ошибок, а MCP отдавал бы крах вызова, командная строка — трассировку.

Перевод живёт на границе транзакции (`app/db/session.py`, `transaction`), одной на все
три интерфейса. Здесь проверяются два из них — те, у которых своего обработчика нет:
клиент MCP и команда `app.cli`. Третий закрыт `tests/test_transactions.py`.

## Почему сессии свои

Гонка за уникальным ключом видна только **между** транзакциями: внутри одной второй
`INSERT` просто увидел бы первый. Поэтому здесь сессии с настоящими коммитами поверх
движка прогона, ручная уборка закоммиченных строк и барьер, который сводит обе
транзакции в одной точке.

Барьер стоит внутри подменённой функции проверки и стоит в ней **после** настоящего
чтения: обе транзакции обязаны прочитать «свободно» раньше, чем любая из них закоммитит.
Подмена считает то же самое и тем же запросом — добавляется только встреча, — поэтому
проверяемое поведение она не подменяет, а лишь делает редкое чередование обязательным.
Встреча до чтения выглядит так же, а проверяет другое: `meet_after_the_check` ниже.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import pytest
from mcp.server.mcpserver import MCPServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import cli
from app.db import session as session_module
from app.db.repositories import ParticipantRepository, QueueRepository, TokenRepository
from app.db.session import transaction
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope
from app.mcp.runtime import Runtime
from app.mcp.server import create_server
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from conftest import connect_mcp, tool_text

#: Уникальный хвост ключей и имён этого прогона: строки коммитятся по-настоящему, и
#: оставшаяся от упавшей уборки строка иначе занимала бы ключ у следующего прогона.
SUFFIX = uuid.uuid4().hex[:6].upper()

QUEUE_KEY = f"CONF{SUFFIX}"
OWNER_NAME = f"conf_owner_{SUFFIX.lower()}"


@pytest.fixture
def committing_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий поверх движка прогона: каждая коммитит по-настоящему."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def committed_secret(
    committing_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[str]:
    """Секрет токена набора `main`, видимый другим соединениям, и уборка за собой.

    Токен обязан быть закоммичен: сервер MCP здесь ходит настоящими сессиями, а строки
    из откатываемой транзакции теста для них не существуют.
    """
    async with committing_sessions() as session:
        participant = await participants_service.register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.HUMAN,
            name=OWNER_NAME,
            description="Владелец на время проверки гонки",
        )
        issued = await tokens_service.issue_token(
            session,
            actor=TRACKER_ACTOR,
            participant=participant,
            scope=TokenScope.MAIN,
            name="integrity race",
        )
        await session.commit()
        secret = issued.secret
        token_id = issued.token.id
        participant_id = participant.id

    try:
        yield secret
    finally:
        async with committing_sessions() as session:
            await session.execute(
                text("DELETE FROM idempotency_keys WHERE token_id = :token"), {"token": token_id}
            )
            await session.execute(text("DELETE FROM tokens WHERE id = :token"), {"token": token_id})
            await session.execute(
                text("DELETE FROM participants WHERE id = :participant"),
                {"participant": participant_id},
            )
            await session.execute(text("DELETE FROM queues WHERE key = :key"), {"key": QUEUE_KEY})
            await session.commit()


@pytest.fixture
def committing_server(committing_sessions: async_sessionmaker[AsyncSession]) -> MCPServer:
    """Сервер MCP на настоящих сессиях и настоящей границе транзакции.

    Граница берётся боевая (`transaction`), а не пишется здесь заново: проверяется
    именно её перевод ошибки, и своя копия сделала бы тест зелёным на сломанном коде.
    """

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        async with committing_sessions() as session, transaction(session):
            yield session

    return create_server(runtime=Runtime(sessions=scope))


def meet_after_the_check(
    monkeypatch: pytest.MonkeyPatch,
    barrier: asyncio.Barrier,
    repository: type,
    method: str,
) -> None:
    """Сводит обе транзакции в одной точке — сразу **после** чтения, решающего исход.

    Место встречи здесь не оформление, а само проверяемое условие. Создающий сценарий
    читает занятость сам и на найденной строке отвечает своим доменным отказом
    (`queue_key_taken`, `participant_name_taken`); до уникального индекса — а значит и до
    проверяемого здесь перевода `IntegrityError` — доходит только тот, кто прочитал
    раньше чужого коммита. Встреча после чтения делает это чередование обязательным для
    обеих транзакций, и других исходов у проигравшего не остаётся.

    Встреча **до** чтения — не более слабая постановка той же гонки, а постановка другой:
    обе транзакции лишь начинают одновременно, дальше первым коммитит кто угодно, и
    проигравший с равным правом печатает то один отказ, то другой. Тест от этого плавает
    и врёт в обе стороны (`TRK-48`, заметка «Место встречи решает, какой из двух отказов
    получит проигравший» в `docs/notes/testing.md`).

    Подмена считает то же самое и тем же запросом — добавляется только встреча, — поэтому
    проверяемое поведение она не подменяет.
    """
    original = getattr(repository, method)

    async def rendezvous(self: object, value: str) -> object:
        found = await original(self, value)
        await barrier.wait()
        return found

    monkeypatch.setattr(repository, method, rendezvous)


async def test_two_parallel_create_queue_calls_leave_mcp_a_domain_error(
    committing_server: MCPServer,
    committed_secret: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Обзорная проверка 3: один создаёт, второй получает отказ с кодом, а не крах.

    Проверяется ровно то, что видит агент: текст результата. В нём обязан стоять
    стабильный код и имя нарушенного ограничения — по ним агент понимает, что ключ занят
    кем-то ещё, и не повторяет вызов вслепую. Трассировки и имени класса драйвера в нём
    быть не должно: агент читает текст, а не разбирает исключения Python.
    """
    meet_after_the_check(monkeypatch, asyncio.Barrier(2), QueueRepository, "get_by_key")
    arguments = {"key": QUEUE_KEY, "title": "Гонка ключа", "description": ""}

    async with AsyncExitStack() as clients:
        first = await clients.enter_async_context(connect_mcp(committing_server, committed_secret))
        second = await clients.enter_async_context(connect_mcp(committing_server, committed_secret))
        results = await asyncio.gather(
            first.call_tool("create_queue", arguments),
            second.call_tool("create_queue", arguments),
        )

    refused = [result for result in results if result.is_error]
    assert len(refused) == 1, [tool_text(result) for result in results]
    text_of_refusal = tool_text(refused[0])
    assert "conflict: Database constraint violated" in text_of_refusal, text_of_refusal
    assert "uq_queues_key" in text_of_refusal, text_of_refusal
    assert "IntegrityError" not in text_of_refusal, text_of_refusal
    assert "IntegrityError" not in caplog.text, caplog.text


async def test_two_parallel_init_commands_end_with_a_message_not_a_traceback(
    committing_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Обзорная проверка 4: проигравшая команда — понятное сообщение и код возврата 1.

    `init` идёт в Compose рядом с миграциями, поэтому запустить его дважды разом — не
    выдумка, а обычный день с двумя репликами. Признак пустой установки подменён на
    «пуста»: иначе исход зависел бы от того, что оставили в базе соседние тесты, а
    проверяется здесь не признак, а судьба ошибки целостности.

    Барьера в этой подмене нет намеренно. Она ничего не читает, и встреча в ней сводила
    бы команды **до** первого запроса обеих — у сессий здесь движок прогона с `NullPool`,
    и первым запросом идёт полное установление соединения. Кто подключился первым, тот
    успевал закоммитить участника раньше, чем второй его прочитает, и проигравший печатал
    `participant_name_taken` вместо перевода ошибки целостности (`TRK-48`). Сводит их
    поэтому `meet_after_the_check` — на чтении имени участника, которым исход и решается.
    """
    monkeypatch.setattr(
        session_module,
        "_sessionmaker",
        async_sessionmaker(bind=committing_sessions.kw["bind"], expire_on_commit=False),
    )

    async def empty_installation(self: TokenRepository) -> bool:
        return False

    monkeypatch.setattr(TokenRepository, "any_exists", empty_installation)
    meet_after_the_check(monkeypatch, asyncio.Barrier(2), ParticipantRepository, "get_by_name")
    args = cli._build_parser().parse_args(
        ["init", "--name", OWNER_NAME, "--description", "Владелец", "--token-name", "race"]
    )

    try:
        codes = await asyncio.gather(cli._run(cli._init, args), cli._run(cli._init, args))
    finally:
        async with committing_sessions() as session:
            await session.execute(
                text(
                    "DELETE FROM tokens WHERE participant_id IN "
                    "(SELECT id FROM participants WHERE name = :name)"
                ),
                {"name": OWNER_NAME},
            )
            await session.execute(
                text("DELETE FROM participants WHERE name = :name"), {"name": OWNER_NAME}
            )
            await session.commit()

    assert sorted(codes) == [0, 1], codes
    errors = capsys.readouterr().err
    assert "conflict: Database constraint violated" in errors, errors
    assert "uq_participants_name" in errors, errors
    assert "Traceback" not in errors, errors
