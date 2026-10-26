"""Инструмент `unlink`: снятие связи и `link_removed` в обоих делах — или отвязка задачи от
обсуждения (`attached`) и `detached` в обоих делах — или снятие связи областей `see_also` и
`link_removed` в делах обеих областей."""

from app.domain.areas import is_area_address
from app.domain.errors import InvalidLinkKindError
from app.domain.links import LinkKind
from app.mcp.enums import LinkToolKind
from app.mcp.tools.links.arguments import LinkKeyArg, LinkKindArg, OtherTaskKeyArg
from app.mcp.tools.links.views import LinkFilingView
from app.mcp.toolset import FILING, Toolset
from app.services import area_links as area_links_service
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import links as links_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет `unlink`."""
    runtime = tools.runtime

    @tools.tool(title="Unlink tasks or areas", annotations=FILING)
    async def unlink(key: LinkKeyArg, kind: LinkKindArg, other: OtherTaskKeyArg) -> LinkFilingView:
        """Removes a link and files `link_removed` in both cases.

        A link is removed from either side and under either name of its kind: `blocks`
        from `TRK-1` to `TRK-7` and `blocked_by` from `TRK-7` to `TRK-1` are the same
        link. On a closed task `parent` and `blocks` stay (`task_closed`), `relates` is
        removed. A link that does not exist is refused with `link_not_found`.

        `attached` detaches the task from the discussion `other` and files `detached` in
        both cases; the task no longer waits for its outcome. A task that is not attached
        is refused with `discussion_task_not_found`, a closed discussion with
        `discussion_closed`.

        `see_also` removes the link of the area `key` to `other`; the opposite one stays.
        A missing one is refused with `area_link_not_found`.
        """
        async with runtime.call() as (session, actor):
            if is_area_address(key):
                if kind is not LinkToolKind.SEE_ALSO:
                    raise InvalidLinkKindError(
                        details={"kind": kind.value, "allowed": [LinkToolKind.SEE_ALSO.value]}
                    )
                source = await areas_service.get_area(session, key)
                target = await areas_service.get_area(session, other)
                await area_links_service.remove_area_link(session, source, target, actor=actor)
                entry = await case_service.latest_area_entry_no(session, source)
                other_entry = await case_service.latest_area_entry_no(session, target)
                return LinkFilingView(key=source.address, entry=entry, other_entry=other_entry)
            if kind is LinkToolKind.SEE_ALSO:
                raise InvalidLinkKindError(
                    details={"kind": kind.value, "allowed": [k.value for k in LinkKind]}
                )
            task = await tasks_service.get_task(session, key)
            if kind is LinkToolKind.ATTACHED:
                discussion = await discussions_service.get_discussion(session, other)
                await discussions_service.detach_task(session, discussion, task, actor=actor)
                entry = await case_service.latest_entry_no(session, task, actor=actor)
                other_entry = await case_service.latest_discussion_entry_no(session, discussion)
                return LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)
            other_task = await tasks_service.get_task(session, other)
            await links_service.remove_link(
                session, task, other_task, actor=actor, kind=LinkKind(kind)
            )
            entry = await case_service.latest_entry_no(session, task, actor=actor)
            other_entry = await case_service.latest_entry_no(session, other_task, actor=actor)
            return LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)
