"""Инструмент `add_project_entry`: запись в дело проекта или направления — решение,
находка, артефакт, заметка.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.case import EntryType
from app.mcp.arguments import CaseOwnerKeyArg, IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg, EntryRefsArg
from app.mcp.tools.case.views import AppendedProjectEntryView, appended_project_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import directions as directions_service
from app.services.case import owner_name

# Набор типов объявлен `Literal` прямо в аннотации, как у `add_entry`: агент видит его в
# схеме до вызова. Он уже, чем у задачи (`PROJECT_ENTRY_TYPES` в домене): у проекта нет
# хода работы, проверок и исполнителя.
ProjectEntryTypeArg = Annotated[
    Literal[EntryType.DECISION, EntryType.FINDING, EntryType.ARTIFACT, EntryType.NOTE],
    Field(
        description=(
            "What the entry records about the project:\n"
            "- `decision` — a project decision: an option chosen among several, with the "
            "reason, that outlives a task and that other tasks are to follow;\n"
            "- `finding` — an established fact with its source;\n"
            "- `artifact` — a pointer to a result;\n"
            "- `note` — an entry that fits none of the types above.\n"
            "Summaries, questions, attempts, verdicts and remarks exist only in task cases"
        )
    ),
]

SupersedesArg = Annotated[
    list[int] | None,
    Field(
        description=(
            "Numbers of earlier `decision` entries of this project that the new decision "
            "supersedes; accepted only with `decision` in a project's case. A number outside "
            "the project's case "
            "or of another entry type is refused with `entry_fields_invalid`, a decision "
            "superseded already with `decision_not_in_force`, its successor in `details`"
        )
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
        key: CaseOwnerKeyArg,
        type: ProjectEntryTypeArg,
        title: ProjectEntryTitleArg,
        body: EntryBodyArg = "",
        refs: EntryRefsArg = None,
        supersedes: SupersedesArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedProjectEntryView:
        """Files an entry in the case of a project or of a direction: a decision, finding,
        artifact or note that concerns it rather than one of its tasks.

        The entry number counts inside the project or direction, and `TRK#7` or
        `TRK/promotion#3` addresses the entry from `refs` of any case. Like a task entry
        filed by `add_entry`, such an entry stays as filed. A `task` token files project
        entries as it files task entries.

        A project decision is in force until a later decision names it in `supersedes`;
        no entry changes, and the status is computed on read. Withdrawing a decision with
        no replacement is a decision too, one that supersedes it.

        An empty title, or a reference to a missing entry, task or project, returns
        `entry_fields_invalid` naming the offending fields.
        """
        async with runtime.call() as (session, actor):
            owner = await directions_service.get_owner(session, key)

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
