"""Инструмент `read_entries`: тела записей одного дела по номерам, типам и «после»."""

from typing import Annotated

from pydantic import Field

from app.mcp.arguments import CursorArg, LimitArg, TaskKeyArg
from app.mcp.tools.case.arguments import EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import case as case_service
from app.services import tasks as tasks_service

EntryNosArg = Annotated[list[int] | None, Field(description="Only entries with these numbers")]


AfterNoArg = Annotated[
    int | None, Field(description="Only entries filed after the entry with this number")
]


def register(tools: Toolset) -> None:
    """Объявляет `read_entries` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def read_entries(
        key: TaskKeyArg,
        nos: EntryNosArg = None,
        types: EntryTypesArg = None,
        after_no: AfterNoArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[EntryView]:
        """Returns entry bodies of one task's case, with payload, in number order.

        Filters combine with `and`: `types=["summary"]` gives every summary, `after_no`
        everything filed after the named entry, and both together the entries of those
        types filed after it. `decision` and `attempt` entries hold the choices already
        made and the attempts already tried, failed ones included.

        Entries of many cases in one stream, with a wait for new ones, come from
        `wait_journal`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            listed = await case_service.list_entries(
                session,
                task,
                actor=actor,
                nos=nos,
                types=types,
                after_no=after_no,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (entry(item, task_key=task.key) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
