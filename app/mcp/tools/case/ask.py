"""Инструмент `ask`: вопрос участникам реестра, блокирующий или нет."""

from typing import Annotated

from pydantic import Field

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg, EntryTitleArg
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service

AddresseesArg = Annotated[
    list[str],
    Field(
        description=(
            "Names of participants from `list_participants`, at least one. A temporary "
            "agent has no registry entry and cannot be addressed. An unknown name is "
            "refused with `entry_fields_invalid`, `reason: unknown_participant`"
        )
    ),
]

BlockingArg = Annotated[
    bool,
    Field(
        description=(
            "Whether work on the task can go on without the answer. `true` counts toward "
            "the `open_blocking_questions` feature, by which such tasks are selected; the "
            "tracker does nothing else with it"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `ask` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def ask(
        key: TaskKeyArg,
        addressees: AddresseesArg,
        title: EntryTitleArg,
        blocking: BlockingArg,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedEntryView:
        """Files a question to registry participants. The tracker delivers nothing: an
        addressee sees the question when reading the feed or their inbox.

        A question stays open until an `answer` with its number is filed in the same
        task; it counts toward `open_questions`, and with `blocking` toward
        `open_blocking_questions`.

        What the cases of the parent, its ancestors and sibling tasks already record is
        readable through `get_task` and `read_entries`, without a question.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> AppendedEntryView:
                entry = await case_service.ask(
                    session,
                    task,
                    actor=actor,
                    addressees=addressees,
                    title=title,
                    body=body,
                    blocking=blocking,
                )
                return appended_entry(entry, task_key=task.key)

            return await Once.of(ask, session, actor, idempotency_key).run(
                result=AppendedEntryView,
                request={
                    "task": task.key,
                    "addressees": addressees,
                    "title": title,
                    "body": body,
                    "blocking": blocking,
                },
                build=append,
            )
