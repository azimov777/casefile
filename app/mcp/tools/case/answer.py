"""Инструмент `answer`: ответ на вопрос обсуждения или прежний вопрос дела задачи, его
снятие или замена."""

from typing import Annotated

from pydantic import Field

from app.domain.case import AnswerOutcome
from app.domain.discussions import is_discussion_address
from app.mcp.arguments import IdempotencyKeyArg
from app.mcp.enums import AnswerOutcomeSchema
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg
from app.mcp.tools.case.views import AppendedDiscussionEntryView, appended_discussion_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import tasks as tasks_service

AnswerKeyArg = Annotated[
    str,
    Field(
        description=(
            "Discussion address `PROJECT~N`, or task key `PROJECT-N` for a question filed "
            "in a task's case before questions moved to discussions"
        )
    ),
]

QuestionNoArg = Annotated[
    int,
    Field(
        description=(
            "Number of the `question` entry in the same case. Any other number is refused "
            "with `entry_fields_invalid`, `reason: unknown_entry` or `not_a_question`"
        )
    ),
]

# Правило снятия живёт здесь и в описании инструмента, а не в `instructions`: тот занят
# почти до предела клиента (`tests/test_mcp_instructions.py`), и правило одного
# инструмента — его метадата (TRK-552, ограничения).
AnswerOutcomeArg = Annotated[
    AnswerOutcomeSchema,
    Field(
        description=(
            "How the question is closed, and what the body holds:\n"
            "- `answered` — an answer on its merits; the body is the answer;\n"
            "- `withdrawn` — the question is stale and needs no answer; the body gives "
            "the reason;\n"
            "- `replaced` — a later question of the same case, named in `replaced_by`, "
            "asks instead; the body gives the reason.\n"
            "`withdrawn` and `replaced` require a non-empty body and are accepted only "
            "while the question has no answer: otherwise `entry_fields_invalid`, "
            "`reason: already_answered`"
        )
    ),
]

ReplacedByArg = Annotated[
    int | None,
    Field(
        description=(
            "Number of the `question` entry that replaces this one: in the same case and "
            "filed after it. Required with `replaced` and refused with any other outcome, "
            "both as `entry_fields_invalid`"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `answer`."""
    runtime = tools.runtime

    @tools.tool(title="Answer question", annotations=FILING, creating=True)
    async def answer(
        key: AnswerKeyArg,
        question_no: QuestionNoArg,
        body: EntryBodyArg = "",
        outcome: AnswerOutcomeArg = AnswerOutcome.ANSWERED,
        replaced_by: ReplacedByArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedDiscussionEntryView:
        """Answers a question of a discussion or of a task's case, or closes it unanswered
        as withdrawn or replaced. Any participant answers, in any case.

        The first answer closes the question and later ones add to it; neither a
        question nor an answer changes a task status. A withdrawn or replaced question
        leaves the open questions and their counts, and stays in the case with this
        entry; a question that already has an answer is not withdrawn. The tracker
        builds the title from the question reference and the outcome.
        """
        async with runtime.call() as (session, actor):
            # Владелец разрешается до занятия ключа идемпотентности. Запрос по задаче —
            # той же формы, что до обсуждений: повтор вчерашнего ответа поднимается.
            if is_discussion_address(key):
                discussion = await discussions_service.get_discussion(session, key)
                owner = {"discussion": discussion.address}

                async def append() -> AppendedDiscussionEntryView:
                    entry = await case_service.answer_in_discussion(
                        session,
                        discussion,
                        actor=actor,
                        question_no=question_no,
                        body=body,
                        outcome=outcome,
                        replaced_by=replaced_by,
                    )
                    return appended_discussion_entry(entry, discussion=discussion.address)

            else:
                task = await tasks_service.get_task(session, key)
                owner = {"task": task.key}

                async def append() -> AppendedDiscussionEntryView:
                    entry = await case_service.answer(
                        session,
                        task,
                        actor=actor,
                        question_no=question_no,
                        body=body,
                        outcome=outcome,
                        replaced_by=replaced_by,
                    )
                    return appended_discussion_entry(entry, task_key=task.key)

            return await Once.of(answer, session, actor, idempotency_key).run(
                result=AppendedDiscussionEntryView,
                request={
                    **owner,
                    "question_no": question_no,
                    "body": body,
                    "outcome": outcome,
                    "replaced_by": replaced_by,
                },
                build=append,
            )
