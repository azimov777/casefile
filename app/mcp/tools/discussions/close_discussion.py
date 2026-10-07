"""Инструмент `close_discussion`: итог и закрытие обсуждения одной транзакцией."""

from pydantic import BaseModel, Field

from app.mcp.arguments import DiscussionAddressArg, IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.discussions.arguments import (
    ConclusionDecidedArg,
    ConclusionOpenArg,
    ConclusionSupersededArg,
)
from app.mcp.toolset import FILING, Toolset
from app.services import discussions as discussions_service
from app.services.discussions import DiscussionClosure


# Ответ закрытия: чем стало обсуждение и номера подшитых записей. Номерами, а не формой
# записи, как у `close_task`: обе записи — итог и `closed` — подшивает трекер по
# присланному, их адрес — адрес обсуждения и номер, а форма записи в схеме ответа стоила
# бы ещё ≈ 100 токенов в каждом подключении (замер — дело TRK-671).
class ClosedDiscussionView(BaseModel):
    """Closed discussion: address, new status and the entries the call filed."""

    discussion: str
    status: str = Field(description="`closed`")
    entries: list[int] = Field(description="Numbers of the conclusion and of `closed`")


def closed_discussion(closure: DiscussionClosure) -> ClosedDiscussionView:
    """Ответ закрытия: адрес, статус и номера записей — итог, затем `closed`."""
    return ClosedDiscussionView(
        discussion=closure.discussion.address,
        status=closure.discussion.status.value,
        entries=[item.no for item in closure.entries],
    )


def register(tools: Toolset) -> None:
    """Объявляет `close_discussion`."""
    runtime = tools.runtime

    @tools.tool(title="Close discussion", annotations=FILING, creating=True)
    async def close_discussion(
        key: DiscussionAddressArg,
        decided: ConclusionDecidedArg,
        superseded: ConclusionSupersededArg,
        open: ConclusionOpenArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> ClosedDiscussionView:
        """Closes a discussion: files the final conclusion and the service entry `closed`
        and moves it to `closed` atomically; no other call closes a discussion.

        A question with no answer refuses it with `discussion_has_open_questions`, the
        question addresses in `details.questions`; an empty conclusion part with
        `entry_fields_invalid`. A closed discussion never reopens: any entry, attaching
        or detaching answers `discussion_closed`, and a further question on the topic
        opens a new discussion that names this one in `refs`.

        Its attached tasks stay attached. While a discussion is open, closing or
        cancelling a task attached to it is refused with `task_has_open_discussions`.
        """
        async with runtime.call() as (session, actor):
            discussion = await discussions_service.get_discussion(session, key)

            async def close() -> ClosedDiscussionView:
                closure = await discussions_service.close_discussion(
                    session,
                    discussion,
                    actor=actor,
                    decided=decided,
                    superseded=superseded,
                    open=open,
                )
                return closed_discussion(closure)

            return await Once.of(close_discussion, session, actor, idempotency_key).run(
                result=ClosedDiscussionView,
                request={
                    "discussion": discussion.address,
                    "decided": decided,
                    "superseded": superseded,
                    "open": open,
                },
                build=close,
            )
