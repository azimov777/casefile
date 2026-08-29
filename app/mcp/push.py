"""MCP-нотификации: сигнал «в инбоксе что-то появилось».

## Это не второй канал уведомлений, а показ того же инбокса

Наружу уходит **только сигнал**: событие `resources/updated` по адресу
`tracker://inbox/<ключ актора>`. Ни текста, ни идентификаторов в нём нет — получив его,
агент читает ленту обычным `list_notifications` и отмечает разобранное
`mark_notifications_read`. Отсюда главное свойство: отметка о прочтении одна на оба
способа, и агент, разобравший ленту инструментом, не получит её повторно нотификацией.

Клиенты, которые подписок не поддерживают, ничего не теряют: инбокс и ожидание
(`wait_for_notifications`) — основной канал, а это дополнение поверх.

## Оповещение приходит тем же механизмом, что и ожидание

Уведомление рождается в **воркере событий** — другом процессе и другой транзакции, —
поэтому единственный способ узнать о нём вовремя это `LISTEN/NOTIFY` PostgreSQL. Слушает
канал уже существующий `WakeupHub` (`app/db/wakeup.py`), и сервер подключается к нему
наблюдателем (`observing`). Заводить ради нотификаций второе соединение и второй
слушатель было бы ошибкой: процесс держал бы две несовместимые механики пробуждения, и
починка одной не чинила бы вторую.

## Публикация идёт задачей, а не прямо в колбэке

Колбэк хаба синхронный: его зовёт обработчик оповещения asyncpg, и ждать в нём отправки
нельзя. Поэтому публикация ставится задачей, а ссылки на задачи держатся до их
завершения — иначе сборщик мусора вправе убрать задачу вместе с неотправленным сигналом.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable

from mcp.server.subscriptions import SubscriptionBus
from mcp.shared.subscriptions import ResourceUpdated

from app.core.logging import get_logger
from app.db.wakeup import WakeupHub
from app.db.wakeup import hub as inbox_hub

logger = get_logger("mcp.push")


def inbox_uri(actor_key: str) -> str:
    """Адрес ресурса-инбокса актора. Он же — то, на что подписывается клиент."""
    return f"tracker://inbox/{actor_key}"


class InboxPush:
    """Мост между оповещениями инбокса и подписками MCP.

    Один экземпляр на процесс, живёт весь жизненный цикл сервера.
    """

    def __init__(self, bus: SubscriptionBus, *, hub: WakeupHub | None = None) -> None:
        self._bus = bus
        self._hub = hub or inbox_hub
        self._tasks: set[asyncio.Task[None]] = set()

    @contextlib.asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Подключает наблюдателя на время работы сервера.

        Слушатель канала поднимается здесь же, а не первым уведомлением: ленивый подъём
        оставил бы за собой соединение, которое некому закрыть. Не подключился — в логе
        строка, а инбокс и ожидание продолжают работать: они и есть основной канал.
        """
        await self._hub.start()
        if not self._hub.is_listening:
            logger.warning(
                "Inbox listener is not connected; MCP notifications are not delivered, "
                "the inbox tools still work"
            )
        with self._hub.observing(self._on_wake):
            try:
                yield
            finally:
                await self._drain()
                await self._hub.close()

    def _on_wake(self, actor_keys: Iterable[str]) -> None:
        """Колбэк хаба: у этих акторов в инбоксе что-то появилось."""
        for key in actor_keys:
            task = asyncio.create_task(self._publish(key))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _publish(self, actor_key: str) -> None:
        """Отправляет сигнал подписанным потокам. Ошибка шины не должна ронять процесс."""
        try:
            await self._bus.publish(ResourceUpdated(uri=inbox_uri(actor_key)))
        except Exception:
            logger.exception("MCP inbox notification for %s is not published", actor_key)

    async def _drain(self) -> None:
        """Дожидается незавершённых публикаций при остановке сервера."""
        pending = list(self._tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
