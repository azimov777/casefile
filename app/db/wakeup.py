"""Пробуждение читателей журнала: `LISTEN/NOTIFY` PostgreSQL.

Задача одна: вызов, который ждёт новых записей — долгое ожидание ленты или открытый
поток SSE, — обязан вернуть управление **сразу**, как только запись появилась, а не
через секунду-другую опроса. Опрос базы в цикле — именно то, чего задача 26 просит не
делать: десяток ждущих агентов превратился бы в десяток запросов каждые сто
миллисекунд.

## Сигнал не может прийти раньше строки

`pg_notify` выполняется **внутри** транзакции подшивки (`app/services/case.py`,
`_append`), а PostgreSQL доставляет такие оповещения слушателям **при фиксации** — и
не доставляет вовсе, если транзакция откатилась. Отсюда свойство, ради которого всё
это и устроено так: разбуженный читатель, сходив в базу, обязательно видит строку, о
которой его разбудили.

Внутрипроцессного хаба пробуждения, который был в старом коде (git `49e2e49`,
`WakeupHub.wake`), здесь нет намеренно. Он будил ждущих **до** коммита, то есть давал
ровно тот сигнал раньше строки, который задача запрещает. Ложное срабатывание само по
себе безопасно (читатель ничего не найдёт и уснёт снова), но отличить его от настоящего
нельзя, а значит нельзя и проверить тестом, что сигналов раньше строк не бывает.
Оповещение поэтому одно и идёт через базу — в том числе когда писатель и читатель живут
в одном процессе: соединение слушателя отдельное, и оповещение возвращается по нему.

## Слушатель поднимается процессом, а не первым ожиданием

`start()` зовётся из жизненного цикла приложения (`app/main.py`). Ленивый подъём «при
первом ожидании» выглядел бы удобнее и оставлял бы за собой соединение, которое некому
закрыть: в тестах, в разовых скриптах и в командах CLI ожидание может случиться один
раз, а соединение переживёт весь процесс.

Без слушателя ожидание не ломается — оно переходит на контрольный опрос
(`journal_wait_poll_interval`), и это видно в логе. Молчать об этом нельзя: «лента
отдаёт записи с задержкой в пять секунд» иначе объяснить нечем.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import asyncpg
from sqlalchemy import bindparam, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import asyncpg_dsn

logger = get_logger("wakeup")

#: Канал оповещений PostgreSQL. Один на установку и широковещательный: у каждого
#: читателя ленты свой фильтр и свой курсор, и решить за него, интересна ли ему запись,
#: можно только прочитав эту запись. Канал на задачу или на очередь означал бы `LISTEN`
#: на каждого ждущего и переподписку при каждом ожидании, а число каналов в PostgreSQL
#: не бесплатно.
JOURNAL_CHANNEL = "tracker_journal"


class JournalWakeup:
    """Кто сейчас ждёт записей журнала и чем их разбудить.

    Один экземпляр на процесс. Ждущих мало (это агенты на длинном запросе и открытые
    потоки SSE), поэтому множество событий здесь дешевле любой очереди.
    """

    def __init__(self, channel: str = JOURNAL_CHANNEL) -> None:
        self._channel = channel
        self._waiters: set[asyncio.Event] = set()
        self._connection: asyncpg.Connection | None = None

    async def start(self, dsn: str | None = None) -> None:
        """Подключается к базе и подписывается на канал оповещений.

        Адрес по умолчанию — основная база установки. Параметр нужен тому, кто слушает
        не её: тесты идут на отдельной базе, и слушатель основной не услышал бы в них
        ничего — то же самое умеют `create_engine` и `asyncpg_dsn`.

        Ошибку не пробрасывает: контур поднимается до применения миграций, база может
        быть недоступна первые секунды, и ронять из-за этого API нельзя. Молчать тоже
        нельзя — без слушателя ожидание работает опросом.
        """
        if self._connection is not None:
            return
        try:
            connection = await asyncpg.connect(asyncpg_dsn(dsn))
            await connection.add_listener(self._channel, self._on_notify)
        except Exception:
            logger.exception(
                "Journal listener on %s is not connected; waits fall back to polling",
                self._channel,
            )
            return
        # Обрыв соединения обязан обнулять ссылку: иначе следующий `start` увидит
        # «уже подключено» и оставит процесс без оповещений навсегда.
        connection.add_termination_listener(self._on_termination)
        self._connection = connection
        logger.info("Journal listener connected to channel %s", self._channel)

    async def close(self) -> None:
        """Закрывает соединение слушателя. Идемпотентна.

        Колбэк завершения снимается **до** закрытия, а не подавляется флагом на время
        закрытия: `_call_termination_listeners` кладёт его в очередь `loop.call_soon`
        и возвращает управление — сам колбэк срабатывает на следующем обороте цикла
        событий, уже после того, как этот метод вернулся. Флаг, взведённый на время
        `await connection.close()` и снятый сразу после, снимался бы раньше, чем
        колбэк успевает проверить его, и WARNING всё равно звучал бы на штатной
        остановке. Снятая же подписка не сработает вовсе — не важно, на каком обороте.
        """
        connection, self._connection = self._connection, None
        if connection is None:
            return
        connection.remove_termination_listener(self._on_termination)
        with contextlib.suppress(Exception):
            await connection.remove_listener(self._channel, self._on_notify)
        with contextlib.suppress(Exception):
            await connection.close()

    @property
    def is_listening(self) -> bool:
        """Подключён ли слушатель. Нужно сценарию ожидания только для строки в логе."""
        return self._connection is not None

    @contextlib.asynccontextmanager
    async def waiting(self) -> AsyncIterator[asyncio.Event]:
        """Регистрирует ждущего и снимает регистрацию на выходе.

        Регистрироваться надо **до** первого чтения ленты, иначе запись, появившаяся
        между чтением и подпиской, никого не разбудит, и вызов прождёт до таймаута при
        непустом хвосте. Контекстный менеджер существует ровно затем, чтобы этот
        порядок нельзя было нарушить случайно.
        """
        event = asyncio.Event()
        self._waiters.add(event)
        try:
            yield event
        finally:
            self._waiters.discard(event)

    async def announce(self, session: AsyncSession, seq: int) -> None:
        """Оповещает о подшитой записи. Выполняется **внутри** транзакции подшивки.

        Это и есть «оповещение после фиксации»: PostgreSQL накапливает `pg_notify`
        транзакции и рассылает их слушателям в момент коммита, а при откате не
        рассылает вовсе. Ждущий поэтому не может проснуться раньше, чем строка стала
        видимой, — и не проснётся вхолостую на откатившейся подшивке.

        Вызывать после `flush`: номер записи выдаёт база, и до вставки его нет.
        """
        statement = select(func.pg_notify(self._channel, bindparam("payload"))).params(
            payload=str(seq)
        )
        await session.execute(statement)

    def wake_all(self) -> None:
        """Будит всех ждущих, не дожидаясь записи.

        Второй повод разбудить, кроме оповещения: сигнал остановки процесса
        (`app/core/shutdown.py`). Спящий проснётся, увидит взведённый признак и выйдет —
        иначе он заметил бы остановку только на следующем круге контрольного опроса, и
        она затянулась бы ровно на столько же.
        """
        for event in self._waiters:
            event.set()

    def _on_notify(
        self,
        connection: object,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Колбэк asyncpg: в нагрузке лежит `seq` подшитой записи.

        Номер в нагрузке не адресует ждущего и на отбор не влияет — будятся все, потому
        что фильтр у каждого свой. Он полезен в отладке и в тестах: по нему видно,
        какая именно запись разбудила процесс.
        """
        self.wake_all()

    def _on_termination(self, connection: object) -> None:
        # `close()` снимает эту подписку до закрытия — значит, добравшийся сюда вызов
        # обязан быть настоящим обрывом, а не штатной остановкой (TRK-126).
        logger.warning(
            "Journal listener on %s lost its connection; waits fall back to polling",
            self._channel,
        )
        self._connection = None


#: Слушатель процесса. Поднимается жизненным циклом приложения (`app/main.py`); без него
#: ожидание работает контрольным опросом.
journal_wakeup = JournalWakeup()
