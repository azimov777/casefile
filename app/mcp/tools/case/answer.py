"""Инструмент `answer`: ответ на вопрос той же задачи."""

from typing import Annotated

from pydantic import Field

from app.mcp.arguments import IdempotencyKeyArg, TaskKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg
from app.mcp.tools.case.views import AppendedEntryView, appended_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service

QuestionNoArg = Annotated[
    int,
    Field(
        description=(
            "Number of the `question` entry in the same task. Any other number is refused "
            "with `entry_fields_invalid`, `reason: unknown_entry` or `not_a_question`"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `answer` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def answer(
        key: TaskKeyArg,
        question_no: QuestionNoArg,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedEntryView:
        """Answers a question of the same task. Any holder of a `task` token answers, in
        any task.

        The first answer closes the question and later ones add to it; neither a
        question nor an answer changes the task status. The tracker builds the title
        from the question reference.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> AppendedEntryView:
                entry = await case_service.answer(
                    session, task, actor=actor, question_no=question_no, body=body
                )
                return appended_entry(entry, task_key=task.key)

            return await Once.of(answer, session, actor, idempotency_key).run(
                result=AppendedEntryView,
                request={"task": task.key, "question_no": question_no, "body": body},
                build=append,
            )
