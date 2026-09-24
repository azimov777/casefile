"""Аргументы инструментов: общие аннотации и вложенные модели.

Описание аргумента — то, что модель читает о поле в `tools/list`: смысл, формат,
допустимые значения, как поле заполняется, на что влияет и каким кодом трекер откажет.
Всё, что относится к одному полю, стоит здесь, а не в описании инструмента.

## Правила текста метадаты

Решение владельца TRK-140#8: скила в проекте нет, и правила работы с одним инструментом
(выбор типа записи, части сводки, `unmeasured`, исходы замечания и прочие строки таблицы
TRK-141#15–#17) живут в его метадате. Прежнее правило «дисциплину в описания не
переносить» (TRK-33, TRK-129) этим отменено. Как писать сам текст — TRK-140#18:

- язык — английский: описания инструментов, аргументов, вложенных моделей, полей ответа
  и перечислений в схеме;
- без повелительного наклонения, советов «делай / не делай», оценок, объяснений
  «because» и примеров ситуаций; правило записывается определением или условием;
- примеры — только формата (`TRK-42`, `TRK-42#12`, UUID, язык запросов);
- одно правило — у одного инструмента или поля; свойство всех записей («видна в ленте и
  человеку») стоит один раз в `instructions`.

Всё это стерегут `tests/test_mcp_metadata.py` по живому `tools/list` и README (раздел
`## Tools`).

## Границы значений здесь не повторяются

У схем REST границы длины продублированы ради документации и раннего отсева
(`app/api/schemas/`). Здесь их нет намеренно: проверку делает домен, и его отказ приезжает
агенту предметным кодом со списком полей (`entry_fields_invalid`, `details.fields`), а не
сообщением pydantic о нарушенной схеме. Пустая часть сводки, отсечённая `min_length=1`,
дала бы агенту ошибку валидации аргументов вместо ответа «поле `blockers` обязательно» —
то есть отобрала бы у него имя поля, по которому он чинит вызов.

## Перечисления

Типы перечислений берутся из `app/mcp/enums.py`, а не из домена напрямую: схема домена
несёт русскую докстроку класса (шапка того модуля).
"""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.case import EntryType
from app.domain.idempotency import KEY_TTL
from app.domain.journal import JOURNAL_START, MAX_TASK_KEYS, MAX_WAIT_SECONDS
from app.mcp.enums import (
    EntryTypeSchema,
    LinkKindSchema,
    ParticipantKindSchema,
    RemarkOutcomeSchema,
    VerdictOutcomeSchema,
)

# --- Адресация ------------------------------------------------------------------------

TaskKeyArg = Annotated[
    str,
    Field(
        description=(
            "Task key `QUEUE-N`, case-insensitive. An unknown key is refused with `task_not_found`"
        ),
        examples=["TRK-42"],
    ),
]
QueueKeyArg = Annotated[
    str,
    Field(
        description=(
            "Queue key, case-insensitive. An unknown key is refused with `queue_not_found`"
        ),
        examples=["TRK"],
    ),
]
NewQueueKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the new queue: a Latin letter followed by 1–15 Latin letters or digits "
            "(`invalid_queue_key` otherwise). It is stored upper-case, never changes and "
            "prefixes the key of every task of the queue. A key already taken, in any "
            "case, is refused with `queue_key_taken`"
        ),
        examples=["TRK"],
    ),
]
ParticipantNameArg = Annotated[
    str,
    Field(
        description=(
            "Participant name, case-insensitive. An unknown name is refused with "
            "`participant_not_found`"
        )
    ),
]
NewParticipantNameArg = Annotated[
    str,
    Field(
        description=(
            "Name of the new participant: a Latin letter followed by 1–63 Latin letters, "
            "digits or `_` (`invalid_participant_name` otherwise). It is stored "
            "lower-case and never changes: it signs the participant's entries. A name "
            "already taken, in any case, is refused with `participant_name_taken`"
        )
    ),
]

# --- Страницы -------------------------------------------------------------------------

LimitArg = Annotated[
    int | None,
    Field(description="Page size. Without a value, the installation's default page size"),
]
CursorArg = Annotated[
    str | None,
    Field(description="`next_cursor` of the previous page; without it, the first page"),
]

# --- Идемпотентность ------------------------------------------------------------------

IdempotencyKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Retry key chosen by the caller, e.g. a UUID. A repeat with the same key and "
            "the same arguments returns the first result and creates nothing; the same "
            "key with other arguments is refused with `idempotency_key_reused`. A key is "
            "bound to the caller's token and kept for "
            f"{int(KEY_TTL.total_seconds() // 3600)} hours"
        ),
        examples=["6b1f0c34-9b2e-4b0a-9a5f-3f1d6c8e0a11"],
    ),
]

# --- Дело -----------------------------------------------------------------------------

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
EntryNosArg = Annotated[list[int] | None, Field(description="Only entries with these numbers")]
EntryTypesArg = Annotated[
    list[EntryTypeSchema] | None, Field(description="Only entries of these types")
]
AfterNoArg = Annotated[
    int | None, Field(description="Only entries filed after the entry with this number")
]

# --- Сводка ---------------------------------------------------------------------------

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

# --- Вопросы и вердикты ---------------------------------------------------------------

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
BlockingArg = Annotated[
    bool,
    Field(
        description=(
            "Whether work on the task can go on without the answer. `true` counts toward "
            "the `open_blocking_questions` feature, by which such tasks are selected; the "
            "tracker does nothing else with it"
        )
    ),
]
QuestionNoArg = Annotated[
    int,
    Field(
        description=(
            "Number of the `question` entry in the same task. Any other number is refused "
            "with `entry_fields_invalid`, `reason: unknown_entry` or `not_a_question`"
        )
    ),
]
RemarkNoArg = Annotated[
    int,
    Field(
        description=(
            "Number of the `remark` entry in the same task; any other number is refused "
            "with `entry_fields_invalid`"
        )
    ),
]
RemarkOutcomeArg = Annotated[
    RemarkOutcomeSchema,
    Field(
        description=(
            "How the remark is resolved, and what the body holds:\n"
            "- `fixed` — corrected at once; the body states what changed;\n"
            "- `accepted` — taken into work as a separate task named in `task`;\n"
            "- `needs_detail` — the remark needs clarification; the body holds the "
            "concrete question;\n"
            "- `declined` — nothing will change; the body gives the reason"
        )
    ),
]
ContinuationKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Key of the task the work went to. Required with `accepted` and refused with "
            "any other outcome, both as `entry_fields_invalid`"
        ),
        examples=["TRK-43"],
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

# --- Связи ----------------------------------------------------------------------------

LinkKindArg = Annotated[
    LinkKindSchema,
    Field(
        description=(
            "Role of the task `key` toward the task `other`: "
            "`link(key='TRK-1', kind='blocks', other='TRK-7')` means TRK-1 blocks TRK-7, "
            "and the card of TRK-7 shows the same link as `blocked_by`"
        )
    ),
]
OtherTaskKeyArg = Annotated[
    str,
    Field(description="Key of the task on the other side of the link", examples=["TRK-7"]),
]

# --- Лента --------------------------------------------------------------------------

AfterArg = Annotated[
    int,
    Field(
        ge=JOURNAL_START,
        description=(
            "Journal sequence number `seq` to read after; `0` reads from the start. "
            "Entries are permanent: no `seq` is too old"
        ),
    ),
]
JournalTaskArg = Annotated[
    list[str] | str | None,
    Field(
        description=(
            f"Only entries of these tasks: one key or a list of at most {MAX_TASK_KEYS}. "
            "One wait covers all of them, and an entry in any of them ends it. More keys "
            "are refused with `journal_too_many_tasks`, an unknown key with "
            "`task_not_found`"
        ),
        examples=[["TRK-42", "TRK-43"]],
    ),
]
JournalQueueArg = Annotated[
    str | None,
    Field(description="Only entries of tasks in this queue", examples=["TRK"]),
]
TimeoutArg = Annotated[
    float,
    Field(
        description=(
            "Seconds to wait for the first matching entry when none is there yet, at most "
            f"{MAX_WAIT_SECONDS:.0f} (`journal_wait_too_long` beyond); `0` answers at "
            "once. An empty page after the wait means nothing happened and is not an error"
        )
    ),
]

# --- Реестры ------------------------------------------------------------------------

ParticipantKindArg = Annotated[ParticipantKindSchema, Field(description="Human or permanent agent")]
ParticipantDescriptionArg = Annotated[
    str,
    Field(
        description=(
            "Who the participant is: all that a reader of a case learns about the author "
            "of an entry"
        )
    ),
]
QueueTitleArg = Annotated[str, Field(description="Queue title")]
QueueDescriptionArg = Annotated[
    str,
    Field(description="Queue description in markdown: the shared context of all its tasks"),
]
# Отдельные аннотации для правки: `None` здесь означает «не передано». Осмысленного
# `null` ни у названия, ни у описания нет, поэтому третьего состояния и не нужно — в
# отличие от исполнителя задачи, который `null` как раз снимается.
QueueTitleChangeArg = Annotated[
    str | None, Field(description="New title; when left out, the title stays")
]
QueueDescriptionChangeArg = Annotated[
    str | None, Field(description="New description; when left out, the description stays")
]
