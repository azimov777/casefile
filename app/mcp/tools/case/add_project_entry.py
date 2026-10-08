"""Инструмент `add_project_entry`: запись в дело проекта или области — решение,
находка, артефакт, заметка — и заметка в дело обсуждения по его адресу.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.case import EntryType
from app.domain.discussions import is_discussion_address
from app.mcp.arguments import CaseAddressArg, IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import ENTRY_REFS_DESCRIPTION, EntryBodyArg
from app.mcp.tools.case.views import AppendedProjectEntryView, appended_project_entry
from app.mcp.toolset import FILING, Toolset
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services.case import owner_name

# Набор типов объявлен `Literal` прямо в аннотации, как у `add_entry`: агент видит его в
# схеме до вызова. Он уже, чем у задачи (`PROJECT_ENTRY_TYPES` в домене): у проекта нет
# хода работы, проверок и исполнителя.
ProjectEntryTypeArg = Annotated[
    Literal[EntryType.DECISION, EntryType.FINDING, EntryType.ARTIFACT, EntryType.NOTE],
    Field(
        description=(
            "What the entry records about the project or area:\n"
            "- `decision` — a project or area decision: an option chosen among several, with "
            "the reason, that outlives a task and that other tasks are to follow;\n"
            "- `finding` — an established fact with its source;\n"
            "- `artifact` — a pointer to a result;\n"
            "- `note` — an entry that fits none of the types above; the only type a "
            "discussion's case takes here.\n"
            "Summaries, attempts, verdicts and remarks exist only in task cases, questions "
            "only in discussions (`ask`)"
        )
    ),
]

SupersedesArg = Annotated[
    list[int] | None,
    Field(
        description=(
            "Numbers of earlier entries of the same type in this project's or area's case "
            "that the new entry supersedes: decisions for a `decision`, findings for a "
            "`finding`; accepted only with these two types. A number outside this case or of "
            "another entry type is refused with `entry_fields_invalid`; an entry superseded "
            "already with `decision_not_in_force` or `finding_not_in_force`, its successor "
            "in `details`"
        )
    ),
]

ProjectEntryRefsArg = Annotated[
    list[str] | None,
    Field(
        description=(
            f"{ENTRY_REFS_DESCRIPTION}. A reference to a task's draft — a decision or "
            "finding filed with `draft_for` naming this project or area — lifts the draft, "
            "whatever the type of the referencing entry: the draft leaves the task's "
            "`open_drafts`, and this entry appears in its `lifted_by`. A draft that replaces "
            "an entry of this case is lifted together with `supersedes` naming that entry"
        ),
        examples=[["TRK-42#12"]],
    ),
]

ProjectEntryTitleArg = Annotated[
    str,
    Field(
        description=(
            "Entry title: its line in the case index of `get_project`. It states what "
            "happened, not how"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `add_project_entry`."""
    runtime = tools.runtime

    @tools.tool(title="Add project entry", annotations=FILING, creating=True)
    async def add_project_entry(
        key: CaseAddressArg,
        type: ProjectEntryTypeArg,
        title: ProjectEntryTitleArg,
        body: EntryBodyArg = "",
        refs: ProjectEntryRefsArg = None,
        supersedes: SupersedesArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedProjectEntryView:
        """Files an entry in the case of a project or of an area: a decision, finding,
        artifact or note that concerns it rather than one of its tasks. A discussion
        address files a note in the discussion's case.

        The entry number counts inside the project, area or discussion, and `TRK#7`,
        `TRK/promotion#3` or `TRK~7#3` addresses the entry from `refs` of any case. Like a
        task entry filed by `add_entry`, such an entry stays as filed.

        A decision or finding, in a project's case and in an area's alike, is in force
        until a later entry of the same type in that case names it in `supersedes`; no
        entry changes, and the status is computed on read. Withdrawing a decision or finding with no
        replacement is an entry of the same type too, one that supersedes it. An area's
        decisions in force bind the work in that area.

        An empty title, or a reference to a missing entry, task or project, returns
        `entry_fields_invalid` naming the offending fields.
        """
        async with runtime.call() as (session, actor):
            if is_discussion_address(key):
                discussion = await discussions_service.get_discussion(session, key)

                async def note() -> AppendedProjectEntryView:
                    entry = await case_service.add_discussion_entry(
                        session,
                        discussion,
                        actor=actor,
                        type=type,
                        title=title,
                        body=body,
                        refs=refs or (),
                        supersedes=supersedes,
                    )
                    return appended_project_entry(entry, project_key=discussion.address)

                return await Once.of(add_project_entry, session, actor, idempotency_key).run(
                    result=AppendedProjectEntryView,
                    request={
                        "discussion": discussion.address,
                        "type": type,
                        "title": title,
                        "body": body,
                        "refs": refs,
                        "supersedes": supersedes,
                    },
                    build=note,
                )
            owner = await areas_service.get_owner(session, key)

            async def append() -> AppendedProjectEntryView:
                entry = await case_service.append_project_entry(
                    session,
                    owner,
                    actor=actor,
                    type=type,
                    title=title,
                    body=body,
                    refs=refs or (),
                    supersedes=supersedes,
                )
                return appended_project_entry(entry, project_key=owner_name(owner))

            return await Once.of(add_project_entry, session, actor, idempotency_key).run(
                result=AppendedProjectEntryView,
                request={
                    "project": owner_name(owner),
                    "type": type,
                    "title": title,
                    "body": body,
                    "refs": refs,
                    "supersedes": supersedes,
                },
                build=append,
            )
