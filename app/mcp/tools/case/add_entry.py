"""Инструмент `add_entry`: запись без нагрузки — решение, попытка, находка, артефакт,
замечание, заметка.
"""

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg, EntryRefsArg, EntryTitleArg, EntryTypeArg
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет `add_entry` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def add_entry(
        key: TaskKeyArg,
        type: EntryTypeArg,
        title: EntryTitleArg,
        body: EntryBodyArg = "",
        refs: EntryRefsArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedEntryView:
        """Files an entry without payload: a decision, attempt, finding, artifact, remark
        or note.

        Entries are immutable: no call edits or deletes one, and a mistaken entry is
        corrected by a new entry that references it in `refs`. Summaries, questions,
        answers, verdicts and resolutions have their own tools: `add_summary`, `ask`,
        `answer`, `add_verdict`, `resolve`.

        An empty title is refused with `entry_fields_invalid`, which lists the fields.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> AppendedEntryView:
                entry = await case_service.add_entry(
                    session,
                    task,
                    actor=actor,
                    type=type,
                    title=title,
                    body=body,
                    refs=refs or (),
                )
                return appended_entry(entry, task_key=task.key)

            return await Once.of(add_entry, session, actor, idempotency_key).run(
                result=AppendedEntryView,
                request={
                    "task": task.key,
                    "type": type,
                    "title": title,
                    "body": body,
                    "refs": refs,
                },
                build=append,
            )
