"""Признак «процессу велено остановиться» и его подписка на сигнал.

Нужен затем, что **в ASGI такого сигнала нет**, а узнать о нём приложению обязательно:
бесконечное чтение — поток ленты — иначе не даёт серверу остановиться никогда
(`docs/notes/docker.md`).

## Почему жизненный цикл приложения не годится

Порядок остановки uvicorn такой: перестать принимать → сказать каждому соединению
`connection.shutdown()` → **дождаться, пока соединения закроются** → и только потом
остановить жизненный цикл приложения. То есть `lifespan`-shutdown срабатывает уже
после ожидания, ради сокращения которого он и понадобился бы.

`connection.shutdown()` тоже не помогает: у h11 он для незавершённого ответа лишь
снимает keep-alive, а генератор продолжает выдавать кадры. И отключения клиента не
приходит: starlette 1.6 при `asgi.spec_version >= 2.4` `http.disconnect` не слушает
вовсе, полагаясь на `OSError` от `send`.

Остаётся сигнал, и к нему можно пристроиться честно: uvicorn ставит свой обработчик
через `signal.signal` (`Server.capture_signals`), а жизненный цикл приложения
запускается **после** этого. Значит `signal.signal` вернёт нам обработчик uvicorn, и наш
позовёт его следом: сервер получит сигнал как раньше, а приложение узнает о нём до
того, как начнётся ожидание соединений.

## Что делает сигнал, кроме взведённого признака

Будит всех, кто спит в ожидании записи журнала. Без этого признак заметили бы только на
следующем круге контрольного опроса — то есть через секунды, — и остановка ровно на
столько же и затянулась бы. Механизм для этого уже есть и используется оповещением
`LISTEN/NOTIFY`; здесь он зовётся вторым поводом, а не заводится заново.

## Чего он не делает

Не отменяет ничего пишущего. Запрос и вызов инструмента, начавшиеся до сигнала,
доводятся до конца в отведённое им время — границу держит `stop_grace_period` в Compose,
а последним рубежом стоит `--timeout-graceful-shutdown` у самого uvicorn. Резать по
таймеру всё подряд нельзя: это тот же обрыв записи, только по расписанию.
"""

import asyncio
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import Any

from app.core.logging import get_logger

logger = get_logger("shutdown")

#: Сигналы остановки, которые ловит uvicorn, — те же ловим и мы.
HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class Shutdown:
    """Признак остановки процесса: взводится один раз и больше не снимается.

    Событие заводится на импорте, до цикла событий: `asyncio.Event` с версии 3.10 к
    циклу при создании не привязывается, и отдельная фабрика была бы лишней.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def started(self) -> bool:
        """Пришёл ли сигнал остановки."""
        return self._event.is_set()

    async def wait(self) -> None:
        """Ждёт сигнала остановки. Возвращается сразу, если он уже пришёл."""
        await self._event.wait()

    def begin(self) -> None:
        """Взводит признак. Зовётся из подписки на сигнал и из тестов."""
        self._event.set()

    def reset(self) -> None:
        """Снимает признак. Нужен только тестам: процесс останавливается один раз."""
        self._event.clear()

    @contextmanager
    def listening(self, *, on_begin: Callable[[], None] | None = None) -> Iterator[None]:
        """Подписка на сигналы остановки на время работы приложения.

        Ставится из жизненного цикла приложения — то есть **после** того, как свои
        обработчики поставил uvicorn, — и на выходе возвращает их на место. Прежний
        обработчик зовётся следом за нашим: без этого сервер перестал бы останавливаться
        вовсе, а не останавливался бы быстрее.

        Признак взводится через `call_soon_threadsafe`: обработчик сигнала прерывает
        цикл событий между байткодами, и трогать его объекты напрямую оттуда нельзя.
        """
        loop = asyncio.get_running_loop()
        previous: dict[int, Any] = {}

        def handle(signum: int, frame: FrameType | None) -> None:
            loop.call_soon_threadsafe(self._begin_and_wake, on_begin)
            chained = previous.get(signum)
            if callable(chained):
                chained(signum, frame)

        for sig in HANDLED_SIGNALS:
            previous[sig] = signal.signal(sig, handle)
        try:
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    def _begin_and_wake(self, on_begin: Callable[[], None] | None) -> None:
        """Взводит признак и будит спящих. Уже в цикле событий, а не в обработчике."""
        if self.started:
            return
        logger.info("Shutdown signalled: reading connections will close, writes will finish")
        self.begin()
        if on_begin is not None:
            on_begin()


#: Признак процесса. Один на процесс, как и сама остановка.
shutdown = Shutdown()
