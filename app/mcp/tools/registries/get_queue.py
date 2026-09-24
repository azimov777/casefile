"""Инструмент `get_queue`: очередь с описанием — общим контекстом её задач."""

from pydantic import BaseModel, Field

from app.db.models.queue import Queue
from app.mcp.arguments import QueueKeyArg
from app.mcp.toolset import READ_ONLY, Toolset
from app.services import queues as queues_service


class QueueView(BaseModel):
    """Queue with its description."""

    key: str
    title: str
    description: str = Field(
        description=(
            "Shared context of all tasks of the queue: where the code lives, which "
            "documents apply, what is out of bounds. Task cards carry only the queue's "
            "key and title"
        )
    )


def queue(item: Queue) -> QueueView:
    """Очередь с описанием — общим контекстом всех её задач.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом.
    """
    return QueueView(key=item.key, title=item.title, description=item.description)


def register(tools: Toolset) -> None:
    """Объявляет `get_queue` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=READ_ONLY)
    async def get_queue(key: QueueKeyArg) -> QueueView:
        """Returns one queue by its key: key, title and description.

        The keys of the installation's queues are listed by `list_queues`.
        """
        async with runtime.call() as (session, actor):
            return queue(await queues_service.read_queue(session, key, actor=actor))
