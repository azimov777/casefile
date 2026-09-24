"""Инструмент `update_queue`: название и описание очереди, только набором `main`."""

from typing import Annotated

from pydantic import Field

from app.domain.tokens import TokenScope
from app.mcp.arguments import QueueKeyArg
from app.mcp.tools.registries.views import QueueKeyView, queue_key
from app.mcp.toolset import OVERWRITING_UPDATE, Toolset
from app.services import queues as queues_service

# Отдельные аннотации для правки: `None` здесь означает «не передано». Осмысленного
# `null` ни у названия, ни у описания нет, поэтому третьего состояния и не нужно — в
# отличие от исполнителя задачи, который `null` как раз снимается.
QueueTitleChangeArg = Annotated[
    str | None, Field(description="New title; when left out, the title stays")
]

QueueDescriptionChangeArg = Annotated[
    str | None, Field(description="New description; when left out, the description stays")
]


def register(tools: Toolset) -> None:
    """Объявляет `update_queue` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=OVERWRITING_UPDATE, scope=TokenScope.MAIN)
    async def update_queue(
        key: QueueKeyArg,
        title: QueueTitleChangeArg = None,
        description: QueueDescriptionChangeArg = None,
    ) -> QueueKeyView:
        """Changes a queue's title and description; a field left out stays. Only a `main`
        token edits queues. The key never changes, and the previous title and
        description are not kept.
        """
        async with runtime.call() as (session, actor):
            queue = await queues_service.get_queue(session, key)
            return queue_key(
                await queues_service.update_queue(
                    session, queue, actor=actor, title=title, description=description
                )
            )
