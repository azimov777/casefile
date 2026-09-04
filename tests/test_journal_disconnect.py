"""Долгий опрос ленты прекращается, когда клиент ушёл.

Проверка идёт на уровне ASGI, а не через `httpx`: клиент библиотеки отключение не
изображает — он либо дожидается ответа, либо снимает свою задачу, и серверная корутина
про это не узнаёт. Приложение здесь вызывается напрямую, а канал `receive` подсовывает
сообщение `http.disconnect` в нужный момент — ровно то, что присылает настоящий сервер,
когда сокет закрылся.

Порог проверки — контрольный опрос: ожидание спит до оповещения или до него, и раньше
конца паузы узнать об уходе неоткуда. Интервал на время теста укорочен, иначе проверка
стоила бы пяти секунд прогона и всё равно проверяла бы то же самое.
"""

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.services import journal as journal_service

#: Номер, после которого записей заведомо нет: хвост пуст, и запрос уходит ждать.
BEYOND_THE_TAIL = 10**9

#: Сколько ждал бы запрос, если бы уход клиента остался незамеченным.
WAIT_SECONDS = 30

#: Контрольный опрос на время проверки. Настоящие пять секунд дали бы то же самое,
#: только медленнее.
POLL_INTERVAL = 0.5


@pytest.fixture
def quick_poll(monkeypatch: pytest.MonkeyPatch) -> float:
    """Укорачивает контрольный опрос ленты. Настройки берутся функцией, её и подменяем."""
    tuned = get_settings().model_copy(update={"journal_wait_poll_interval": POLL_INTERVAL})
    monkeypatch.setattr(journal_service, "get_settings", lambda: tuned)
    return POLL_INTERVAL


async def test_the_wait_stops_within_a_poll_after_the_client_is_gone(
    app: FastAPI,
    main_secret: str,
    quick_poll: float,
) -> None:
    """Обзорная проверка 5: ушедший клиент прекращает ожидание, не досиживая до `wait`.

    Ответ при этом обычный и пустой: отдавать его уже некому, но и ошибкой уход клиента
    не является — в логах установки его быть не должно.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/journal",
        "raw_path": b"/api/v1/journal",
        "query_string": f"wait={WAIT_SECONDS}&after={BEYOND_THE_TAIL}".encode(),
        "root_path": "",
        "headers": [
            (b"host", b"tracker.test"),
            (b"authorization", f"Bearer {main_secret}".encode()),
        ],
        "client": ("127.0.0.1", 51234),
        "server": ("tracker.test", 80),
    }
    gone = asyncio.Event()
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        """Канал запроса: до ухода молчит, после — отдаёт `http.disconnect`.

        Молчание именно бесконечное, а не «пустое сообщение»: `Request.is_disconnected`
        читает канал под уже отменённой областью, то есть спрашивает «есть ли сообщение
        прямо сейчас», и на ожидании просто отвечает «нет».
        """
        if gone.is_set():
            return {"type": "http.disconnect"}
        await asyncio.sleep(WAIT_SECONDS * 2)
        raise AssertionError("канал запроса не должен был дождаться конца ожидания")

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    loop = asyncio.get_running_loop()
    request = asyncio.create_task(app(scope, receive, send))
    # Запрос успевает дойти до ожидания: хвост пуст, и он засыпает до опроса.
    await asyncio.sleep(POLL_INTERVAL / 2)
    assert not request.done(), "запрос не ушёл в ожидание, проверять нечего"

    gone.set()
    left = loop.time()
    await asyncio.wait_for(request, timeout=POLL_INTERVAL * 4)
    waited = loop.time() - left

    assert waited < POLL_INTERVAL * 3, (
        f"ожидание держалось ещё {waited:.1f} секунд после ухода клиента"
    )
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 200
