"""Поток журнала (SSE): форма кадра и переподключение по `Last-Event-ID`.

## Почему здесь нет httpx

`ASGITransport`, на котором работает клиент остальных тестов API, **собирает тело
целиком** и только потом отдаёт ответ. Для бесконечного потока это означает не провал, а
зависший прогон: тест ждал бы конца ответа, которого не будет. Поэтому кадры читаются
прямо из ASGI — приложение вызывается как есть, а сообщения `http.response.body`
разбираются по мере поступления. Проверяется при этом весь стек: маршрутизация,
аутентификация, заголовки ответа и само разбиение на кадры.

Читатель ограничен и по числу кадров, и по времени: тест, забывший про то или другое,
не падает, а висит.

## Почему поток и тест делят одну сессию безопасно

Поток открывает сессию только в начале круга, забирает пачку и потом отдаёт кадры уже
без базы, а закончив пачку — засыпает до оповещения или до контрольного опроса. К моменту,
когда читатель набрал нужное число кадров и снимает задачу, поток спит, а не ждёт ответа
базы. Сессия теста поэтому не может оказаться отменённой посреди запроса.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_factory
from app.db.models.entry import Entry
from app.db.models.task import Task
from app.domain.case import EntryType
from app.services import case as case_service
from app.services import journal as journal_service
from app.services.auth import Actor

STREAM = "/api/v1/journal/stream"

#: Потолок ожидания кадров, которые обязаны прийти сразу: поток отдаёт уже подшитое
#: первой же выборкой. Нужен ровно затем, чтобы провал выглядел как провал.
READ_TIMEOUT = 10.0


@pytest.fixture
def streaming_app(app: FastAPI, db_session: AsyncSession) -> FastAPI:
    """Приложение, у которого и запрос, и поток ходят в транзакцию теста.

    Фабрика сессий подменяется отдельно от самой сессии: поток открывает её на каждую
    выборку и закрывает сразу — как и в бою, где держать соединение всё время потока
    нельзя. Здесь она повторяет `session_scope` на сессии теста.
    """

    @asynccontextmanager
    async def _scope() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise
        else:
            await db_session.commit()

    app.dependency_overrides[get_session_factory] = lambda: _scope
    return app


@pytest.fixture
async def entries(
    db_session: AsyncSession,
    task_actor: Actor,
    task: Task,
) -> list[Entry]:
    """Четыре записи в деле: хватает, чтобы оборвать поток посередине."""
    return [
        await case_service.add_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.FINDING,
            title=f"Находка {number}",
        )
        for number in range(1, 5)
    ]


def _scope_for(query: str, headers: dict[str, str]) -> dict[str, Any]:
    """Минимальный ASGI-запрос к потоку. Заголовки — байты, как их видит сервер."""
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": STREAM,
        "raw_path": STREAM.encode(),
        "root_path": "",
        "query_string": query.encode(),
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": ("127.0.0.1", 45678),
        "server": ("tracker.test", 80),
    }


async def read_frames(
    app: FastAPI,
    secret: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    count: int,
) -> list[dict[str, str]]:
    """Открывает поток, забирает `count` кадров с данными и закрывает его.

    Строку `retry:` и тики (строки-комментарии) пропускает: они часть транспорта, а не
    содержимого. Каждый кадр приезжает отдельным сообщением `http.response.body`,
    потому что обработчик отдаёт его одним `yield`.
    """
    query = urlencode(params or {}, doseq=True)
    request_headers = {"host": "tracker.test", "authorization": f"Bearer {secret}"}
    request_headers.update(headers or {})

    events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    gone = asyncio.Event()
    body_sent = False

    async def receive() -> dict[str, Any]:
        """Тело один раз, дальше — молчание до ухода клиента.

        Отвечать `http.request` бесконечно нельзя: Starlette слушает отключение клиента
        в своём цикле `while True: await receive()`, и корутина, возвращающая значение
        не засыпая, превращает этот цикл в занятое ожидание — прогон встаёт целиком,
        включая собственный таймаут читателя. Стоило часа.
        """
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        await events.put(message)

    runner = asyncio.create_task(app(_scope_for(query, request_headers), receive, send))
    frames: list[dict[str, str]] = []
    try:
        async with asyncio.timeout(READ_TIMEOUT):
            start = await events.get()
            assert start["type"] == "http.response.start", start
            assert start["status"] == 200, start
            headers_of_response = {
                name.decode(): value.decode() for name, value in start["headers"]
            }
            assert headers_of_response["content-type"].startswith("text/event-stream")
            assert headers_of_response["cache-control"] == "no-cache"
            while len(frames) < count:
                message = await events.get()
                assert message["type"] == "http.response.body", message
                chunk = message.get("body", b"").decode()
                if not chunk.strip() or chunk.startswith(":") or chunk.startswith("retry:"):
                    continue
                frames.append(
                    dict(line.split(": ", 1) for line in chunk.strip().split("\n"))  # type: ignore[misc,arg-type]
                )
    finally:
        # Клиент уходит так же, как ушёл бы настоящий: обрывом соединения. Поток
        # обязан от этого закончиться сам и вернуть место в лимите — снятие задачи
        # проверяло бы не то поведение, а отмену изнутри.
        gone.set()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(runner, timeout=READ_TIMEOUT)
        if not runner.done():
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
    return frames


async def test_a_frame_carries_the_sequence_number_the_type_and_the_entry(
    streaming_app: FastAPI,
    main_secret: str,
    entries: list[Entry],
    task: Task,
) -> None:
    """`id:` — это `seq`, `event:` — тип записи, `data:` — та же запись, что у ленты."""
    frames = await read_frames(
        streaming_app, main_secret, params={"after": entries[0].seq - 1}, count=1
    )

    assert frames[0]["id"] == str(entries[0].seq)
    assert frames[0]["event"] == entries[0].type.value
    payload = json.loads(frames[0]["data"])
    assert payload["seq"] == entries[0].seq
    assert payload["no"] == entries[0].no
    assert payload["type"] == entries[0].type.value
    assert payload["task_key"] == task.key


async def test_a_broken_stream_resumes_right_after_the_last_event_id(
    streaming_app: FastAPI,
    main_secret: str,
    entries: list[Entry],
) -> None:
    """Обзорная проверка 5: продолжение без пропусков и без повторов.

    Первый поток обрывается после второго кадра, второй открывается с `Last-Event-ID`
    этого кадра — и начинает ровно со следующей записи. Окна переподключения у ленты нет
    и не нужно: записи постоянны, догнать можно с любого номера.
    """
    first = await read_frames(
        streaming_app, main_secret, params={"after": entries[0].seq - 1}, count=2
    )

    resumed = await read_frames(
        streaming_app, main_secret, headers={"Last-Event-ID": first[-1]["id"]}, count=2
    )

    assert [frame["id"] for frame in first] == [str(entries[0].seq), str(entries[1].seq)]
    assert [frame["id"] for frame in resumed] == [str(entries[2].seq), str(entries[3].seq)]


async def test_the_query_parameter_replaces_the_header_for_clients_that_cannot_set_it(
    streaming_app: FastAPI,
    main_secret: str,
    entries: list[Entry],
) -> None:
    """Браузерный `EventSource` заголовков не шлёт, а токен в адрес мы класть не стали."""
    frames = await read_frames(
        streaming_app, main_secret, params={"last_event_id": entries[1].seq}, count=1
    )

    assert frames[0]["id"] == str(entries[2].seq)


async def test_the_filters_of_the_stream_are_the_filters_of_the_feed(
    streaming_app: FastAPI,
    main_secret: str,
    db_session: AsyncSession,
    task_actor: Actor,
    task: Task,
    entries: list[Entry],
) -> None:
    """Сужение по типу пропускает чужие записи: фильтры у ленты и у потока одни."""
    note = await case_service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка"
    )

    frames = await read_frames(
        streaming_app,
        main_secret,
        params={"after": entries[0].seq - 1, "types": ["note"]},
        count=1,
    )

    assert frames[0]["id"] == str(note.seq)
    assert frames[0]["event"] == "note"


async def test_the_stream_gives_its_slot_back_when_the_client_goes_away(
    streaming_app: FastAPI,
    main_secret: str,
    entries: list[Entry],
) -> None:
    """Иначе место оставалось бы занятым до перезапуска процесса."""
    await read_frames(streaming_app, main_secret, params={"after": entries[0].seq - 1}, count=1)

    assert journal_service.slots.open == 0


async def test_a_stream_over_the_connection_limit_is_refused_before_the_first_byte(
    streaming_app: FastAPI,
    auth_client: AsyncClient,
    entries: list[Entry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Потолок соединений — `429` до потока, а не оборванный `200` посреди кадров.

    Отказ идёт обычным клиентом: до кадров дело не доходит, поэтому бесконечного тела,
    на котором зависает `ASGITransport`, здесь нет.
    """
    monkeypatch.setattr(journal_service, "connection_limit", lambda: 0)

    response = await auth_client.get(STREAM)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "journal_stream_limit"
    assert journal_service.slots.open == 0, "отказ не должен занимать место в лимите"


async def test_the_stream_gives_project_entries_under_the_project_filter(
    streaming_app: FastAPI,
    main_secret: str,
    db_session: AsyncSession,
    task_actor: Actor,
    task: Task,
    entries: list[Entry],
) -> None:
    """Обзорная проверка 3 TRK-156: поток с отбором `project` отдаёт и запись дела проекта
    — с ключом проекта и без ключа задачи."""
    note = await case_service.append_project_entry(
        db_session, task.project, actor=task_actor, type="note", title="Заметка проекта"
    )

    frames = await read_frames(
        streaming_app,
        main_secret,
        params={"after": entries[-1].seq, "project": "TRK"},
        count=1,
    )

    payload = json.loads(frames[0]["data"])
    assert frames[0]["id"] == str(note.seq)
    assert (payload["task_key"], payload["project_key"], payload["no"]) == (None, "TRK", note.no)
