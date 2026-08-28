"""Шина событий: реестр подписчиков и рассылка одного события.

Подписчик — асинхронная функция `(session, envelope) -> None`. Она получает сессию,
потому что почти каждому подписчику нужно писать в базу: движок уведомлений складывает
записи в инбокс, вебхуки — задание на доставку, автоматика — журнал срабатываний.

## Зачем реестр, а не список вызовов в воркере

Следующие задачи (13 автоматика, 14 уведомления, 15 вебхуки и SSE) должны подписаться
на события, не трогая ядро. Со списком вызовов внутри воркера каждая из них правила бы
один и тот же файл, и порядок обработчиков зависел бы от того, кто редактировал его
последним. С реестром задача добавляет свой модуль и одну строку в `SUBSCRIBER_MODULES`.

## Изоляция подписчиков держится на SAVEPOINT

Каждый обработчик выполняется внутри `session.begin_nested()`. Причина не в
аккуратности, а в устройстве SQLAlchemy: подписчик, успевший что-то записать и
упавший, оставляет транзакцию в состоянии, где любой следующий запрос падает до самого
отката. Без вложенной транзакции падение вебхука уносило бы с собой и работу
автоматики, и отметку об обработке события — то есть ровно то, что запрещено.

Ловится `Exception`, а не `BaseException`, и это тоже намеренно: `CancelledError`
наследуется от `BaseException`, и её перехват означал бы воркер, который не
останавливается по сигналу.
"""

import importlib
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("events")

#: Потолок текста ошибки в `outbox_events.last_error`. Сообщение исключения бывает
#: длиной в весь SQL-запрос с параметрами, а колонке нужна причина, а не дамп.
MAX_ERROR_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Событие в том виде, в каком его получает подписчик.

    Самодостаточно: `payload` содержит состояние объекта после изменения и список
    «было → стало». Ходить за контекстом в базу подписчику не нужно и вредно — пока
    событие лежало в очереди, объект успел измениться дальше, и база отдаст не то
    состояние, о котором событие.

    `event_type` — строка, а не `EventType`, сознательно. Значения берутся из словаря
    `app/domain/events.py` и сравниваются с его членами напрямую (`StrEnum` равен своей
    строке), но приведение к перечислению на входе означало бы, что событие с
    неизвестным типом роняет воркер вместо того, чтобы честно пометиться недоставленным.
    """

    id: uuid.UUID
    event_type: str
    object_type: str
    object_id: uuid.UUID
    object_key: str
    actor_key: str
    payload: dict[str, Any]
    created_at: datetime


type EventHandler = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Subscriber:
    """Подписчик: имя, обработчик и типы событий, которые ему интересны.

    Имя — не украшение: по нему в `outbox_events.delivered_to` отмечается, кто уже
    отработал. Менять имя существующего подписчика нельзя так же, как код ошибки:
    события, доставленные под старым именем, при повторе достанутся ему второй раз.
    """

    name: str
    handler: EventHandler
    #: `None` означает «все типы»: так подписываются SSE и вебхуки, которым нужен весь
    #: поток, а не отдельные события.
    event_types: frozenset[str] | None = None

    def wants(self, event_type: str) -> bool:
        return self.event_types is None or event_type in self.event_types


class SubscriberRegistry:
    """Реестр подписчиков. Порядок вызова — порядок регистрации.

    Порядок стабилен, но полагаться на него подписчику нельзя: он не должен ждать, что
    другой обработчик уже отработал. Изоляция вложенными транзакциями означает, что
    соседний подписчик мог и упасть, откатив свою запись.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, Subscriber] = {}

    def register(
        self,
        handler: EventHandler,
        *,
        name: str,
        events: Iterable[str] | None = None,
    ) -> Subscriber:
        """Регистрирует обработчик. Повтор имени — ошибка, а не молчаливая замена.

        Молчаливая замена — худший из возможных исходов: подписчик исчезает из
        обработки, всё продолжает работать, и обнаруживается это как «уведомления
        перестали приходить» через неделю после того, как две задачи выбрали одно имя.
        """
        if name in self._subscribers:
            raise ValueError(f"Event subscriber {name!r} is already registered")
        subscriber = Subscriber(
            name=name,
            handler=handler,
            event_types=None if events is None else frozenset(events),
        )
        self._subscribers[name] = subscriber
        return subscriber

    def subscribe(
        self,
        *events: str,
        name: str | None = None,
    ) -> Callable[[EventHandler], EventHandler]:
        """Декоратор подписки. Без аргументов — подписка на все типы событий.

        @subscribe(EventType.ISSUE_ASSIGNED, name="notifications")
        async def notify(session, event): ...
        """

        def decorator(handler: EventHandler) -> EventHandler:
            self.register(handler, name=name or handler.__name__, events=events or None)
            return handler

        return decorator

    def matching(self, event_type: str) -> tuple[Subscriber, ...]:
        """Подписчики, которым интересен этот тип события."""
        return tuple(item for item in self._subscribers.values() if item.wants(event_type))

    def names(self) -> tuple[str, ...]:
        return tuple(self._subscribers)

    def clear(self) -> None:
        """Опустошает реестр. Нужен тестам: реестр глобальный, а тесты — независимые."""
        self._subscribers.clear()


#: Реестр приложения. Подписчики регистрируются при импорте своего модуля.
registry = SubscriberRegistry()
subscribe = registry.subscribe


#: Модули, объявляющие подписчиков. Воркер импортирует их перед стартом — иначе
#: декораторы не выполнятся и реестр останется пустым. Задачи 13, 14 и 15 дописывают
#: сюда свои модули; трогать воркер при этом не нужно.
SUBSCRIBER_MODULES: tuple[str, ...] = (
    "app.services.event_log",
    "app.automation.subscriber",
    "app.services.notification_subscriber",
)


def load_subscribers() -> tuple[str, ...]:
    """Импортирует модули подписчиков и возвращает имена зарегистрированных.

    Импорт идемпотентен (модуль исполняется один раз), но повторная регистрация — нет,
    поэтому подписчики объявляются на уровне модуля, а не внутри функции.
    """
    for module in SUBSCRIBER_MODULES:
        importlib.import_module(module)
    return registry.names()


@dataclass(frozen=True, slots=True)
class SubscriberFailure:
    """Упавший подписчик: имя и причина. Имя важнее текста — по нему понятно, кто виноват."""

    name: str
    error: str


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Итог рассылки одного события: кто отработал и кто упал."""

    delivered: tuple[str, ...] = ()
    failures: tuple[SubscriberFailure, ...] = field(default=())

    @property
    def failed(self) -> bool:
        return bool(self.failures)


async def deliver(
    session: AsyncSession,
    envelope: EventEnvelope,
    subscribers: Iterable[Subscriber],
) -> DeliveryOutcome:
    """Раздаёт событие подписчикам. Падение одного не мешает остальным.

    Каждый обработчик идёт внутри вложенной транзакции: его запись либо фиксируется
    целиком, либо откатывается целиком, не задевая ни соседей, ни отметку об обработке
    события. Исключение не пробрасывается — оно становится строкой в итоге доставки,
    из которой сценарий решает, повторять событие или пометить недоставленным.
    """
    delivered: list[str] = []
    failures: list[SubscriberFailure] = []

    for subscriber in subscribers:
        try:
            async with session.begin_nested():
                await subscriber.handler(session, envelope)
        except Exception as exc:
            logger.exception(
                "Event subscriber %s failed on %s %s",
                subscriber.name,
                envelope.event_type,
                envelope.object_key,
            )
            failures.append(
                SubscriberFailure(
                    name=subscriber.name,
                    error=f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
                )
            )
        else:
            delivered.append(subscriber.name)

    return DeliveryOutcome(delivered=tuple(delivered), failures=tuple(failures))
