"""Инструмент `add_verdict`: исход одной обзорной проверки в текущем заходе."""

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import CheckNoArg, EvidenceArg, VerdictOutcomeArg
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет `add_verdict` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def add_verdict(
        key: TaskKeyArg,
        check_no: CheckNoArg,
        outcome: VerdictOutcomeArg,
        evidence: EvidenceArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedEntryView:
        """Files the outcome of one review check, as run by the task's assignee within the
        current pass.

        A pass starts with each entry into `in_progress`, a return from `waiting`
        included. Only verdicts of the current pass count for closing, and the latest
        verdict on a check replaces the earlier ones: a `failed` verdict is filed when
        it happens, like a `passed` one. Verdicts of earlier passes stay in the case
        without counting. `close_task` also takes verdicts, together with the closing.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> AppendedEntryView:
                entry = await case_service.add_verdict(
                    session,
                    task,
                    actor=actor,
                    check_no=check_no,
                    outcome=outcome,
                    evidence=evidence,
                )
                return appended_entry(entry, task_key=task.key)

            return await Once.of(add_verdict, session, actor, idempotency_key).run(
                result=AppendedEntryView,
                request={
                    "task": task.key,
                    "check_no": check_no,
                    "outcome": outcome,
                    "evidence": evidence,
                },
                build=append,
            )
