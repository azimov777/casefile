"""Инструмент `unlink`: снятие связи и `link_removed` в обоих делах."""

from app.mcp.arguments import TaskKeyArg
from app.mcp.tools.links.arguments import LinkKindArg, OtherTaskKeyArg
from app.mcp.tools.links.views import LinkFilingView
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import links as links_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет `unlink` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING)
    async def unlink(key: TaskKeyArg, kind: LinkKindArg, other: OtherTaskKeyArg) -> LinkFilingView:
        """Removes a link and files `link_removed` in both cases.

        A link is removed from either side and under either name of its kind: `blocks`
        from `TRK-1` to `TRK-7` and `blocked_by` from `TRK-7` to `TRK-1` are the same
        link. On a closed task `parent` and `blocks` stay (`task_closed`), `relates` is
        removed. A link that does not exist is refused with `link_not_found`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            other_task = await tasks_service.get_task(session, other)
            await links_service.remove_link(session, task, other_task, actor=actor, kind=kind)
            entry = await case_service.latest_entry_no(session, task, actor=actor)
            other_entry = await case_service.latest_entry_no(session, other_task, actor=actor)
            return LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)
