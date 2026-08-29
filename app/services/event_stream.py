"""Живой поток событий: что отдавать соединению и когда его будить.

## Поток читает outbox, а не получает событие от подписчика

Соединения живут в процессах API, а подписчик шины работает в воркере — разные
процессы, и передать между ними объект нечем. Поэтому подписчик только **будит**
(`app/services/stream_subscriber.py`), а событие каждый поток читает сам, со своим
курсором. Побочная выгода важнее исходной причины: переподключение решается тем же
запросом, что и обычное чтение, — клиент просто продолжает с той позиции, на которой
оборвался.

## Окно переподключения — это `outbox_events`

Своего хранилища недавних событий у потока нет и заводить его нельзя: очередь событий
уже хранит всё. Отсюда честная граница обещания — `stream_replay_limit`. Клиент,
отставший больше чем на этот запас, получает отказ с просьбой перечитать состояние
через API, а не молчаливый старт «с текущего момента»: тихий пропуск означал бы
клиента, который считает себя синхронизированным, не будучи им.

Очередь чистится по сроку хранения (`app/services/retention.py`), и обещание от этого
не сужается: чистка не трогает `stream_replay_limit + 1` самых свежих событий, каким бы
старым ни был этот хвост. Единственное, чего пол не покрывает, — поток, суженный
`event_types`: он считает отставание только по своим типам, поэтому в абсолютных
событиях его окно шире. Обещание поэтому абсолютно: `stream_replay_limit` событий всей
очереди.

## Соединение не держит транзакцию

Сессия открывается на время выборки и закрывается перед сном. Поток живёт часами, и
соединение из пула, удерживаемое всё это время, исчерпало бы пул на десятке клиентов —
ровно та же причина, по которой отпускает соединение ожидание инбокса.

## Число соединений ограничено

Каждое соединение — открытый сокет и периодическое обращение к базе. Потолок задан
настройкой и проверяется до начала потока: отказ `429` клиент повторит через паузу, а
поток, открытый сверх ресурсов, ронял бы обслуживание всем остальным.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models.actor import Actor
from app.db.repositories import OutboxRepository
from app.db.repositories.events import StreamPosition
from app.db.wakeup import BROADCAST_KEY, stream_hub
from app.domain.errors import InvalidStreamCursorError, StreamConnectionLimitError
from app.domain.event_stream import StreamFilter, build_event_view
from app.domain.notifications import audience_of
from app.services.permissions import ensure_allowed

logger = get_logger("events.stream")

#: Сколько событий поток забирает из очереди за раз. Пачками, а не по одному: волна из
#: массового переноса статусов даёт сотни событий подряд, и запрос на каждое превратил
#: бы догоняющее чтение в сотню обращений к базе.
STREAM_BATCH_SIZE = 100

#: Пауза переподключения, которую поток советует клиенту (поле `retry` в SSE). Совет, а
#: не гарантия: браузер вправе её увеличить, но без неё он переподключается сразу и
#: заваливает упавший сервер запросами.
RECONNECT_DELAY_MS = 3000

#: Фабрика сессий: контекстный менеджер, открывающий и закрывающий транзакцию. Поток
#: получает её параметром, а не берёт импортом, чтобы тест мог подсунуть свою сессию —
#: и чтобы было видно, что сессия здесь живёт короче самого потока.
type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class StreamMessage:
    """Одно сообщение потока: событие или служебный тик.

    Тик (`comment`) нужен не для красоты. Он не даёт прокси закрыть простаивающее
    соединение и даёт серверу обнаружить ушедшего клиента: запись в закрытый сокет
    падает, и генератор завершается вместо того, чтобы висеть до перезапуска процесса.
    """

    event_id: str | None = None
    event_type: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    comment: str | None = None

    @property
    def is_heartbeat(self) -> bool:
        return self.comment is not None


class StreamSlots:
    """Счётчик открытых потоков процесса.

    Живёт в сценариях, а не в HTTP-слое, намеренно: потолок обязан действовать на любой
    интерфейс, который откроет поток, — и на REST, и на MCP. Счётчик, а не семафор:
    ждать освободившегося места не нужно, лишнему клиенту надо отказать сразу.
    """

    def __init__(self) -> None:
        self._open = 0

    @property
    def open(self) -> int:
        return self._open

    def acquire(self, *, limit: int) -> None:
        """Занимает место или отказывает сразу.

        Пара `acquire`/`release` вместо одного контекстного менеджера нужна потому, что
        занятие и освобождение живут в разных местах: место занимается **до** начала
        потока (отказ после первого отданного байта клиент увидел бы как обрыв без
        объяснения), а освобождается в генераторе, когда чтение закончилось.
        """
        if self._open >= limit:
            raise StreamConnectionLimitError(details={"open": self._open, "limit": limit})
        self._open += 1

    def release(self) -> None:
        """Возвращает место. Ниже нуля не уходит: лишний вызов — ошибка, но не авария."""
        self._open = max(self._open - 1, 0)

    @contextlib.contextmanager
    def take(self, *, limit: int) -> Iterator[None]:
        """Занять и обязательно вернуть. Для вызывающих, у которых оба конца рядом."""
        self.acquire(limit=limit)
        try:
            yield
        finally:
            self.release()


#: Счётчик процесса. Реплики API считают свои соединения независимо — потолок задан на
#: процесс, потому что ограничен пул соединений именно процесса.
slots = StreamSlots()


def connection_limit() -> int:
    """Потолок открытых потоков процесса.

    Отдельная функция, а не чтение настройки по месту: потолок обязан быть одинаковым у
    всех интерфейсов, которые откроют поток, — и у REST, и у MCP в задаче 16.
    """
    return get_settings().stream_max_connections


async def resolve_position(
    session: AsyncSession,
    *,
    initiator: Actor,
    last_event_id: uuid.UUID | None,
    stream_filter: StreamFilter,
) -> StreamPosition | None:
    """Позиция, с которой поток начинает выдачу.

    Без курсора — конец очереди: клиент просит «что будет дальше», а не историю
    установки. С курсором — позиция названного события, и здесь же проверяется, что
    отставание влезает в окно переподключения.

    Неизвестное событие — отказ, а не тихий старт с конца. Клиент, переподключившийся с
    потерянным курсором, обязан узнать о разрыве: иначе он решит, что за время обрыва
    ничего не происходило, и разойдётся с сервером незаметно для себя.
    """
    ensure_allowed(initiator, "event.stream")
    repository = OutboxRepository(session)
    if last_event_id is None:
        return await repository.latest_position()

    event = await repository.get(last_event_id)
    if event is None:
        raise InvalidStreamCursorError(
            details={"last_event_id": str(last_event_id), "reason": "unknown_event"},
        )

    position = (event.created_at, event.id)
    limit = get_settings().stream_replay_limit
    behind = await repository.count_after(
        position=position,
        event_types=stream_filter.event_types,
    )
    if behind > limit:
        raise InvalidStreamCursorError(
            details={
                "last_event_id": str(last_event_id),
                "reason": "too_far_behind",
                "behind": behind,
                "limit": limit,
            },
        )
    return position


async def list_events(
    session: AsyncSession,
    *,
    initiator: Actor,
    stream_filter: StreamFilter,
    limit: int | None = None,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Страница ленты событий: то же, что отдаёт поток, но запросом.

    Нужна там, где поток не помогает: клиент, отставший больше окна переподключения,
    получает отказ и догоняет историю отсюда, а не гадает, что пропустил.

    Сужение по очереди, проекту и задаче применяется **после** выборки страницы —
    считать его можно только по нагрузке события. Отсюда следствие, записанное и в
    описании эндпоинта: страница бывает короче запрошенного размера, а `next_cursor`
    при этом верен. Отбрасывать курсор ради ровных страниц значило бы читать всю
    очередь событий установки ради одной страницы.
    """
    ensure_allowed(initiator, "event.list")
    page = await OutboxRepository(session).list_page(
        event_types=stream_filter.event_types,
        limit=limit,
        cursor=cursor,
    )
    views = []
    for event in page.items:
        audience = audience_of(event.event_type, event.payload)
        if not stream_filter.accepts(event.event_type, audience):
            continue
        views.append(
            build_event_view(
                event_id=str(event.id),
                event_type=event.event_type,
                object_type=event.object_type,
                object_key=event.object_key,
                actor_key=event.actor_key,
                occurred_at=event.created_at,
                payload=event.payload,
                audience=audience,
            )
        )
    return views, page.next_cursor


async def stream_events(
    sessions: SessionFactory,
    *,
    stream_filter: StreamFilter,
    position: StreamPosition | None,
) -> AsyncIterator[StreamMessage]:
    """Бесконечный поток сообщений: события по мере появления, между ними тики.

    Останавливается только тогда, когда его перестают читать, — то есть когда клиент
    отключился и потребитель генератора закрыл его. Освобождение места в счётчике
    соединений и снятие регистрации в хабе идут через контекстные менеджеры, поэтому
    случиться при этом обязаны оба, каким бы способом чтение ни закончилось.

    Регистрация в хабе идёт **до** первой выборки: событие, появившееся между выборкой
    и подпиской, иначе никого не разбудило бы, и поток простоял бы до контрольного
    опроса при непустой очереди.
    """
    settings = get_settings()
    loop = asyncio.get_running_loop()
    last_sent = loop.time()

    async with stream_hub.waiting_for(BROADCAST_KEY) as woken:
        while True:
            # Флаг сбрасывается **до** выборки: событие, пришедшее во время неё, оставит
            # его взведённым, и следующий круг не уйдёт спать, имея непрочитанное.
            woken.clear()
            async with sessions() as session:
                events = await OutboxRepository(session).list_after(
                    position=position,
                    event_types=stream_filter.event_types,
                    limit=STREAM_BATCH_SIZE,
                )

            for event in events:
                position = (event.created_at, event.id)
                audience = audience_of(event.event_type, event.payload)
                if not stream_filter.accepts(event.event_type, audience):
                    continue
                yield StreamMessage(
                    event_id=str(event.id),
                    event_type=event.event_type,
                    data=build_event_view(
                        event_id=str(event.id),
                        event_type=event.event_type,
                        object_type=event.object_type,
                        object_key=event.object_key,
                        actor_key=event.actor_key,
                        occurred_at=event.created_at,
                        payload=event.payload,
                        audience=audience,
                    ),
                )
                last_sent = loop.time()

            if len(events) == STREAM_BATCH_SIZE:
                # Пачка забита целиком — очередь наверняка не разобрана до конца, и
                # засыпать здесь значило бы отдавать догоняющие события порциями раз в
                # несколько секунд.
                continue

            await _sleep_until_woken(woken, settings.stream_poll_interval)
            if loop.time() - last_sent >= settings.stream_heartbeat_interval:
                last_sent = loop.time()
                yield StreamMessage(comment="ping")


async def _sleep_until_woken(woken: asyncio.Event, seconds: float) -> None:
    """Пауза, которую прерывает оповещение о новом событии.

    Таймаут здесь — контрольный опрос, а не основной механизм: он страхует от
    оборванного соединения слушателя, из-за которого поток иначе молчал бы при
    наполняющейся очереди.
    """
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(woken.wait(), timeout=seconds)
