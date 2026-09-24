"""Инструмент `wait_journal`: записи ленты после номера `after`, с ожиданием новых."""

from typing import Annotated

from pydantic import Field

from app.domain.journal import JOURNAL_START, MAX_TASK_KEYS, MAX_WAIT_SECONDS
from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.tools.case.arguments import EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import journal as journal_service

AfterArg = Annotated[
    int,
    Field(
        ge=JOURNAL_START,
        description=(
            "Journal sequence number `seq` to read after; `0` reads from the start. "
            "Entries are permanent: no `seq` is too old"
        ),
    ),
]

JournalTaskArg = Annotated[
    list[str] | str | None,
    Field(
        description=(
            f"Only entries of these tasks: one key or a list of at most {MAX_TASK_KEYS}. "
            "One wait covers all of them, and an entry in any of them ends it. More keys "
            "are refused with `journal_too_many_tasks`, an unknown key with "
            "`task_not_found`"
        ),
        examples=[["TRK-42", "TRK-43"]],
    ),
]

JournalQueueArg = Annotated[
    str | None,
    Field(description="Only entries of tasks in this queue", examples=["TRK"]),
]

TimeoutArg = Annotated[
    float,
    Field(
        description=(
            "Seconds to wait for the first matching entry when none is there yet, at most "
            f"{MAX_WAIT_SECONDS:.0f} (`journal_wait_too_long` beyond); `0` answers at "
            "once. An empty page after the wait means nothing happened and is not an error"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `wait_journal` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def wait_journal(
        after: AfterArg = JOURNAL_START,
        task: JournalTaskArg = None,
        queue: JournalQueueArg = None,
        types: EntryTypesArg = None,
        timeout: TimeoutArg = 0,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[EntryView]:
        """Returns journal entries after the sequence number `after`, waiting for new ones.

        The journal is every case entry of the installation in one stream, in `seq`
        order; `task`, `queue` and `types` narrow it. The call returns as soon as a
        matching entry appears, and after `timeout` seconds at the latest. The next call
        continues from the `seq` of the last entry received. With `types=["answer"]` and
        `task`, one call covers an answer expected within `timeout`.

        Entries already filed in one case, by number, are returned by `read_entries`.
        """
        async with runtime.call() as (session, actor):
            listed = await journal_service.wait_journal(
                session,
                actor=actor,
                journal_filter=await journal_service.resolve_filter(
                    session, task=task, queue=queue, types=types
                ),
                after=after,
                cursor=cursor,
                limit=limit or settings.mcp_page_size,
                wait=timeout,
            )
            return page(
                (entry(item.entry, task_key=item.task_key) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
