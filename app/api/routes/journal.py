"""Лента журнала наружу: хвост запросом и тот же хвост потоком.

Роутер только переводит HTTP в вызов сценария и обратно. Фильтры у ленты и у потока
одинаковые и объявлены здесь один раз: разойдясь описаниями, они выглядели бы в
сгенерированном клиенте как разные параметры, хотя это один и тот же отбор.

## Единственное место в API без оболочки `data`

Соглашения требуют одинаковой оболочки у всех ответов, и у потока её нет — не по
недосмотру, а потому что её нет в самом формате `text/event-stream`: кадр состоит из
строк `id:`, `event:` и `data:`, и завернуть его во что-то ещё нельзя, не перестав быть
SSE. Контракт от этого не теряется: полезная нагрузка кадра описана тем же объединением
`EntryRead`, что и элемент ленты `GET /api/v1/journal`, где оболочка обычная. Клиенту,
которому нужна оболочка, поток не нужен — ему нужна лента.

Исключение объявлено кодом в `app/api/contract.py` (`ENVELOPE_EXEMPT`) — вместе с самим
маршрутом, иначе один из двух тестов контракта падает: без строки в списке падает
сплошная проверка оболочки, а со строкой, но без маршрута — проверка «исключение
указывает на существующий маршрут».

## Поток читается fetch-клиентом, а не голым `EventSource`

Браузерный `EventSource` не умеет слать заголовки, а весь `/api/v1` защищён токеном в
`Authorization`. Принимать токен ещё и параметром запроса ради него мы не стали: он
уехал бы в журналы прокси, в историю браузера и в `Referer`, а токен в этом проекте даёт
полный доступ к API. Фронтенд открывает поток `fetch`-клиентом (например,
`@microsoft/fetch-event-source`), который заголовки поддерживает и переподключается сам.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep, StreamSessionsDep
from app.api.schemas.common import CollectionResponse, ErrorResponse
from app.api.schemas.entries import EntryRead, entry_read, entry_read_schema
from app.core.logging import get_logger
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.case import EntryType
from app.domain.journal import (
    DEFAULT_WAIT_SECONDS,
    JOURNAL_START,
    MAX_TASK_KEYS,
    MAX_WAIT_SECONDS,
    parse_last_event_id,
)
from app.services import journal as service
from app.services.journal import RECONNECT_DELAY_MS, JournalMessage

logger = get_logger("api.journal")

router = APIRouter(prefix="/journal", tags=["journal"])

# --- Фильтры. Одни и те же у ленты и у потока ------------------------------------------

AfterQuery = Annotated[
    int,
    Query(
        ge=JOURNAL_START,
        description=(
            "Read only entries after this tracker-wide sequence number. 0 means from the "
            "very beginning: entries are permanent, so any number is a valid position"
        ),
        examples=[1024],
    ),
]
TaskQuery = Annotated[
    list[str] | None,
    Query(
        description=(
            "Only entries of these tasks; matching ignores case. Repeat the parameter or "
            "separate the keys with commas — one key narrows the tail exactly as it "
            f"always did, and at most {MAX_TASK_KEYS} keys fit in one filter. A session "
            "leading several cases asks about all of them at once instead of polling "
            "them one by one. An unknown key answers 422 instead of a silent empty tail"
        ),
        examples=[["TRK-42", "TRK-43"]],
    ),
]
ProjectQuery = Annotated[
    str | None,
    Query(
        description=(
            "Only entries of this project: its own case and the cases of its tasks; "
            "matching ignores case"
        ),
        examples=["TRK"],
    ),
]
TypesQuery = Annotated[
    list[EntryType] | None,
    Query(description="Only entries of these types", examples=[["answer", "status_changed"]]),
]
WaitQuery = Annotated[
    float,
    Query(
        ge=0,
        le=MAX_WAIT_SECONDS,
        description=(
            f"Seconds to wait for a new entry when the tail is empty, at most "
            f"{MAX_WAIT_SECONDS:.0f}. 0 answers right away. The wait is woken by a "
            f"PostgreSQL notification, not by polling, and returns as soon as the first "
            f"matching entry is committed"
        ),
        examples=[30],
    ),
]
LastEventIdHeader = Annotated[
    str | None,
    Header(
        alias="Last-Event-ID",
        description="`seq` of the last frame received; the stream resumes right after it",
    ),
]
LastEventIdQuery = Annotated[
    str | None,
    Query(description="Same as the `Last-Event-ID` header, for clients that cannot set it"),
]


class JournalStreamResponse(StreamingResponse):
    """`StreamingResponse` с типом `text/event-stream`.

    Классом ответа маршрута (`response_class`) он намеренно **не** объявлен, хотя это
    выглядело бы уместнее. FastAPI берёт из класса ответа тип содержимого для **всех**
    ответов операции, включая ошибки, — и `401` в схеме оказался бы описан как
    `text/event-stream`, хотя ошибки приходят обычным JSON-конвертом. Поэтому тип
    содержимого потока задан вручную в `responses`, а сам класс просто возвращается из
    обработчика. Дефект такого рода ловит `tests/test_api_contract.py`, а не чтение
    схемы глазами (выявлено в задаче 15).
    """

    media_type = "text/event-stream"


def render(message: JournalMessage) -> str:
    """Одно сообщение в виде кадра SSE.

    Формат — часть транспорта, поэтому живёт здесь, а не в сценарии: сценарий отдаёт
    данные, HTTP-слой решает, как они выглядят в сети. Кадр всегда заканчивается пустой
    строкой — именно она отделяет события друг от друга, и без неё клиент будет ждать
    продолжения текущего кадра до самого закрытия соединения.

    `id:` кадра — это `seq` записи. Он же приезжает обратно в `Last-Event-ID` при
    переподключении и он же служит параметром `after` у ленты: один номер на все три
    способа читать журнал.
    """
    if message.is_heartbeat:
        # Строка-комментарий: клиент её игнорирует, а прокси видит трафик и не закрывает
        # соединение как простаивающее.
        return f": {message.comment}\n\n"
    assert message.item is not None
    entry = message.item.entry
    data = entry_read(
        entry, task_key=message.item.task_key, project_key=message.item.project_key
    ).model_dump_json()
    return f"id: {entry.seq}\nevent: {entry.type.value}\ndata: {data}\n\n"


@router.get("", summary="Read the journal tail")
async def read_journal(
    request: Request,
    session: SessionDep,
    actor: ActorDep,
    after: AfterQuery = JOURNAL_START,
    task: TaskQuery = None,
    project: ProjectQuery = None,
    types: TypesQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
    wait: WaitQuery = DEFAULT_WAIT_SECONDS,
) -> CollectionResponse[EntryRead]:
    """Записи журнала после сквозного номера `after`, по возрастанию `seq`.

    Отдельной таблицы событий в трекере нет: журнал всех записей дела и есть лента для
    внешнего мира (`CONCEPT.md`, 4.1). Записи постоянны, поэтому догнать ленту можно с
    любого номера, а срока хранения и «слишком старого» курсора не существует.

    Отсюда строится цикл назначателя и живого харнесса: «прочитать хвост с курсора,
    пересчитать кандидатов, запустить харнесс». Различать записи для этого не нужно —
    пересчёт дёшев.

    `wait` превращает чтение в долгое ожидание: ответ приходит, как только появилась
    первая подходящая запись, и не позже, чем через указанное число секунд. Ожидание
    построено на оповещениях PostgreSQL, а не на опросе, и не держит соединение с базой.
    Пустой список по истечении ожидания означает «ничего не случилось» — это не ошибка.
    Ушедший клиент ожидание прекращает: сценарию передаётся `Request.is_disconnected`,
    и брошенный запрос отпускает соединение, не досиживая до конца `wait`.

    Фильтры складываются по «и» и совпадают с фильтрами потока. `after` и `cursor` — не
    дубль: первый задаёт клиент, второй продолжает страницу; действуют оба, побеждает
    больший.
    """
    page = await service.wait_journal(
        session,
        actor=actor,
        journal_filter=await service.resolve_filter(
            session, task=task, project=project, types=types
        ),
        after=after,
        cursor=cursor,
        limit=limit,
        wait=wait,
        client_gone=request.is_disconnected,
    )
    return CollectionResponse[EntryRead].of(
        [
            entry_read(item.entry, task_key=item.task_key, project_key=item.project_key)
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/stream",
    summary="Stream the journal as it grows",
    # Базовый `Response`, а не `JournalStreamResponse` и не значение по умолчанию.
    # FastAPI берёт тип содержимого из `response_class.media_type` и подставляет его и в
    # успешный ответ, и в ошибки. У `JSONResponse` (значение по умолчанию) это давало бы
    # `200` с пустой схемой `application/json` рядом с объявленным вручную
    # `text/event-stream` — то есть маршрут, который генератор клиента видит как
    # возвращающий `unknown`. У `JournalStreamResponse` тем же способом ломались бы
    # ошибки. У базового `Response` тип содержимого — `None`: FastAPI не добавляет ничего
    # к `200`, а ошибкам подставляет `application/json`. Экземпляр этого класса при этом
    # не создаётся никогда: обработчик возвращает готовый `JournalStreamResponse`.
    response_class=Response,
    responses={
        200: {
            "description": (
                "An endless `text/event-stream`. Every frame carries the entry `seq` in "
                "`id:`, the entry type in `event:` and the entry itself in `data:`. Lines "
                "starting with `:` are heartbeats and carry no data"
            ),
            "content": {"text/event-stream": {"schema": entry_read_schema()}},
        },
        # `model` обязателен и здесь, хотя те же коды объявлены на роутере: ответы
        # маршрута не дополняют ответы роутера, а замещают их по коду целиком. Уточнив
        # одно описание, легко отобрать у ответа схему тела — и фронтенд увидит `422`
        # без формы ошибки ровно у того маршрута, где её проще всего получить.
        422: {"model": ErrorResponse, "description": "Malformed `Last-Event-ID`"},
        429: {"model": ErrorResponse, "description": "Too many open streams on this server"},
    },
)
async def stream_journal(
    session: SessionDep,
    sessions: StreamSessionsDep,
    actor: ActorDep,
    task: TaskQuery = None,
    project: ProjectQuery = None,
    types: TypesQuery = None,
    after: AfterQuery | None = None,
    last_event_id_header: LastEventIdHeader = None,
    last_event_id: LastEventIdQuery = None,
) -> JournalStreamResponse:
    """Тот же хвост журнала, что отдаёт лента, но потоком по мере появления записей.

    Фильтры те же, что у `GET /api/v1/journal`, и складываются так же. Кадр несёт `seq`
    записи в `id:`, тип записи в `event:` и саму запись в `data:` — той же формы, что и
    элемент ленты.

    Начало выдачи: без курсора — конец журнала, то есть «что будет дальше». С курсором
    (`Last-Event-ID`, параметр `last_event_id` или `after`) — сразу после названного
    номера. Слишком старого курсора не бывает: записи постоянны, и поток, оборванный на
    кадре `id: 17`, переоткрытый с `Last-Event-ID: 17`, продолжает с 18 без пропусков и
    повторов. Отказ здесь один — `Last-Event-ID`, который не разбирается как
    неотрицательное целое: молчаливый старт с конца заставил бы клиента считать, что за
    время обрыва ничего не произошло.

    Число одновременно открытых потоков на процесс ограничено настройкой; сверх неё —
    `429`, который клиент повторяет через паузу.
    """
    journal_filter = await service.resolve_filter(session, task=task, project=project, types=types)
    # Проверки, способные отказать, идут **до** начала потока: разбор курсора, права и
    # место в лимите соединений. Отказ после первого отданного байта клиент увидел бы
    # как оборванный поток без объяснения — по коду ответа `200` уже не сказать «нельзя».
    cursor = parse_last_event_id(last_event_id_header or last_event_id)
    if cursor is None:
        cursor = after
    start = await service.stream_start(session, actor=actor, last_event_id=cursor)
    service.slots.acquire(limit=service.connection_limit())

    async def frames() -> AsyncIterator[str]:
        try:
            yield f"retry: {RECONNECT_DELAY_MS}\n\n"
            async for message in service.stream_journal(
                sessions,
                journal_filter=journal_filter,
                after=start,
            ):
                yield render(message)
        finally:
            # `finally` в генераторе срабатывает на любом способе завершить чтение:
            # отключении клиента, остановке сервера, исключении. Без него место
            # оставалось бы занятым до перезапуска процесса.
            service.slots.release()
            logger.debug("Journal stream for %s closed", actor.author.signature)

    return JournalStreamResponse(
        frames(),
        headers={
            # Буферизация обратного прокси накапливает кадры и отдаёт их пачкой, то есть
            # превращает живой поток в опрос с непредсказуемой задержкой. Заголовок
            # понимает nginx; для остальных ту же роль играет `Cache-Control`.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
