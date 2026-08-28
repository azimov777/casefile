"""Пробуждение ожидающих инбокс: оповещение PostgreSQL плюс внутрипроцессный хаб.

Задача одна: вызов «жди новых уведомлений» должен возвращать управление **сразу**, как
только уведомление появилось, а не через секунду-другую опроса. Опрос базы в цикле —
именно то, чего задача 14 просит не делать: десяток ждущих агентов превратились бы в
десяток запросов каждые сто миллисекунд.

## Почему одного механизма мало

Уведомление рождается в **воркере событий** — это отдельный сервис Compose, другой
процесс и другая транзакция. Ждёт его API или MCP-сервер. Между двумя процессами
`asyncio.Event` ничего не передаст, поэтому основной канал — `LISTEN/NOTIFY`
PostgreSQL: `pg_notify` выполняется в транзакции воркера и доставляется слушателям при
её фиксации, то есть ровно тогда, когда уведомление стало видимым.

Внутрипроцессный хаб при этом нужен и не является дублем. Он покрывает два случая, где
`NOTIFY` бесполезен: уведомление, созданное в том же процессе (макрос автоматики,
запущенный HTTP-запросом), и тесты, где транзакция откатывается и оповещение до
слушателя не доходит вовсе.

Третий уровень — редкий контрольный опрос в самом сценарии ожидания
(`notification_wait_poll_interval`). Он страхует от потерянного оповещения: соединение
слушателя могло оборваться между двумя ожиданиями, и без страховки вызов молча ждал бы
до таймаута при полном инбоксе.

## Слушатель поднимается процессом, а не первым ожиданием

`start()` зовётся из жизненного цикла приложения. Ленивый подъём «при первом ожидании»
выглядел бы удобнее и оставлял бы за собой соединение, которое некому закрыть: в
тестах, в разовых скриптах и в командах CLI ожидание может случиться один раз, а
соединение переживёт весь процесс. Без слушателя ожидание не ломается — оно переходит
на контрольный опрос, и это видно в логе.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable

import asyncpg
from sqlalchemy import String, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import asyncpg_dsn

logger = get_logger("notifications.wakeup")

#: Канал оповещений PostgreSQL. Имя одно на установку; адресат едет в полезной
#: нагрузке оповещения — ключом актора. Канал на актора означал бы `LISTEN` на каждого
#: ждущего и переподписку при каждом ожидании, а число каналов в PostgreSQL не
#: бесплатно.
CHANNEL = "tracker_inbox"


class WakeupHub:
    """Кто сейчас ждёт уведомлений и чем их разбудить.

    Один экземпляр на процесс. Ждущих мало (это агенты, висящие на длинном запросе),
    поэтому словарь множеств здесь дешевле любой очереди.
    """

    def __init__(self, channel: str = CHANNEL) -> None:
        self._channel = channel
        self._waiters: dict[str, set[asyncio.Event]] = {}
        self._connection: asyncpg.Connection | None = None

    async def start(self) -> None:
        """Подключается к базе и подписывается на канал оповещений.

        Ошибку не пробрасывает: контур поднимается до применения миграций, база может
        быть недоступна первые секунды, и ронять из-за этого API нельзя. Молчать тоже
        нельзя — без слушателя ожидание работает опросом, и это надо видеть в логе, а
        не выяснять по «уведомления приходят с задержкой».
        """
        if self._connection is not None:
            return
        try:
            connection = await asyncpg.connect(asyncpg_dsn())
            await connection.add_listener(self._channel, self._on_notify)
        except Exception:
            logger.exception(
                "Inbox wakeup listener is not connected; waits fall back to polling",
            )
            return
        # Обрыв соединения обязан обнулять ссылку: иначе следующий `start` увидит
        # «уже подключено» и оставит процесс без оповещений навсегда.
        connection.add_termination_listener(self._on_termination)
        self._connection = connection
        logger.info("Inbox wakeup listener connected to channel %s", self._channel)

    async def close(self) -> None:
        """Закрывает соединение слушателя. Идемпотентна."""
        connection, self._connection = self._connection, None
        if connection is None:
            return
        with contextlib.suppress(Exception):
            await connection.remove_listener(self._channel, self._on_notify)
        with contextlib.suppress(Exception):
            await connection.close()

    @property
    def is_listening(self) -> bool:
        """Подключён ли слушатель. Нужно сценарию ожидания только для строки в логе."""
        return self._connection is not None

    def wake(self, actor_keys: Iterable[str]) -> None:
        """Будит всех, кто ждёт уведомлений для этих акторов, внутри этого процесса."""
        for key in actor_keys:
            for event in self._waiters.get(key, ()):
                event.set()

    @contextlib.asynccontextmanager
    async def waiting_for(self, actor_key: str) -> AsyncIterator[asyncio.Event]:
        """Регистрирует ожидающего и снимает регистрацию на выходе.

        Регистрироваться надо **до** первой проверки инбокса, иначе уведомление,
        появившееся между проверкой и подпиской, никого не разбудит, и вызов прождёт
        до таймаута при непустом инбоксе. Контекстный менеджер существует ровно затем,
        чтобы этот порядок нельзя было нарушить случайно.
        """
        event = asyncio.Event()
        self._waiters.setdefault(actor_key, set()).add(event)
        try:
            yield event
        finally:
            waiters = self._waiters.get(actor_key)
            if waiters is not None:
                waiters.discard(event)
                if not waiters:
                    del self._waiters[actor_key]

    def _on_notify(
        self,
        connection: object,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Колбэк asyncpg: в нагрузке лежит ключ актора, которому что-то пришло."""
        if payload:
            self.wake([payload])

    def _on_termination(self, connection: object) -> None:
        logger.warning("Inbox wakeup listener lost its connection; waits fall back to polling")
        self._connection = None


#: Хаб процесса. Слушатель поднимается жизненным циклом приложения (`app/main.py`);
#: без него ожидание работает контрольным опросом.
hub = WakeupHub()


async def notify(session: AsyncSession, actor_keys: Iterable[str]) -> None:
    """Оповещает о новых уведомлениях для этих акторов.

    Два действия за один вызов, и оба обязательны. `pg_notify` уходит **в текущей
    транзакции** — PostgreSQL доставит его слушателям при фиксации, то есть ровно
    тогда, когда уведомление стало видимым для чтения. Откат транзакции отменяет и
    оповещение: разбуженный ждущий не увидел бы в инбоксе ничего.

    Локальное пробуждение, наоборот, происходит немедленно и до фиксации. Ложное
    срабатывание здесь безопасно: ожидание проверяет инбокс запросом и, ничего не
    найдя, возвращается ждать дальше.
    """
    keys = sorted({key for key in actor_keys if key})
    if not keys:
        return
    # Одним запросом на всю пачку: событие с десятком адресатов не должно стоить
    # десяти обращений к базе. `unnest` в списке выборки разворачивает массив ключей в
    # строки, и `pg_notify` вызывается по разу на каждую.
    statement = select(
        func.pg_notify(CHANNEL, func.unnest(bindparam("keys", type_=ARRAY(String))))
    ).params(keys=keys)
    await session.execute(statement)
    hub.wake(keys)
