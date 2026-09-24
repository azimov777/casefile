"""Инструменты по связям: поставить и снять.

Обе задачи разрешаются здесь, а не в сценарии: модуль связей намеренно не импортирует
сценарии задач, иначе зависимость стала бы кольцевой (`app/services/links.py`). Ровно то
же самое делает роутер REST — и это не дублирование логики, а разрешение адреса, которое
у каждого интерфейса своё.

Чтения связей отдельным инструментом нет: они приезжают в пакете преемника `get_task`
вместе со статусом задачи на другой стороне. Отдельный инструмент означал бы второй вызов
ради того, что агент получает первым.
"""

from app.mcp import views
from app.mcp.arguments import (
    IdempotencyKeyArg,
    LinkKindArg,
    OtherTaskKeyArg,
    TaskKeyArg,
)
from app.mcp.idempotency import Once
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import links as links_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет инструменты набора `task` по связям."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def link(
        key: TaskKeyArg,
        kind: LinkKindArg,
        other: OtherTaskKeyArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.LinkFilingView:
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
        """
        async with runtime.call() as (session, actor):
            # Ключи разрешаются до занятия ключа идемпотентности: вызов, отклонённый до
            # работы, не должен его тратить.
            task = await tasks_service.get_task(session, key)
            other_task = await tasks_service.get_task(session, other)

            async def add() -> views.LinkFilingView:
                await links_service.add_link(session, task, other_task, actor=actor, kind=kind)
                # Номера читаются из обоих дел, а не протаскиваются через `add_link`
                # (`docs/notes/mcp.md`): под общей блокировкой изменений последняя
                # запись каждого дела — только что подшитый `link_added`.
                entry = await case_service.latest_entry_no(session, task, actor=actor)
                other_entry = await case_service.latest_entry_no(session, other_task, actor=actor)
                return views.LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)

            return await Once.of(link, session, actor, idempotency_key).run(
                result=views.LinkFilingView,
                request={"task": task.key, "kind": kind, "other": other_task.key},
                build=add,
            )

    @tools.tool(annotations=FILING)
    async def unlink(
        key: TaskKeyArg, kind: LinkKindArg, other: OtherTaskKeyArg
    ) -> views.LinkFilingView:
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
            return views.LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)
