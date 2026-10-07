"""Инструмент `add_conclusion`: итог обсуждения — решено, заменено, открыто — без закрытия."""

from app.mcp.arguments import DiscussionAddressArg, IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.views import AppendedDiscussionEntryView, appended_discussion_entry
from app.mcp.tools.discussions.arguments import (
    ConclusionDecidedArg,
    ConclusionOpenArg,
    ConclusionSupersededArg,
)
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import discussions as discussions_service


def register(tools: Toolset) -> None:
    """Объявляет `add_conclusion`."""
    runtime = tools.runtime

    @tools.tool(title="Add conclusion", annotations=FILING, creating=True)
    async def add_conclusion(
        key: DiscussionAddressArg,
        decided: ConclusionDecidedArg,
        superseded: ConclusionSupersededArg,
        open: ConclusionOpenArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedDiscussionEntryView:
        """Files a conclusion in a discussion's case: where the discussion stands, as
        decided, superseded and still open. An empty part is refused with
        `entry_fields_invalid` naming it.

        The latest conclusion outranks the earlier ones, like a task's latest summary,
        and sets the work of the attached tasks together with their sections; `get_task`
        carries it. The turn then stays no one's until an answer or an entry of a person.
        A closed discussion refuses it with `discussion_closed`.
        """
        async with runtime.call() as (session, actor):
            discussion = await discussions_service.get_discussion(session, key)

            async def append() -> AppendedDiscussionEntryView:
                entry = await case_service.add_conclusion(
                    session,
                    discussion,
                    actor=actor,
                    decided=decided,
                    superseded=superseded,
                    open=open,
                )
                return appended_discussion_entry(entry, discussion=discussion.address)

            return await Once.of(add_conclusion, session, actor, idempotency_key).run(
                result=AppendedDiscussionEntryView,
                request={
                    "discussion": discussion.address,
                    "decided": decided,
                    "superseded": superseded,
                    "open": open,
                },
                build=append,
            )
