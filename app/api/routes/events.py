"""Живой поток событий для фронтенда (SSE).

## Единственное место в API без оболочки `data`

Соглашения проекта требуют одинаковой оболочки у всех ответов, и здесь её нет — не по
недосмотру, а потому что её нет в самом формате `text/event-stream`: кадр состоит из
строк `id:`, `event:` и `data:`, и завернуть его во что-то ещё нельзя, не перестав быть
SSE. Контракт от этого не теряется: полезная нагрузка каждого кадра описана схемой
`StreamEventRead`, и генератор клиента её видит.

## Поток читается fetch-клиентом, а не голым `EventSource`

Браузерный `EventSource` не умеет слать заголовки, а весь `/api/v1` защищён токеном в
`Authorization`. Принимать токен ещё и параметром запроса ради него мы не стали: он
уехал бы в журналы прокси, в историю браузера и в `Referer`, а токен в этом проекте даёт
полный доступ к API. Фронтенд открывает поток `fetch`-клиентом (например,
`@microsoft/fetch-event-source`), который заголовки поддерживает и умеет
переподключаться сам.

## Переподключение

Клиент присылает `Last-Event-ID` (или параметр `last_event_id`, если клиент его не
умеет) — идентификатор последнего полученного события. Поток продолжает ровно с него.
Неизвестный идентификатор и слишком большое отставание — `422`, а не тихий старт с
конца: клиент, пропустивший события и не знающий об этом, разошёлся бы с сервером
незаметно для себя.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from app.api.deps import (
    CurrentActorDep,
    CursorQuery,
    LimitQuery,
    SessionDep,
    StreamSessionsDep,
)
from app.api.schemas.common import CollectionResponse
from app.api.schemas.events import StreamEventRead
from app.core.logging import get_logger
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.errors import InvalidStreamCursorError
from app.domain.event_stream import (
    MAX_FILTER_EVENT_TYPES,
    StreamFilter,
    parse_event_types,
    parse_last_event_id,
)
from app.services import event_stream as service
from app.services.event_stream import RECONNECT_DELAY_MS, StreamMessage

logger = get_logger("api.events")

router = APIRouter(prefix="/events", tags=["events"])

QueueQuery = Annotated[str | None, Query(description="Only events of this queue")]
ProjectQuery = Annotated[
    str | None,
    Query(description="Only events of this project or portfolio"),
]
IssueQuery = Annotated[str | None, Query(description="Only events of this issue")]
EventTypesQuery = Annotated[
    list[str] | None,
    Query(
        max_length=MAX_FILTER_EVENT_TYPES,
        description=(
            "Only these event types; omit for the whole stream. Unknown types are "
            "accepted here, unlike in a subscription: a stream lives for minutes and its "
            "emptiness is visible immediately, so a frontend may filter by a type this "
            "server does not know yet"
        ),
    ),
]
LastEventIdHeader = Annotated[
    str | None,
    Header(
        alias="Last-Event-ID",
        description="Id of the last event received; the stream resumes right after it",
    ),
]
LastEventIdQuery = Annotated[
    str | None,
    Query(description="Same as the `Last-Event-ID` header, for clients that cannot set it"),
]


class EventStreamResponse(StreamingResponse):
    """`StreamingResponse` с типом `text/event-stream`.

    Классом ответа маршрута (`response_class`) он намеренно **не** объявлен, хотя это
    выглядело бы уместнее. FastAPI берёт из класса ответа тип содержимого для **всех**
    ответов операции, включая ошибки, — и `401` в схеме оказался бы описан как
    `text/event-stream`, хотя ошибки приходят обычным JSON-конвертом. Поэтому тип
    содержимого потока задан вручную в `responses`, а сам класс просто возвращается из
    обработчика. Дефект поймал `tests/test_openapi.py`, а не чтение схемы глазами.
    """

    media_type = "text/event-stream"


def render(message: StreamMessage) -> str:
    """Одно сообщение в виде кадра SSE.

    Формат — часть транспорта, поэтому живёт здесь, а не в сценарии: сценарий отдаёт
    данные, HTTP-слой решает, как они выглядят в сети. Кадр всегда заканчивается пустой
    строкой — именно она отделяет события друг от друга, и без неё клиент будет ждать
    продолжения текущего кадра до самого закрытия соединения.
    """
    if message.is_heartbeat:
        # Строка-комментарий: клиент её игнорирует, а прокси видит трафик и не закрывает
        # соединение как простаивающее.
        return f": {message.comment}\n\n"
    data = json.dumps(message.data, ensure_ascii=False)
    return f"id: {message.event_id}\nevent: {message.event_type}\ndata: {data}\n\n"


@router.get("", summary="List events")
async def list_events(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueQuery = None,
    project: ProjectQuery = None,
    issue: IssueQuery = None,
    event_types: EventTypesQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[StreamEventRead]:
    """Лента событий страницами: то же, что отдаёт поток, но запросом.

    Нужна там, где поток не помогает. Клиент, отставший больше окна переподключения,
    получает от потока отказ `invalid_stream_cursor` — и догоняет пропущенное отсюда,
    а не гадает, что именно потерял.

    Сужение по очереди, проекту и задаче применяется **после** выборки страницы: считать
    его можно только по нагрузке события. Поэтому страница бывает короче запрошенного
    размера, а `meta.next_cursor` при этом верен — листать надо до `has_more: false`, а
    не до первой неполной страницы.
    """
    views, next_cursor = await service.list_events(
        session,
        initiator=current_actor,
        stream_filter=StreamFilter(
            queue=queue,
            project=project,
            issue=issue,
            event_types=parse_event_types(event_types),
        ),
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[StreamEventRead].of(
        [StreamEventRead(**view) for view in views],
        next_cursor=next_cursor,
    )


@router.get(
    "/stream",
    summary="Stream events as they happen",
    responses={
        200: {
            "description": (
                "An endless `text/event-stream`. Every frame carries the event id in "
                "`id:`, the event type in `event:` and the payload in `data:`. Lines "
                "starting with `:` are heartbeats and carry no data"
            ),
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/StreamEventRead"}}
            },
        },
        422: {"description": "Unknown or too old `Last-Event-ID`"},
        429: {"description": "Too many open streams on this server"},
    },
)
async def stream_events(
    session: SessionDep,
    sessions: StreamSessionsDep,
    current_actor: CurrentActorDep,
    queue: QueueQuery = None,
    project: ProjectQuery = None,
    issue: IssueQuery = None,
    event_types: EventTypesQuery = None,
    last_event_id_header: LastEventIdHeader = None,
    last_event_id: LastEventIdQuery = None,
) -> EventStreamResponse:
    """Открывает поток событий, доступных текущему актору.

    Проверки, способные отказать, идут **до** начала потока: место в лимите соединений и
    разбор курсора переподключения. Отказ после первого отданного байта клиент увидел бы
    как оборванный поток без объяснения — по коду ответа `200` уже не сказать «нельзя».

    Сужение (`queue`, `project`, `issue`, `event_types`) складывается по «и». Считается
    оно по нагрузке события той же функцией, что и адресаты уведомлений: сравнивать
    `object_key` со строкой было бы короче и неверно — у комментария он `TRK-7:<uuid>`,
    и фильтр «по задаче TRK-7» терял бы половину её событий.
    """
    stream_filter = StreamFilter(
        queue=queue,
        project=project,
        issue=issue,
        event_types=parse_event_types(event_types),
    )
    raw_cursor = last_event_id_header or last_event_id
    cursor = parse_last_event_id(raw_cursor)
    if raw_cursor and cursor is None:
        raise InvalidStreamCursorError(
            details={"last_event_id": raw_cursor, "reason": "malformed"},
        )

    position = await service.resolve_position(
        session,
        initiator=current_actor,
        last_event_id=cursor,
        stream_filter=stream_filter,
    )
    # Место занимается здесь, а возвращается в генераторе. Занять его внутри генератора
    # было бы стройнее и неверно: тело начинает выполняться уже после того, как ответ
    # `200` ушёл клиенту, и отказать было бы нечем.
    service.slots.acquire(limit=service.connection_limit())

    async def frames() -> AsyncIterator[str]:
        try:
            yield f"retry: {RECONNECT_DELAY_MS}\n\n"
            async for message in service.stream_events(
                sessions,
                stream_filter=stream_filter,
                position=position,
            ):
                yield render(message)
        finally:
            # `finally` в генераторе срабатывает на любом способе завершить чтение:
            # отключении клиента, остановке сервера, исключении. Без него место
            # оставалось бы занятым до перезапуска процесса.
            service.slots.release()
            logger.debug("Event stream for %s closed", current_actor.key)

    return EventStreamResponse(
        frames(),
        headers={
            # Буферизация обратного прокси накапливает кадры и отдаёт их пачкой, то есть
            # превращает живой поток в опрос с непредсказуемой задержкой. Заголовок
            # понимает nginx; для остальных та же роль у `Cache-Control`.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
