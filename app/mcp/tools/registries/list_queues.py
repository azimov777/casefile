"""Инструмент `list_queues`: очереди установки строкой — ключ и название."""

from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, QueueRefView, page, queue_ref
from app.services import queues as queues_service


def register(tools: Toolset) -> None:
    """Объявляет `list_queues` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def list_queues(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[QueueRefView]:
        """Lists the installation's queues, one page at a time: key and title. A queue's
        description is returned by `get_queue`.
        """
        async with runtime.call() as (session, actor):
            listed = await queues_service.list_queues(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return page(
                (queue_ref(item) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
