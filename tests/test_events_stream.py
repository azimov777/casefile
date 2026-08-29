"""Живой поток событий: продолжение с курсора, сужение, лимит соединений, кадры SSE.

## HTTP-часть идёт через настоящий сервер, а не через ASGI-транспорт

`ASGITransport` из httpx — тот, на котором работают все остальные тесты API, — ждёт
**завершения** приложения, прежде чем отдать ответ: `await self.app(scope, receive,
send)` и только потом сборка `Response`. Бесконечный поток не завершается никогда,
поэтому такой тест висит до таймаута и не проверяет ничего. Отсюда `live_server`:
uvicorn поднимается в этом же цикле событий, поэтому подмена зависимостей продолжает
работать и поток читает данные транзакции теста.

## Паузы укорочены фикстурой

Поток по умолчанию спит секундами, и тест, честно ждущий контрольного опроса, стоил бы
полминуты на каждую проверку. Механика от этого не меняется — меняются только паузы.

Слушатель оповещений в тестах не поднят (жизненный цикл приложения выключен), и это не
мешает: без него поток переходит на контрольный опрос — ровно то поведение, которое
заявлено на случай оборванного соединения слушателя.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_factory
from app.db.models.actor import Actor
from app.db.models.event import OutboxEvent
from app.db.models.issue import Issue
from app.db.repositories import OutboxRepository
from app.domain.errors import InvalidStreamCursorError, StreamConnectionLimitError
from app.domain.event_stream import StreamFilter
from app.services import event_stream as service
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[Issue]]


@pytest.fixture
def sessions(db_session: AsyncSession) -> service.SessionFactory:
    """Фабрика сессий потока, отдающая транзакцию теста.

    Закрывать сессию нельзя: она общая с тестом, и её откат в конце — граница теста.
    Ровно ради такой подмены поток и получает фабрику параметром.
    """

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _factory


@pytest.fixture
def fast_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Укорачивает паузы потока: проверяется механика, а не терпение."""
    settings = service.get_settings()
    monkeypatch.setattr(settings, "stream_poll_interval", 0.05, raising=False)
    monkeypatch.setattr(settings, "stream_heartbeat_interval", 0.1, raising=False)


@pytest.fixture
async def live_server(
    app: FastAPI,
    sessions: service.SessionFactory,
    owner_secret: str,
) -> AsyncIterator[AsyncClient]:
    """Настоящий HTTP-сервер поверх приложения теста, с клиентом к нему.

    Нужен ровно из-за стриминга: `ASGITransport` отдаёт ответ только после того, как
    приложение закончило работу, а поток не заканчивает её никогда. Сервер поднимается в
    этом же цикле событий, поэтому подменённые зависимости и транзакция теста остаются
    теми же.

    Жизненный цикл выключен (`lifespan="off"`): он поднимал бы слушателя оповещений и
    синхронизировал правила автоматики в базе мимо транзакции теста.
    """
    app.dependency_overrides[get_session_factory] = lambda: sessions
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
        timeout_graceful_shutdown=1,
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    client = AsyncClient(base_url=f"http://127.0.0.1:{port}")
    client.headers["Authorization"] = f"Bearer {owner_secret}"
    try:
        yield client
    finally:
        await client.aclose()
        server.should_exit = True
        await serving


async def positions(session: AsyncSession) -> list[OutboxEvent]:
    statement = select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)
    return list((await session.scalars(statement)).unique().all())


async def take(
    stream: AsyncIterator[service.StreamMessage],
    count: int,
    *,
    timeout: float = 2.0,
) -> list[service.StreamMessage]:
    """Забирает из потока `count` событий, пропуская тики, и закрывает его."""

    async def _collect() -> list[service.StreamMessage]:
        collected: list[service.StreamMessage] = []
        async for message in stream:
            if message.is_heartbeat:
                continue
            collected.append(message)
            if len(collected) == count:
                break
        return collected

    try:
        return await asyncio.wait_for(_collect(), timeout=timeout)
    finally:
        await stream.aclose()


# --- Начальная позиция ---------------------------------------------------------------


async def test_a_stream_without_a_cursor_starts_at_the_end(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
) -> None:
    """Клиент без курсора просит «что будет дальше», а не историю установки."""
    await make_issue()
    events = await positions(db_session)

    position = await service.resolve_position(
        db_session,
        initiator=owner,
        last_event_id=None,
        stream_filter=StreamFilter(),
    )

    assert position == (events[-1].created_at, events[-1].id)


async def test_an_unknown_cursor_is_refused_instead_of_silently_starting_over(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Иначе клиент решит, что за время обрыва ничего не происходило."""
    with pytest.raises(InvalidStreamCursorError) as error:
        await service.resolve_position(
            db_session,
            initiator=owner,
            last_event_id=uuid.uuid4(),
            stream_filter=StreamFilter(),
        )

    assert error.value.details["reason"] == "unknown_event"


async def test_a_client_too_far_behind_is_told_so(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Окно переподключения — обещание, и его нельзя давать шире, чем система выполняет."""
    settings = service.get_settings()
    monkeypatch.setattr(settings, "stream_replay_limit", 1, raising=False)
    await make_issue()
    await make_issue(summary="Вторая")
    await make_issue(summary="Третья")
    events = await positions(db_session)

    with pytest.raises(InvalidStreamCursorError) as error:
        await service.resolve_position(
            db_session,
            initiator=owner,
            last_event_id=events[0].id,
            stream_filter=StreamFilter(),
        )

    assert error.value.details["reason"] == "too_far_behind"
    assert error.value.details["behind"] == 2


# --- Выдача -------------------------------------------------------------------------


async def test_the_stream_replays_what_was_missed_after_the_cursor(
    db_session: AsyncSession,
    sessions: service.SessionFactory,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    """Переподключение — тот же запрос, что и обычное чтение, только с другой позицией."""
    await make_issue()
    events = await positions(db_session)
    await make_issue(summary="Вторая")

    stream = service.stream_events(
        sessions,
        stream_filter=StreamFilter(),
        position=(events[-1].created_at, events[-1].id),
    )
    (message,) = await take(stream, 1)

    assert message.data["event"]["type"] == "issue.created"
    assert message.data["issue"] == "TRK-2"
    assert message.event_id == message.data["event"]["id"]


async def test_the_stream_keeps_the_order_events_happened_in(
    db_session: AsyncSession,
    sessions: service.SessionFactory,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    """Клиент, восстанавливающий состояние по потоку, иначе получит «закрыта» до «открыта»."""
    await make_issue()
    await make_issue(summary="Вторая")
    await make_issue(summary="Третья")

    stream = service.stream_events(sessions, stream_filter=StreamFilter(), position=None)
    messages = await take(stream, 3)

    assert [message.data["issue"] for message in messages] == ["TRK-1", "TRK-2", "TRK-3"]


async def test_a_queue_filter_drops_events_of_other_queues(
    db_session: AsyncSession,
    owner: Actor,
    sessions: service.SessionFactory,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    other = await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="OPS",
        name="Эксплуатация",
    )
    await make_issue()
    await make_issue(queue=other, summary="Поднять контур")

    stream = service.stream_events(
        sessions,
        stream_filter=StreamFilter(queue="OPS"),
        position=None,
    )
    (message,) = await take(stream, 1)

    assert message.data["issue"] == "OPS-1"


async def test_an_issue_filter_keeps_comments_of_that_issue(
    db_session: AsyncSession,
    owner: Actor,
    sessions: service.SessionFactory,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    """Ключ комментария — `TRK-7:<uuid>`, и сравнение строк потеряло бы это событие."""
    from app.services import comments as comments_service

    issue = await make_issue()
    await comments_service.add_comment(db_session, issue, initiator=owner, body="Взял в работу")

    stream = service.stream_events(
        sessions,
        stream_filter=StreamFilter(issue=issue.key, event_types=frozenset({"comment.created"})),
        position=None,
    )
    (message,) = await take(stream, 1)

    assert message.data["object"]["type"] == "comment"
    assert message.data["issue"] == issue.key


async def test_a_stream_with_nothing_to_say_sends_a_heartbeat(
    db_session: AsyncSession,
    sessions: service.SessionFactory,
    fast_stream: None,
) -> None:
    """Тик не даёт прокси закрыть соединение и обнаруживает ушедшего клиента."""
    stream = service.stream_events(sessions, stream_filter=StreamFilter(), position=None)

    message = await asyncio.wait_for(anext(stream), timeout=2.0)
    await stream.aclose()

    assert message.is_heartbeat


# --- Лимит соединений ----------------------------------------------------------------


async def test_a_stream_over_the_limit_is_refused_at_once() -> None:
    """Отказ сразу и с `429`: клиент повторит через паузу, а не решит, что поток сломан."""
    slots = service.StreamSlots()
    slots.acquire(limit=1)

    with pytest.raises(StreamConnectionLimitError):
        slots.acquire(limit=1)

    slots.release()
    slots.acquire(limit=1)


# --- HTTP ---------------------------------------------------------------------------


async def test_the_endpoint_streams_sse_frames(
    live_server: AsyncClient,
    db_session: AsyncSession,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    """Кадр несёт идентификатор события, его тип и тело — тем, чем продолжают поток."""
    await make_issue()
    events = await positions(db_session)
    await make_issue(summary="Вторая")

    lines: list[str] = []
    async with live_server.stream(
        "GET",
        "/api/v1/events/stream",
        headers={"Last-Event-ID": str(events[-1].id)},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            lines.append(line)
            if line.startswith("data:"):
                break

    assert any(line.startswith("retry:") for line in lines)
    assert "event: issue.created" in lines
    assert any(line.startswith("id: ") for line in lines)


async def test_a_malformed_cursor_is_refused_before_the_stream_starts(
    auth_client: AsyncClient,
) -> None:
    """Отказ после первого отданного байта клиент увидел бы как обрыв без объяснения."""
    response = await auth_client.get(
        "/api/v1/events/stream",
        headers={"Last-Event-ID": "not-a-uuid"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_stream_cursor"


async def test_the_open_stream_counter_returns_the_slot_after_the_client_leaves(
    live_server: AsyncClient,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    """Незакрытый счётчик означал бы отказ всем новым клиентам до перезапуска процесса."""
    await make_issue()

    async with live_server.stream("GET", "/api/v1/events/stream") as response:
        async for line in response.aiter_lines():
            if line.startswith(":"):
                break
        assert service.slots.open == 1

    # Место возвращает `finally` генератора, а он срабатывает не в момент разрыва, а
    # когда сервер дочитал закрытое соединение, — поэтому проверка с ожиданием.
    for _ in range(100):
        if service.slots.open == 0:
            break
        await asyncio.sleep(0.05)
    assert service.slots.open == 0


async def test_the_cursor_counts_only_the_types_the_stream_asked_for(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отставание считается по тому же отбору, каким поток читает: иначе окно врало бы."""
    settings = service.get_settings()
    monkeypatch.setattr(settings, "stream_replay_limit", 1, raising=False)
    await make_issue()
    await make_issue(summary="Вторая")
    await make_issue(summary="Третья")
    events = await positions(db_session)

    behind = await OutboxRepository(db_session).count_after(
        position=(events[0].created_at, events[0].id),
        event_types=frozenset({"comment.created"}),
    )

    assert behind == 0
    assert await service.resolve_position(
        db_session,
        initiator=owner,
        last_event_id=events[0].id,
        stream_filter=StreamFilter(event_types=frozenset({"comment.created"})),
    ) == (events[0].created_at, events[0].id)


# --- Лента запросом ------------------------------------------------------------------


async def test_the_event_feed_answers_what_a_client_missed(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    """Клиент, отставший больше окна переподключения, догоняет историю отсюда."""
    await make_issue()
    await make_issue(summary="Вторая")

    response = await auth_client.get("/api/v1/events", params={"event_types": "issue.created"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["issue"] for item in body["data"]] == ["TRK-1", "TRK-2"]
    assert body["data"][0]["event"]["type"] == "issue.created"
    assert body["meta"]["has_more"] is False


async def test_the_feed_frame_has_the_same_shape_as_a_stream_frame(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    sessions: service.SessionFactory,
    make_issue: MakeIssue,
    fast_stream: None,
) -> None:
    """Одно событие обязано читаться одинаково запросом и потоком."""
    await make_issue()

    response = await auth_client.get("/api/v1/events")
    (from_feed,) = response.json()["data"]

    stream = service.stream_events(sessions, stream_filter=StreamFilter(), position=None)
    (message,) = await take(stream, 1)

    assert from_feed["event"]["id"] == message.data["event"]["id"]
    assert set(from_feed) == set(message.data)


async def test_the_stream_frame_schema_is_published_for_the_client_generator(
    app: FastAPI,
) -> None:
    """Кадр — единственное место API без оболочки `data`, и его форма обязана быть в схеме."""
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)

    stream = schema["paths"]["/api/v1/events/stream"]["get"]["responses"]
    assert "text/event-stream" in stream["200"]["content"]
    reference = stream["200"]["content"]["text/event-stream"]["schema"]["$ref"]
    assert reference.rsplit("/", 1)[-1] in schema["components"]["schemas"]
    # Ошибки приходят обычным JSON-конвертом, и схема обязана говорить именно это.
    assert "application/json" in stream["401"]["content"]
