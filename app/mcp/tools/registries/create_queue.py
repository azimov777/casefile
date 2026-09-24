"""Инструмент `create_queue`: новая очередь, только набором `main`."""

from typing import Annotated

from pydantic import Field

from app.domain.tokens import TokenScope
from app.mcp.arguments import IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.views import QueueKeyView, queue_key
from app.mcp.toolset import FILING, Toolset
from app.services import queues as queues_service

NewQueueKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the new queue: a Latin letter followed by 1–15 Latin letters or digits "
            "(`invalid_queue_key` otherwise). It is stored upper-case, never changes and "
            "prefixes the key of every task of the queue. A key already taken, in any "
            "case, is refused with `queue_key_taken`"
        ),
        examples=["TRK"],
    ),
]

QueueTitleArg = Annotated[str, Field(description="Queue title")]


QueueDescriptionArg = Annotated[
    str,
    Field(description="Queue description in markdown: the shared context of all its tasks"),
]


def register(tools: Toolset) -> None:
    """Объявляет `create_queue` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def create_queue(
        key: NewQueueKeyArg,
        title: QueueTitleArg,
        description: QueueDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> QueueKeyView:
        """Creates a queue with a key, a title and a description. Only a `main` token
        creates queues.
        """
        async with runtime.call() as (session, actor):

            async def create() -> QueueKeyView:
                return queue_key(
                    await queues_service.create_queue(
                        session, actor=actor, key=key, title=title, description=description
                    )
                )

            return await Once.of(create_queue, session, actor, idempotency_key).run(
                result=QueueKeyView,
                request={"key": key, "title": title, "description": description},
                build=create,
            )
