"""Инструмент `link`: связь двух задач и `link_added` в обоих делах — или привязка задачи
к обсуждению (`attached`) и `attached` в обоих делах."""

from app.domain.links import LinkKind
from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.enums import LinkToolKind
from app.mcp.idempotency import Once
from app.mcp.tools.links.arguments import LinkKindArg, OtherTaskKeyArg
from app.mcp.tools.links.views import LinkFilingView
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import links as links_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет `link`."""
    runtime = tools.runtime

    @tools.tool(title="Link tasks", annotations=FILING, creating=True)
    async def link(
        key: TaskKeyArg,
        kind: LinkKindArg,
        other: OtherTaskKeyArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> LinkFilingView:
        """Links two tasks and files `link_added` in both cases.

        `kind` is the role of `key`: `blocks` means `key` blocks `other`, and the card
        of `other` shows the link as `blocked_by`. A link is stored once: the same link
        from the other side is refused with `link_exists`, like a repeat. A link closing
        a cycle is refused with `link_cycle_detected`, a link of a task to itself with
        `link_self_not_allowed`.

        `parent` and `child` set the hierarchy, shown by `get_task` in the fields
        `parent` and `children` rather than in `links`. A task has one parent: a second
        one is refused with `task_has_parent`, the current parent named in
        `details.parent`.

        An open blocker raises the `blocked` feature of the blocked task and keeps it
        out of `in_progress` with `task_blocked`.

        A closed task (`done`, `cancelled`) accepts only `relates`, the link to a
        continuation grown from it; `parent` and `blocks` on it are refused with
        `task_closed`. Only a link shows the lineage on the cards of both tasks: a key
        mentioned in an entry body or in `refs` does not.

        `attached` attaches the task to the discussion `other` and files `attached` in
        both cases: the task depends on its outcome, shown in the `discussions` of
        `get_task`. A repeat is refused with `discussion_task_exists`, a closed task with
        `task_closed`, a closed discussion with `discussion_closed`.
        """
        async with runtime.call() as (session, actor):
            # Ключи разрешаются до занятия ключа идемпотентности: вызов, отклонённый до
            # работы, не должен его тратить.
            task = await tasks_service.get_task(session, key)
            if kind is LinkToolKind.ATTACHED:
                discussion = await discussions_service.get_discussion(session, other)

                async def attach() -> LinkFilingView:
                    await discussions_service.attach_task(session, discussion, task, actor=actor)
                    entry = await case_service.latest_entry_no(session, task, actor=actor)
                    other_entry = await case_service.latest_discussion_entry_no(session, discussion)
                    return LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)

                return await Once.of(link, session, actor, idempotency_key).run(
                    result=LinkFilingView,
                    request={"task": task.key, "kind": kind, "other": discussion.address},
                    build=attach,
                )
            other_task = await tasks_service.get_task(session, other)

            async def add() -> LinkFilingView:
                await links_service.add_link(
                    session, task, other_task, actor=actor, kind=LinkKind(kind)
                )
                # Номера читаются из обоих дел, а не протаскиваются через `add_link`
                # (`TRK/mcp#28`): под общей блокировкой изменений последняя
                # запись каждого дела — только что подшитый `link_added`.
                entry = await case_service.latest_entry_no(session, task, actor=actor)
                other_entry = await case_service.latest_entry_no(session, other_task, actor=actor)
                return LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)

            return await Once.of(link, session, actor, idempotency_key).run(
                result=LinkFilingView,
                request={"task": task.key, "kind": kind, "other": other_task.key},
                build=add,
            )
