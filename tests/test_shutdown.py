"""Остановка процесса: поток кончается сам, запись дописывается.

Бесконечное чтение — поток ленты — не давало серверу остановиться никогда: uvicorn
ждёт закрытия соединений, а генератор потока не кончается. На дев-контуре это вешало
API при каждой правке кода, в проде проходило `SIGKILL`-ом по десятисекундному
умолчанию Docker, обрывая заодно и запрос, который в этот момент писал в базу
(`TRK-24`).

Здесь проверяется граница, по которой прошло решение: **чтение закрывается сразу,
запись дописывается**. И отдельно — подписка на сигнал, потому что она обязана не
только сработать, но и не сломать остановку самого сервера: обработчик uvicorn стоял
раньше нашего и должен позваться следом.
"""

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from types import FrameType
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_factory
from app.core.shutdown import HANDLED_SIGNALS, shutdown
from app.db.models.entry import Entry
from app.db.models.task import Task
from app.db.wakeup import journal_wakeup
from app.domain.case import EntryType
from app.services import journal as journal_service
from app.services.auth import Actor
from app.services.journal import JournalFilter

STREAM = "/api/v1/journal/stream"

#: Потолок ожидания конца потока. Поток обязан кончиться сразу — подписка будит спящих,
#: — и потолок нужен затем, чтобы провал выглядел провалом, а не зависшим прогоном.
STOP_TIMEOUT = 10.0


@pytest.fixture(autouse=True)
def clean_shutdown() -> Iterator[None]:
    """Признак остановки — на процесс, а прогон в нём не один.

    Без снятия первый же тест, взведший признак, обесценил бы все следующие: поток
    выходил бы из цикла, не начав работать, и проверка «поток отдаёт кадры» проходила бы
    на пустом месте.
    """
    shutdown.reset()
    yield
    shutdown.reset()


@pytest.fixture
def streaming_app(app: FastAPI, db_session: AsyncSession) -> FastAPI:
    """Приложение, у которого поток ходит в транзакцию теста."""

    @asynccontextmanager
    async def _scope() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session_factory] = lambda: _scope
    return app


async def open_stream(app: FastAPI, secret: str) -> tuple[asyncio.Task[None], asyncio.Queue[Any]]:
    """Открывает поток и отдаёт задачу с очередью его сообщений.

    Читается прямо из ASGI, а не через httpx: `ASGITransport` собирает тело целиком и на
    бесконечном потоке просто повис бы (`tests/test_journal_stream.py`).
    """
    events: asyncio.Queue[Any] = asyncio.Queue()
    body_sent = False
    forever = asyncio.Event()

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        # Клиент никуда не уходит: проверяется остановка сервера, а не отключение
        # клиента. Ждать здесь обязательно — возврат без сна превратил бы цикл
        # Starlette в занятое ожидание и повесил бы весь прогон.
        await forever.wait()
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": STREAM,
        "raw_path": STREAM.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"tracker.test"), (b"authorization", f"Bearer {secret}".encode())],
        "client": ("127.0.0.1", 45678),
        "server": ("tracker.test", 80),
    }
    runner = asyncio.create_task(app(scope, receive, events.put))

    async with asyncio.timeout(STOP_TIMEOUT):
        start = await events.get()
    assert start["type"] == "http.response.start", start
    assert start["status"] == 200, start
    return runner, events


async def test_a_silent_stream_ends_itself_when_the_process_is_told_to_stop(
    streaming_app: FastAPI, main_secret: str, task: Task
) -> None:
    """Обзорная проверка 2: открытый и молчащий поток не держит остановку.

    Молчащий — то есть такой, в чьей ленте ничего не происходит: именно он и висел
    вечно, потому что спал до контрольного опроса и снова спал. Клиент при этом обязан
    увидеть **конец** потока, а не ошибку: ответ уже отдан кодом `200`, и оборвать его
    на середине значило бы сказать «поломка» там, где случилась остановка.
    """
    del task
    runner, events = await open_stream(streaming_app, main_secret)
    try:
        shutdown.begin()

        async with asyncio.timeout(STOP_TIMEOUT):
            await runner
    finally:
        if not runner.done():
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner

    assert runner.exception() is None, "поток обязан закончиться сам, без падения"
    tail = []
    while not events.empty():
        tail.append(events.get_nowait())
    assert tail, "поток закончился, не отдав ни одного сообщения тела"
    assert all(message["type"] == "http.response.body" for message in tail), tail
    assert tail[-1].get("more_body") is False, "последнее сообщение обязано закрыть тело"


async def test_a_write_that_started_before_the_signal_is_finished_and_filed(
    auth_client: AsyncClient, db_session: AsyncSession, task: Task
) -> None:
    """Обзорная проверка 3: сигнал останавливает чтение, но не отменяет запись.

    Проверяется чтением из базы, а не кодом ответа: код `201` сказал бы лишь то, что
    обработчик дошёл до конца, а вопрос в том, осталась ли запись в деле.
    """
    key = task.key
    shutdown.begin()

    response = await auth_client.post(
        f"/api/v1/tasks/{key}/entries",
        json={"type": "finding", "title": "Дописано во время остановки"},
    )

    assert response.status_code == 201, response.text
    filed = await db_session.scalars(
        select(Entry).where(Entry.task_id == task.id, Entry.type == EntryType.FINDING)
    )
    assert [entry.title for entry in filed] == ["Дописано во время остановки"]


async def test_the_subscription_calls_the_handler_that_stood_before_it() -> None:
    """Подписка обязана не сломать остановку сервера, ради ускорения которой поставлена.

    Свой обработчик uvicorn ставит раньше нашего, и наш обязан позвать его следом. Не
    позвал бы — сервер перестал бы останавливаться вовсе: было «долго», стало «никогда».
    Выход из подписки возвращает прежний обработчик на место.
    """
    called: list[int] = []

    def previous(signum: int, frame: FrameType | None) -> None:
        del frame
        called.append(signum)

    installed = {sig: signal.signal(sig, previous) for sig in HANDLED_SIGNALS}
    try:
        with shutdown.listening():
            assert signal.getsignal(signal.SIGTERM) is not previous
            signal.raise_signal(signal.SIGTERM)
            # Признак взводится через цикл событий: обработчик сигнала не вправе
            # трогать его объекты напрямую.
            await asyncio.sleep(0)

            assert called == [signal.SIGTERM], "прежний обработчик не позван"
            assert shutdown.started

        assert signal.getsignal(signal.SIGTERM) is previous, "прежний обработчик не возвращён"
    finally:
        for sig, handler in installed.items():
            signal.signal(sig, handler)


async def test_the_signal_wakes_a_wait_instead_of_letting_it_sit_out_its_timeout(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    """Ожидание ленты возвращается по сигналу, не досиживая свой таймаут.

    Без этого остановка затягивалась бы ровно на остаток ожидания: у `wait_journal` он
    доходит до `MAX_WAIT_SECONDS`, и агент, ждущий ответа, держал бы процесс столько же
    после сигнала. Ждать здесь заведомо нечего — `after` взят заведомо больше любого
    номера, — поэтому пустой ответ до срока и означает, что сигнал сработал.
    """
    del task
    waiting = asyncio.create_task(
        journal_service.wait_journal(
            db_session,
            actor=main_actor,
            journal_filter=JournalFilter(),
            after=10**9,
            wait=30,
        )
    )
    await asyncio.sleep(0.05)

    shutdown.begin()
    journal_wakeup.wake_all()

    async with asyncio.timeout(STOP_TIMEOUT):
        page = await waiting

    assert page.items == [], "ожидание обязано вернуться пустым"
