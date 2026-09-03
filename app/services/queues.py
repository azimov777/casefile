"""Сценарии по очередям."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import QueueRepository
from app.domain.errors import QueueKeyTakenError, QueueNotFoundError
from app.domain.queues import normalize_queue_key, validate_queue_key
from app.domain.tokens import TokenScope
from app.services.auth import Actor
from app.services.permissions import ensure_scope


async def get_queue(session: AsyncSession, key: str) -> Queue:
    """Очередь по ключу или `queue_not_found`. Адресация мягкая: `trk` находит `TRK`."""
    queue = await QueueRepository(session).get_by_key(normalize_queue_key(key))
    if queue is None:
        raise QueueNotFoundError(details={"key": key})
    return queue


async def read_queue(session: AsyncSession, key: str, *, actor: Actor) -> Queue:
    """Карточка очереди с описанием — общим контекстом всех её задач."""
    ensure_scope(actor, TokenScope.TASK, action="queue.read")
    return await get_queue(session, key)


async def list_queues(
    session: AsyncSession,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Queue]:
    ensure_scope(actor, TokenScope.TASK, action="queue.list")
    return await QueueRepository(session).list_page(limit=limit, cursor=cursor)


async def create_queue(
    session: AsyncSession,
    *,
    actor: Actor,
    key: str,
    title: str,
    description: str = "",
) -> Queue:
    """Заводит очередь. Ключ канонизируется и дальше неизменяем."""
    ensure_scope(actor, TokenScope.MAIN, action="queue.create")

    canonical = validate_queue_key(key)
    repository = QueueRepository(session)
    if await repository.get_by_key(canonical) is not None:
        raise QueueKeyTakenError(details={"key": canonical})

    return await repository.add(
        Queue(
            key=canonical,
            title=title.strip(),
            description=description.strip(),
            **created_by_columns(actor.author),
        )
    )


async def update_queue(
    session: AsyncSession,
    queue: Queue,
    *,
    actor: Actor,
    title: str | None = None,
    description: str | None = None,
) -> Queue:
    """Меняет название и описание. Ключ не меняется никогда.

    Ключ вшит в ключ каждой задачи очереди (`TRK-42`), и его правка задним числом
    порвала бы все уже записанные ссылки. В API поля `key` у частичного обновления нет
    вовсе — схема отвергает его как лишнее, а не молча игнорирует.

    `None` означает «поле не передано»: ни у названия, ни у описания нет осмысленного
    значения `null`, поэтому схема `QueueUpdate` отвергает явный `null` сама.
    """
    ensure_scope(actor, TokenScope.MAIN, action="queue.update")

    if title is not None:
        queue.title = title.strip()
    if description is not None:
        queue.description = description.strip()
    await session.flush()
    return queue


async def next_task_number(session: AsyncSession, queue: Queue, *, actor: Actor) -> int:
    """Следующий номер задачи в очереди.

    Выдаётся атомарным `UPDATE ... RETURNING` (`QueueRepository.allocate_task_number`):
    два параллельных создания задачи получают разные номера, но платят за это
    сериализацией до конца транзакции. Поэтому номер берут **последним**, после всех
    проверок: откатившаяся транзакция свой номер теряет навсегда.

    Набор `task`, а не `main`: номер берут при создании задачи, то есть в рабочем цикле
    агента.
    """
    ensure_scope(actor, TokenScope.TASK, action="queue.allocate_task_number")
    return await QueueRepository(session).allocate_task_number(queue)
