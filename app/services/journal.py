"""Лента журнала: хвост по сквозному номеру, долгое ожидание, живой поток.

Источник у всех трёх один — таблица записей дела (`CONCEPT.md`, 4.1). Ни отдельной
таблицы событий, ни outbox, ни воркера, ни срока хранения: записи постоянны, поэтому
догнать ленту можно с любого номера, а «слишком старого» курсора не существует.

## Ожидание не опрашивает базу

Ждущий регистрируется у слушателя `LISTEN/NOTIFY` (`app/db/wakeup.py`) и спит, пока его
не разбудят. Оповещение уходит из транзакции подшивки и доставляется PostgreSQL при её
фиксации, поэтому разбуженный, сходив в базу, обязательно видит строку, из-за которой
проснулся. Контрольный опрос (`journal_wait_poll_interval`) — не основной механизм, а
страховка от оборванного соединения слушателя.

## Ожидание отпускает соединение на время сна

`session.commit()` перед каждой паузой обязателен. Вызов висит десятки секунд, и без
этого он держал бы соединение из пула с открытым снимком: пять ждущих агентов исчерпали
бы пул целиком, и остальной API встал бы. Терять при этом нечего — сценарий только
читает. Ждущий, который что-то пишет, так делать не может, и такого здесь нет.

## Ушедший клиент прекращает ожидание

Ждать ради того, кто уже отключился, незачем: соединение из пула и место в пуле задач
заняты, а ответ отдавать некому. Поэтому вызывающий передаёт способ узнать, что клиент
ушёл, и цикл проверяет его после каждой паузы — то есть бросает ожидание не позже, чем
через один контрольный опрос. Проверка приходит параметром, а не берётся из запроса:
сценарий один на REST и MCP, и про `Request` он знать не должен.

## Поток читает ту же ленту, что и запрос

Соединение SSE не получает записи откуда-то ещё: оно читает тот же хвост тем же
запросом, только в цикле и со своим курсором. Отсюда бесплатно получается
переподключение — клиент просто продолжает с номера, на котором оборвался.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.shutdown import shutdown
from app.db.pagination import Page, decode_sort_cursor
from app.db.repositories import EntryRepository
from app.db.wakeup import journal_wakeup
from app.domain.case import EntryType
from app.domain.errors import JournalStreamLimitError
from app.domain.journal import (
    JOURNAL_START,
    JournalFilter,
    resolve_after,
    resolve_types,
    resolve_wait,
)
from app.domain.tokens import TokenScope
from app.services import queues as queues_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.case import TaskEntry
from app.services.permissions import ensure_scope

logger = get_logger("journal")

#: Сколько записей поток забирает за один заход. Пачками, а не по одной: догоняющий
#: клиент, отставший на тысячу записей, иначе сделал бы тысячу запросов.
STREAM_BATCH_SIZE = 100

#: Пауза переподключения, которую поток советует клиенту (поле `retry` в SSE). Совет, а
#: не гарантия: браузер вправе её увеличить, но без неё он переподключается сразу и
#: заваливает упавший сервер запросами.
RECONNECT_DELAY_MS = 3000

#: Фабрика сессий: контекстный менеджер, открывающий и закрывающий транзакцию. Поток
#: получает её параметром, а не берёт импортом, чтобы было видно — сессия здесь живёт
#: короче самого потока, и чтобы тест мог подсунуть свою.
type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

#: Способ спросить, ушёл ли клиент. У HTTP это `Request.is_disconnected` — проверка без
#: ожидания: она смотрит, не пришло ли в канал `http.disconnect`, и не блокирует цикл.
type ClientGone = Callable[[], Awaitable[bool]]


# --- Фильтр ---------------------------------------------------------------------------


async def resolve_filter(
    session: AsyncSession,
    *,
    task: str | None = None,
    queue: str | None = None,
    types: Sequence[EntryType] | None = None,
) -> JournalFilter:
    """Превращает ключи из запроса в фильтр по идентификаторам.

    Ключи разрешаются через те же сценарии, что и везде, а не подставляются в условие
    как есть: опечатка в ключе иначе дала бы пустую ленту, неотличимую от «ничего не
    происходит», и ждущий висел бы до таймаута, считая установку спящей. Несуществующий
    ключ поэтому `task_not_found` или `queue_not_found`.
    """
    resolved_task = None if task is None else await tasks_service.get_task(session, task)
    resolved_queue = None if queue is None else await queues_service.get_queue(session, queue)
    return JournalFilter(
        task_id=resolved_task.id if resolved_task is not None else None,
        queue_id=resolved_queue.id if resolved_queue is not None else None,
        types=resolve_types(types),
    )


# --- Чтение ---------------------------------------------------------------------------


async def read_journal(
    session: AsyncSession,
    *,
    actor: Actor,
    journal_filter: JournalFilter,
    after: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[TaskEntry]:
    """Страница хвоста журнала: записи с номером больше `after`, по возрастанию `seq`.

    `after` и `cursor` — не дубль: первый задаёт клиент (это его курсор ленты, тот же
    номер, что уезжает в `id:` кадра потока), второй продолжает страницу и приезжает из
    `meta.next_cursor`. Действуют оба сразу, побеждает больший.
    """
    ensure_scope(actor, TokenScope.TASK, action="journal.read")
    cursor_seq = None
    if cursor is not None:
        (value,), _ = decode_sort_cursor(cursor, arity=1)
        cursor_seq = int(value)
    page = await EntryRepository(session).journal_page(
        after=resolve_after(after, cursor_seq),
        task_id=journal_filter.task_id,
        queue_id=journal_filter.queue_id,
        types=journal_filter.types,
        limit=limit,
    )
    return Page(
        items=[TaskEntry(entry=entry, task_key=key) for entry, key in page.items],
        next_cursor=page.next_cursor,
    )


async def wait_journal(
    session: AsyncSession,
    *,
    actor: Actor,
    journal_filter: JournalFilter,
    after: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    wait: float | None = None,
    client_gone: ClientGone | None = None,
) -> Page[TaskEntry]:
    """Тот же хвост, но с ожиданием: возвращается, как только появилась первая запись.

    Основа цикла назначателя и живого харнесса (`CONCEPT.md`, 4.6): «прочитать хвост,
    пересчитать кандидатов». Порядок шагов обязателен и держится контекстным
    менеджером:

    1. зарегистрироваться ждущим **до** первого чтения, иначе запись, появившаяся между
       чтением и подпиской, никого не разбудит, и вызов прождёт до таймаута при непустом
       хвосте;
    2. прочитать — возможно, ждать уже нечего;
    3. заснуть до оповещения или до контрольного опроса, что раньше.

    Пустой ответ по истечении ожидания — не ошибка и не отдельный код: «ничего не
    случилось» и есть пустая коллекция. Отличать её от сбоя незачем — сбой приходит
    ошибкой.

    `client_gone` прекращает ожидание досрочно, когда звавший отключился. Тем же пустым
    ответом, а не исключением: отдавать его уже некому, а исключение в этом месте
    означало бы ошибку в логах на каждый закрытый браузер.
    """
    ensure_scope(actor, TokenScope.TASK, action="journal.read")
    seconds = resolve_wait(wait)
    if seconds <= 0:
        return await read_journal(
            session,
            actor=actor,
            journal_filter=journal_filter,
            after=after,
            cursor=cursor,
            limit=limit,
        )

    settings = get_settings()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    if not journal_wakeup.is_listening:
        # Не предупредить нельзя: без слушателя ожидание работает контрольным опросом,
        # и «лента отдаёт записи с задержкой в пять секунд» иначе объяснить нечем.
        logger.debug("Journal wait runs without the PostgreSQL listener; polling instead")

    async with journal_wakeup.waiting() as woken:
        while True:
            # Флаг сбрасывается **до** выборки: запись, подшитая во время неё, оставит
            # его взведённым, и следующий круг не уйдёт спать, имея непрочитанное.
            woken.clear()
            page = await read_journal(
                session,
                actor=actor,
                journal_filter=journal_filter,
                after=after,
                cursor=cursor,
                limit=limit,
            )
            if page.items:
                return page

            remaining = deadline - loop.time()
            if remaining <= 0:
                return page

            # Соединение отпускается на время сна. `commit`, а не `rollback`: сценарий
            # ничего не менял, но откат в середине запроса выглядел бы как отмена
            # чего-то, чего не было.
            await session.commit()
            await _sleep_until_woken(woken, min(remaining, settings.journal_wait_poll_interval))
            if shutdown.started:
                # Процесс останавливается. Ждать дальше некому и незачем: пустой ответ —
                # законный исход ожидания, и звавший повторит вызов с тем же `after`.
                logger.debug("Journal wait stopped: the process is shutting down")
                return Page(items=[], next_cursor=None)
            # После паузы, а не до: пока цикл спал, клиент мог уйти, и следующий круг
            # начинался бы с выборки ради ответа, который никто не прочитает.
            if client_gone is not None and await client_gone():
                logger.debug("Journal wait stopped: the client is gone")
                return Page(items=[], next_cursor=None)


# --- Поток ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JournalMessage:
    """Одно сообщение потока: запись журнала или служебный тик.

    Тик нужен не для красоты. Он не даёт прокси закрыть простаивающее соединение и даёт
    серверу обнаружить ушедшего клиента: запись в закрытый сокет падает, и генератор
    завершается вместо того, чтобы висеть до перезапуска процесса.
    """

    item: TaskEntry | None = None
    comment: str | None = None

    @property
    def is_heartbeat(self) -> bool:
        return self.item is None


class StreamSlots:
    """Счётчик открытых потоков процесса.

    Живёт в сценариях, а не в HTTP-слое: потолок обязан действовать на любой интерфейс,
    который откроет поток. Счётчик, а не семафор — ждать освободившегося места не нужно,
    лишнему клиенту надо отказать сразу.
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
        объяснения), а освобождается в генераторе кадров, когда чтение закончилось.
        """
        if self._open >= limit:
            raise JournalStreamLimitError(details={"open": self._open, "limit": limit})
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


#: Счётчик процесса. Реплики API считают свои соединения независимо: потолок задан на
#: процесс, потому что ограничен пул соединений именно процесса.
slots = StreamSlots()


def connection_limit() -> int:
    """Потолок открытых потоков процесса. Отдельная функция, а не чтение по месту."""
    return get_settings().journal_stream_max_connections


async def stream_start(
    session: AsyncSession,
    *,
    actor: Actor,
    last_event_id: int | None,
) -> int:
    """Номер, после которого поток начинает выдачу.

    Без курсора — конец журнала: клиент просит «что будет дальше», а не историю
    установки. С курсором — ровно он, каким бы старым ни был: записи постоянны, и
    отставание потока ничем не ограничено. Окна переподключения, которое было у потока
    событий, здесь нет и заводить его незачем.
    """
    ensure_scope(actor, TokenScope.TASK, action="journal.stream")
    if last_event_id is not None:
        return last_event_id
    return await EntryRepository(session).latest_seq()


async def stream_journal(
    sessions: SessionFactory,
    *,
    journal_filter: JournalFilter,
    after: int,
) -> AsyncIterator[JournalMessage]:
    """Поток сообщений: записи по мере появления, между ними тики.

    Кончается двумя способами. Первый — его перестают читать: клиент отключился и
    потребитель генератора закрыл его. Второй — **сигнал остановки процесса**: поток
    выходит из цикла сам, и SSE-ответ завершается обычным концом, а не обрывом.

    Второй способ существует затем, что без него сервер не останавливается вовсе:
    uvicorn ждёт закрытия соединений, а бесконечный генератор не кончается никогда
    (`app/core/shutdown.py`, `docs/notes/docker.md`). Потерь при этом нет и клиенту
    ничего нового знать не надо: записи постоянны, `retry:` ему уже послан, и поток,
    переоткрытый с `Last-Event-ID`, продолжает ровно с того же места.

    Регистрация идёт **до** первой выборки по той же причине, что и в ожидании: запись,
    подшитая между выборкой и подпиской, иначе никого не разбудила бы, и поток простоял
    бы до контрольного опроса при непустом хвосте.
    """
    settings = get_settings()
    loop = asyncio.get_running_loop()
    last_sent = loop.time()

    async with journal_wakeup.waiting() as woken:
        while not shutdown.started:
            woken.clear()
            async with sessions() as session:
                page = await EntryRepository(session).journal_page(
                    after=after,
                    task_id=journal_filter.task_id,
                    queue_id=journal_filter.queue_id,
                    types=journal_filter.types,
                    limit=STREAM_BATCH_SIZE,
                )
            for entry, task_key in page.items:
                after = entry.seq
                yield JournalMessage(item=TaskEntry(entry=entry, task_key=task_key))
                last_sent = loop.time()

            if len(page.items) == STREAM_BATCH_SIZE:
                # Пачка забита целиком — хвост наверняка не разобран до конца, и
                # засыпать здесь значило бы отдавать догоняющие записи порциями раз в
                # несколько секунд.
                continue

            await _sleep_until_woken(woken, settings.journal_wait_poll_interval)
            if shutdown.started:
                # Сигнал пришёл, пока поток спал: выходим, не послав прощального кадра.
                # Своего кадра у конца потока нет намеренно — клиент переживает обрыв по
                # `Last-Event-ID`, и это проверено сквозными тестами интерфейса.
                logger.debug("Journal stream closing: the process is shutting down")
                break
            if loop.time() - last_sent >= settings.journal_stream_heartbeat_interval:
                last_sent = loop.time()
                yield JournalMessage(comment="ping")


async def _sleep_until_woken(woken: asyncio.Event, seconds: float) -> None:
    """Пауза, которую прерывает оповещение о новой записи или сигнал остановки.

    Таймаут здесь — контрольный опрос, а не основной механизм: он страхует от
    оборванного соединения слушателя, из-за которого ждущий иначе молчал бы при
    наполняющемся журнале.

    Отдельного ожидания сигнала остановки тут нет: подписка будит ждущих тем же
    механизмом, что и оповещение о записи (`app/db/wakeup.py`, `wake_all`). Спящий
    просыпается сразу, а разбираться, что именно его разбудило, — дело звавшего.
    """
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(woken.wait(), timeout=seconds)


__all__ = [
    "JOURNAL_START",
    "RECONNECT_DELAY_MS",
    "ClientGone",
    "JournalMessage",
    "SessionFactory",
    "connection_limit",
    "read_journal",
    "resolve_filter",
    "slots",
    "stream_journal",
    "stream_start",
    "wait_journal",
]
