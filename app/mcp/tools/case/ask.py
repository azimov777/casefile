"""Инструмент `ask`: вопрос участникам реестра — в обсуждении (решение `TRK#51`, п. 6).

По ключу задачи вопрос заводит обсуждение и привязывает к нему задачу тем же вызовом; по
адресу обсуждения ложится в его дело. В дело задачи вопрос не ложится никогда.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.domain.case import (
    MAX_OPTION_LABEL_LENGTH,
    MAX_OPTION_TEXT_LENGTH,
    MAX_QUESTION_OPTIONS,
    MIN_QUESTION_OPTIONS,
)
from app.domain.discussions import is_discussion_address
from app.mcp.arguments import IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import (
    EntryBodyArg,
    EntryFilesArg,
    EntryRefsArg,
    EntryTitleArg,
)
from app.mcp.tools.case.views import AppendedDiscussionEntryView, appended_discussion_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import tasks as tasks_service

AskKeyArg = Annotated[
    str,
    Field(
        description=(
            "Task key `PROJECT-N`: the call opens a discussion in the task's project, titled "
            "by the question, and attaches the task to it. Discussion address `PROJECT~N`: "
            "the question joins that discussion, its attached tasks unchanged"
        ),
        examples=["TRK-42"],
    ),
]

AddresseesArg = Annotated[
    list[str],
    Field(
        description=(
            "Names of participants from `list_participants`, at least one. A temporary "
            "agent has no registry entry and cannot be addressed. An unknown name is "
            "refused with `entry_fields_invalid`, `reason: unknown_participant`"
        )
    ),
]


class QuestionOption(BaseModel):
    """One answer option of a question: a short label and the text it stands for."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        description=(
            f"Short mark of the option, up to {MAX_OPTION_LABEL_LENGTH} characters, unique "
            "in the question ignoring case; an `answer` names it in `choice`"
        )
    )
    text: str = Field(
        description=f"What the option means, up to {MAX_OPTION_TEXT_LENGTH} characters"
    )


OptionsArg = Annotated[
    list[QuestionOption] | None,
    Field(
        description=(
            f"Answer options of a question with a fork, {MIN_QUESTION_OPTIONS} to "
            f"{MAX_QUESTION_OPTIONS} pairs. The addressee picks one in the interface or "
            "in an `answer` with `choice`; free text stays possible beside it. A question "
            "without options takes a free answer. A malformed list is refused with "
            "`entry_fields_invalid`, `field: options`"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `ask`."""
    runtime = tools.runtime

    @tools.tool(title="Ask question", annotations=FILING, creating=True)
    async def ask(
        key: AskKeyArg,
        addressees: AddresseesArg,
        title: EntryTitleArg,
        body: EntryBodyArg = "",
        options: OptionsArg = None,
        refs: EntryRefsArg = None,
        files: EntryFilesArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedDiscussionEntryView:
        """Files a question to registry participants in a discussion. The tracker delivers
        nothing: an addressee sees the question when reading the feed or their inbox.

        A question stays open until an `answer` with its number is filed in the same
        discussion. While it is open, every task attached to the discussion counts it in
        `open_questions` and `open_blocking_questions` and is refused `in_progress` with
        `task_has_open_blocking_questions`; the answer makes a task in `open` a candidate
        again, with no status move. A question to whoever learns of an event outside the
        tracker carries a wait on that event the same way.

        A discussion is one narrow question with its own case; the tasks whose work
        depends on its outcome are attached to it. `add_conclusion` files its conclusion
        and `close_discussion` ends it; an attached task is not closed while it is open.

        What the cases of the parent, its ancestors and sibling tasks already record is
        readable through `get_task` and `read_entries`, without a question.
        """
        option_pairs = [item.model_dump() for item in options] if options is not None else None
        async with runtime.call() as (session, actor):
            # Владелец разрешается до занятия ключа идемпотентности: отклонённый до работы
            # вызов не должен его тратить.
            if is_discussion_address(key):
                discussion = await discussions_service.get_discussion(session, key)
                owner = {"discussion": discussion.address}

                async def append() -> AppendedDiscussionEntryView:
                    entry = await case_service.ask_in_discussion(
                        session,
                        discussion,
                        actor=actor,
                        addressees=addressees,
                        title=title,
                        body=body,
                        options=option_pairs,
                        refs=refs or (),
                        files=files or (),
                    )
                    return appended_discussion_entry(entry, discussion=discussion.address)

            else:
                task = await tasks_service.get_task(session, key)
                owner = {"task": task.key}

                async def append() -> AppendedDiscussionEntryView:
                    opened = await discussions_service.ask_about_task(
                        session,
                        task,
                        actor=actor,
                        addressees=addressees,
                        title=title,
                        body=body,
                        options=option_pairs,
                        refs=refs or (),
                        files=files or (),
                    )
                    return appended_discussion_entry(
                        opened.entry, discussion=opened.discussion.address, attached_task=task.key
                    )

            return await Once.of(ask, session, actor, idempotency_key).run(
                result=AppendedDiscussionEntryView,
                request={
                    **owner,
                    "addressees": addressees,
                    "title": title,
                    "body": body,
                    "refs": refs,
                    **({"options": option_pairs} if option_pairs is not None else {}),
                    **({"files": files} if files else {}),
                },
                build=append,
            )
