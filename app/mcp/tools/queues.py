"""Инструменты очередей: что вообще есть и чем можно заполнять задачу.

Первое, что делает агент в незнакомой установке: смотрит список очередей и берёт
конфигурацию нужной. В конфигурации лежит всё, что нужно для создания задачи — типы,
статусы, резолюции, поля и графы процессов, — поэтому четырёх отдельных вызовов ради
одной формы здесь нет.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.core.config import get_settings
from app.db.pagination import MAX_PAGE_SIZE
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import queues as queues_service


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты очередей."""

    @server.tool()
    async def list_queues(
        is_archived: Annotated[
            bool | None,
            Field(description="Filter by the archived flag; omit to get both"),
        ] = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List the queues of this installation.

        A queue owns its process: its own issue types, statuses, resolutions and
        workflows. Archived queues keep everything but accept no new issues.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            page = await queues_service.list_queues(
                session,
                initiator=actor,
                is_archived=is_archived,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (views.queue(item) for item in page.items), next_cursor=page.next_cursor
            )

    @server.tool()
    async def get_queue_config(
        queue: Annotated[str, Field(description="Queue key, for example `TRK`")],
    ) -> dict[str, Any]:
        """Read everything an issue in this queue can be filled with.

        Issue types, statuses, resolutions, custom fields and the workflow graphs in
        one call. Only active entries are listed: the answer is «what can be used now»,
        not «what was ever created».

        Read this before creating an issue in a queue you do not know: it names the
        required custom fields, the allowed statuses and the default type.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.queue(session, queue)
            config = await queues_service.get_queue_config(session, entry, initiator=actor)
            return views.queue_config(config)
