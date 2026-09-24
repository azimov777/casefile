"""Аргументы записи дела, общие для нескольких инструментов: поля записи без нагрузки,
части сводки, исход проверки.

Их же берут `close_task` — поля его вложенных моделей объявлены теми же аннотациями — и
`wait_journal` (`EntryTypesArg`): описание поля одно на весь сервер.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.case import EntryType
from app.mcp.enums import EntryTypeSchema, VerdictOutcomeSchema

EntryBodyArg = Annotated[
    str,
    Field(
        description=(
            "Entry body in markdown, stored and returned as is. It holds what a successor "
            "needs to continue; file contents and long outputs stay outside it, "
            "represented by a pointer and the gist"
        )
    ),
]


EntryRefsArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "References: entries `TRK-42#12`, tasks `TRK-7`, URLs. An entry or task that "
            "does not exist is refused with `entry_fields_invalid`; URLs are not checked"
        ),
        examples=[["TRK-42#12"]],
    ),
]


#: Типы, которые подшивает `add_entry`, — те, у которых нет нагрузки. Структурные записи
#: идут своими инструментами: у сводки, вопроса, ответа и вердикта нагрузка есть, и
#: принимать её свободным словарём значило бы отдать проверку формы агенту.
#:
#: Набор объявлен `Literal` прямо в аннотации, а не проверкой в теле инструмента: агент
#: видит допустимые значения в самой схеме и не узнаёт о них из отказа.
#:
#: Описание поля — правила выбора типа из таблицы TRK-141 (4.1, 3.5, 4.2, 4.3, 8.6, 8.7):
#: у записи без нагрузки выбор типа и есть решение агента, и других мест для него нет.
EntryTypeArg = Annotated[
    Literal[
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.REMARK,
        EntryType.NOTE,
    ],
    Field(
        description=(
            "What the entry records:\n"
            "- `decision` — an option chosen among several, with the reason;\n"
            "- `attempt` — something tried and how it ended, failed attempts included;\n"
            "- `finding` — an established fact with its source, including what was "
            "learned from reading;\n"
            "- `artifact` — a pointer to a result;\n"
            "- `remark` — a claim that finished work of a task came out wrong, written "
            "from the side of whoever needs the result; the task's assignee resolves it "
            "with `resolve`. A remark on a closed task is accepted: the case grows, the "
            "task stays as it is. An observation about the caller's own task is a "
            "`finding`, not a `remark`;\n"
            "- `note` — an entry that fits none of the types above"
        )
    ),
]


EntryTitleArg = Annotated[
    str,
    Field(
        description=(
            "Entry title: its line in the case index of `get_task`. It states what "
            "happened, not how"
        )
    ),
]


VerdictOutcomeArg = Annotated[
    VerdictOutcomeSchema, Field(description="Outcome of the check; there is no third state")
]


EntryTypesArg = Annotated[
    list[EntryTypeSchema] | None, Field(description="Only entries of these types")
]


SummaryDoneArg = Annotated[
    str,
    Field(
        description=(
            "What was done since the previous summary, with references to artifacts. Its "
            "first line becomes the entry title in the case index: one sentence about "
            "what happened; a longer line is cut at a word boundary"
        )
    ),
]


SummaryRemainingArg = Annotated[str, Field(description="What remains before the task is done")]


SummaryBlockersArg = Annotated[
    str,
    Field(
        description=(
            "What stands in the way, or `nothing`. In a summary before `waiting` it names "
            "what is awaited and from whom"
        )
    ),
]


SummaryNextStepArg = Annotated[
    str,
    Field(
        description=(
            "The one concrete action a successor starts with. In a summary before "
            "`waiting` it is the action taken once the awaited arrives. A doubt about a "
            "decision or a result is recorded here, as what to look at and why, rather "
            "than as a verdict"
        )
    ),
]


SummaryUnmeasuredArg = Annotated[
    str,
    Field(
        description=(
            "Which part of the task's goal no review check measured, and which risks the "
            "author considers theoretical: what was done but not proven, what was run by "
            "hand instead of a check, where a conclusion rests on similarity rather than "
            "measurement. A verdict answers its check, not the goal. `nothing` is a "
            "valid value when the checks covered the whole goal"
        )
    ),
]


CheckNoArg = Annotated[
    int,
    Field(
        description=(
            "Number of the review check in the task's list, from 1; a number outside the "
            "list is refused with `entry_fields_invalid`"
        )
    ),
]


EvidenceArg = Annotated[
    str,
    Field(
        description=(
            "What was run for the check as written and what it showed: the command, its "
            "output, a link to the material"
        )
    ),
]
