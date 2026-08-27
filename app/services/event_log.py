"""Подписчик, пишущий каждое событие в лог. Единственный встроенный в проект.

Зачем он нужен. Во-первых, это работающий пример подписки для задач 13, 14 и 15: видно,
как объявляется обработчик и как он попадает в реестр. Во-вторых, без него воркер
молчалив — при пустом реестре подписчиков понять, что события вообще обрабатываются,
можно было бы только запросом в базу.

Подписка на все типы событий: ловить надо любое, а не перечислять словарь заново.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.event_bus import EventEnvelope, subscribe

logger = get_logger("events.log")


@subscribe(name="event_log")
async def log_event(session: AsyncSession, event: EventEnvelope) -> None:
    """Пишет строку в лог. Сессия не нужна, но входит в контракт подписчика.

    Изменённые поля попадают в строку, а полезная нагрузка целиком — нет: в ней лежит
    снимок задачи, и лог превратился бы в дамп базы.
    """
    logger.info(
        "%s %s by %s (fields: %s)",
        event.event_type,
        event.object_key,
        event.actor_key,
        ", ".join(event.payload.get("fields", [])) or "-",
    )
