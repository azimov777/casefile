"""Инструмент `add_project_entry`: запись в дело проекта — решение, находка, артефакт,
заметка.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.case import EntryType
from app.mcp.arguments import IdempotencyKeyArg, ProjectKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.case.arguments import EntryBodyArg, EntryRefsArg
from app.mcp.tools.case.views import AppendedProjectEntryView, appended_project_entry
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import projects as projects_service

# Набор типов объявлен `Literal` прямо в аннотации, как у `add_entry`: агент видит его в
# схеме до вызова. Он уже, чем у задачи (`PROJECT_ENTRY_TYPES` в домене): у проекта нет
# хода работы, проверок и исполнителя.
ProjectEntryTypeArg = Annotated[
    Literal[EntryType.DECISION, EntryType.FINDING, EntryType.ARTIFACT, EntryType.NOTE],
    Field(
        description=(
            "What the entry records about the project:\n"
            "- `decision` — an option chosen among several, with the reason;\n"
            "- `finding` — an established fact with its source;\n"
            "- `artifact` — a pointer to a result;\n"
            "- `note` — an entry that fits none of the types above.\n"
            "Summaries, questions, attempts, verdicts and remarks exist only in task cases"
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
    """Объявляет `add_project_entry` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def add_project_entry(
        key: ProjectKeyArg,
        type: ProjectEntryTypeArg,
        title: ProjectEntryTitleArg,
        body: EntryBodyArg = "",
        refs: EntryRefsArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AppendedProjectEntryView:
        """Files an entry in a project's case: a decision, finding, artifact or note that
        concerns the project rather than one of its tasks.

        The entry number counts inside the project, and `TRK#7` addresses the entry from
        `refs` of any task or project case. Like a task entry filed by `add_entry`, a
        project entry stays as filed. A `task` token files project entries as it files
        task entries.

        An empty title, or a reference to a missing entry, task or project, returns
        `entry_fields_invalid` naming the offending fields.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)

            async def append() -> AppendedProjectEntryView:
                entry = await case_service.append_project_entry(
                    session,
                    project,
                    actor=actor,
                    type=type,
                    title=title,
                    body=body,
                    refs=refs or (),
                )
                return appended_project_entry(entry, project_key=project.key)

            return await Once.of(add_project_entry, session, actor, idempotency_key).run(
                result=AppendedProjectEntryView,
                request={
                    "project": project.key,
                    "type": type,
                    "title": title,
                    "body": body,
                    "refs": refs,
                },
                build=append,
            )
