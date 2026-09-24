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

## Частичное изменение — вложенная модель

У инструмента нет способа отличить пропущенный аргумент от `null`, если у параметра есть
значение по умолчанию (`docs/notes/mcp.md`). Поэтому изменения задачи приезжают объектом
`changes`, поля которого объявлены через `unset_field`, а `model_dump(exclude_unset=True)`
отдаёт ровно переданные ключи. Без этого правка тегов каждый раз снимала бы исполнителя,
а снять его было бы нечем.

## Перечисления

Типы перечислений берутся из `app/mcp/enums.py`, а не из домена напрямую: схема домена
несёт русскую докстроку класса (шапка того модуля).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.sentinels import unset_field
from app.domain.case import EntryType
from app.domain.idempotency import KEY_TTL
from app.domain.journal import JOURNAL_START, MAX_TASK_KEYS, MAX_WAIT_SECONDS
from app.domain.query_language import (
    QUERY_EXAMPLES,
    QUERY_RIGHT_SHAPE,
    QUERY_WRONG_SHAPE,
)
from app.domain.search import (
    FEATURES_FIELD,
    PARENT_FIELD,
    searchable_names,
    selectable_names,
    sortable_names,
)
from app.domain.tasks import (
    FIRST_CHECK_NUMBER,
    MAX_CHECK_LENGTH,
    feature_names,
)
from app.mcp.enums import (
    EntryTypeSchema,
    LinkKindSchema,
    ParticipantKindSchema,
    RemarkOutcomeSchema,
    TaskPrioritySchema,
    TaskStatusSchema,
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
ParentKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Key of the parent task: the new task is born as its child. A closed parent "
            "is refused with `task_closed`. The parent is not closed — neither `done` "
            "nor `cancelled` — while any of its children is open"
        ),
        examples=["TRK-42"],
    ),
]
VersionArg = Annotated[
    int | None,
    Field(
        description=(
            "Task version read earlier. When given and the task has changed since, the "
            "call is refused with `version_conflict` instead of overwriting the other "
            "change; when left out, the edit applies on top of the current version"
        )
    ),
]

# --- Поля задачи ----------------------------------------------------------------------

TaskTitleArg = Annotated[str, Field(description="Task title, one line")]
TaskDescriptionArg = Annotated[
    str,
    Field(
        description=(
            "What happened and why it is a task. For a continuation of a closed task it "
            "names the task the work grew from; the lineage itself is a `relates` link"
        )
    ),
]
AssigneeArg = Annotated[
    str | None,
    Field(
        description=(
            "Participant name or temporary agent label. The tracker never sets or clears "
            "it by itself; only a caller whose signature matches it moves the task into "
            "`in_progress`"
        )
    ),
]
PriorityArg = Annotated[TaskPrioritySchema, Field(description="Task priority")]
ReasonArg = Annotated[
    str | None,
    Field(
        description=(
            "Why the task moves. Required for any step back along `backlog < open < "
            "in_progress < done`, for `cancelled` and for `waiting` "
            "(`transition_reason_required` otherwise), optional elsewhere. For `waiting` "
            "it is the only record of what the task waits for. Filed in the "
            "`status_changed` entry"
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

# --- Вложенные модели -----------------------------------------------------------------
#
# Докстрока вложенной модели — её описание в схеме, то есть метадата: английская и
# короткая. Доводы разработчика стоят комментарием над классом.


class TaskSections(BaseModel):
    """The five task sections; they are editable only while the task is in `backlog`."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(default="", description="Why the task exists and what will change")
    context: str = Field(default="", description="What already exists and what the work relies on")
    constraints: str = Field(
        default="", description="What is out of scope and what stays unchanged"
    )
    output: str = Field(default="", description="What exists once the task is done")
    checks: list[str] = Field(
        default_factory=list,
        description=(
            "Review checks in order, numbered from 1; each names what is run and the "
            "expected result"
        ),
    )


SectionsArg = Annotated[
    TaskSections | None,
    Field(
        description=(
            "The five sections. The task moves from `backlog` to `open` only with four "
            "non-empty text sections and at least one check (`task_sections_incomplete` "
            "otherwise); until then they can be completed with `update_task`"
        )
    ),
]


class CheckEditArg(BaseModel):
    """Rewrite of one check: its number and new text."""

    model_config = ConfigDict(extra="forbid")

    no: int = Field(
        ge=FIRST_CHECK_NUMBER,
        description="Number of the check in the current list, from 1",
    )
    text: str = Field(
        min_length=1,
        max_length=MAX_CHECK_LENGTH,
        description="New wording of this check",
    )


# `null` осмыслен только у `assignee`: он снимает исполнителя. У остальных полей `null`
# смысла не имеет, и схема его не пропустит. Статуса здесь нет — он меняется
# `transition`; ключа нет — он неизменяем.
class TaskChanges(BaseModel):
    """Fields to change; a field left out stays as it is. Title, description, sections
    and checks are editable only in `backlog`; elsewhere they are refused with
    `task_field_locked`.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(description="Task title")
    description: str = unset_field(description="Task description")
    goal: str = unset_field(description="Section `goal`")
    context: str = unset_field(description="Section `context`")
    constraints: str = unset_field(description="Section `constraints`")
    output: str = unset_field(description="Section `output`")
    checks: list[str] = unset_field(
        description=(
            "All review checks as a list: changes their composition — a check added, "
            "removed or moved"
        )
    )
    check: CheckEditArg = unset_field(
        description=(
            "Rewrites one check in place; the other checks stay byte for byte, and the "
            "`section_changed` entry names the check number. Refused together with "
            "`checks` (`task_fields_invalid`)"
        )
    )
    assignee: str | None = unset_field(
        description=(
            "Participant name or temporary agent label; `null` clears it. The name is "
            "compared with the caller's signature regardless of case, and every session "
            "signed with that name counts as the assignee. Replacing another "
            "participant's name takes the task over from them: the tracker accepts it, "
            "files `assignee_changed` and informs no one"
        )
    )
    priority: TaskPrioritySchema = unset_field(description="Task priority")


# --- Закрытие -------------------------------------------------------------------------
#
# Поля вложенных моделей объявлены **теми же** аннотациями, что и одиночные аргументы
# подшивающих инструментов: описание у части сводки одно на весь сервер, и второй его
# копии, которая разойдётся с первой, здесь нет.


# `unmeasured` обязателен: значение по умолчанию превратило бы «чего не измерили» в
# поле, которое молча опускают ровно в тех делах, где оно и нужно.
class ClosingSummary(BaseModel):
    """Final summary: the four parts of `add_summary` plus `unmeasured`. It takes no
    title: the first line of `done` becomes it.
    """

    model_config = ConfigDict(extra="forbid")

    done: SummaryDoneArg
    remaining: SummaryRemainingArg
    blockers: SummaryBlockersArg
    next_step: SummaryNextStepArg
    unmeasured: SummaryUnmeasuredArg


class ClosingVerdict(BaseModel):
    """Outcome of one review check with its evidence."""

    model_config = ConfigDict(extra="forbid")

    check_no: CheckNoArg
    outcome: VerdictOutcomeArg
    evidence: EvidenceArg = ""


class ClosingEntry(BaseModel):
    """An entry without payload, of the same shape as in `add_entry`."""

    model_config = ConfigDict(extra="forbid")

    type: EntryTypeArg
    title: EntryTitleArg
    body: EntryBodyArg = ""
    refs: EntryRefsArg = None


ClosingSummaryArg = Annotated[
    ClosingSummary,
    Field(
        description=(
            "The summary the task closes with, filed last and reporting the outcome of "
            "the entries and verdicts before it: the first line of `done` states how the "
            "task ended, `remaining` is `nothing` or the key of the task the rest went "
            "to, `next_step` is `no steps` or that key"
        )
    ),
]
ClosingVerdictsArg = Annotated[
    list[ClosingVerdict] | None,
    Field(
        description=(
            "Verdicts filed by this call. The list may be empty: verdicts filed earlier "
            "in the current pass count equally. A refused call files none of them, so a "
            "`failed` verdict sent here leaves no trace in the case, unlike one filed "
            "with `add_verdict`"
        )
    ),
]
ClosingEntriesArg = Annotated[
    list[ClosingEntry] | None,
    Field(
        description=(
            "Entries without payload filed before the verdicts, such as `artifact` pointers "
            "to the result"
        )
    ),
]


# --- Отбор задач ----------------------------------------------------------------------

#: Что `search_tasks` просит по умолчанию. Узкий набор не оптимизация, а требование:
#: полная задача с пятью разделами на страницу в двадцать пять строк съедает контекст
#: ровно там, где агент выбирает, что брать.
#:
#: Признаки в набор входят: они короткие, а решение «брать ли задачу» без них не
#: принимается — иначе агент звал бы `get_task` на каждую строку выдачи, чтобы узнать,
#: не заблокирована ли она.
#:
#: Родитель входит по той же причине: без него агент не видит, к какой программе
#: относится задача, и читает `get_task` построчно. Цена замерена (TRK-95#7, тогда ещё
#: списком): у задачи верхнего уровня — `"parent":null`, у ребёнка — ключ и название.
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = (
    "key",
    "title",
    "status",
    "assignee",
    "priority",
    FEATURES_FIELD,
    PARENT_FIELD,
)

QueryArg = Annotated[
    str | None,
    Field(
        description=(
            "Query language string. A condition is written `name: [operator] values`: the "
            "operator stands **after** the colon, unlike SQL — "
            f"`{QUERY_RIGHT_SHAPE}`, not `{QUERY_WRONG_SHAPE}`. Parentheses group "
            "conditions, not values.\n\n"
            "Without an operator a condition means equality, and comma-separated values "
            "mean membership: `status: open, in_progress` equals "
            f"`{QUERY_RIGHT_SHAPE}`.\n\n"
            "Fields: " + ", ".join(f"`{name}`" for name in searchable_names()) + ". "
            "Operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` (substring), `!~`, `in`, "
            "`not in`; `empty()` matches tasks without a value. Conditions combine with "
            "`and` and `or`.\n\n"
            "Examples:\n"
            + "\n".join(f"- `{example}`" for example in QUERY_EXAMPLES)
            + "\n\nA string that does not parse is refused with `invalid_search_query` "
            "and the character position, plus the correct form in `details.hint` where "
            "the error position determines it"
        ),
        examples=list(QUERY_EXAMPLES),
    ),
]
SortArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Sort order, most significant key first; a leading `-` sorts descending. "
            "Allowed: " + ", ".join(f"`{name}`" for name in sortable_names())
        ),
        examples=[["-updated_at"]],
    ),
]
# Домен значений называется целиком и собирается из домена, а не переписывается словами:
# описание и `details.allowed` отказа обязаны быть одним списком в одном порядке, иначе
# агент решит, что набор зависит от вызова. Место здесь дорогое — описание `search_tasks`
# самое длинное в установке, — поэтому названы имена и ничего больше.
FieldsArg = Annotated[
    list[str],
    Field(
        description=(
            "Fields to return: "
            + ", ".join(f"`{name}`" for name in selectable_names())
            + ". The key always comes back; an empty list returns whole tasks. "
            "`features` brings the computed features: "
            + ", ".join(f"`{name}`" for name in feature_names())
            + ". `parent` is the parent's key and title, or `null`"
        )
    ),
]

# Структурный отбор: по аргументу на поле. Значения одного аргумента складываются по
# «или», аргументы между собой — по «и». Тот же разбор значений, что и у языка, поэтому
# `assignee: ["empty()"]` и строка `assignee: empty()` значат буквально одно и то же:
# своя ветка условий здесь развела бы MCP с REST на первом же краевом случае.
KeysArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Task keys: several named tasks in one call. An unknown key is refused with "
            "`search_value_invalid`, `reason: task_not_found`, rather than left out"
        ),
        examples=[["TRK-42", "TRK-43"]],
    ),
]
QueuesArg = Annotated[list[str] | None, Field(description="Queue keys", examples=[["TRK"]])]
StatusesArg = Annotated[list[TaskStatusSchema] | None, Field(description="Task statuses")]
AssigneesArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Assignee names, exact match; `empty()` matches tasks without an assignee. A "
            "name covers every session signed with it: no value selects the tasks of one "
            "session"
        )
    ),
]
ParentFilterArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Parent task keys: their **direct** children, one level down. `empty()` "
            "matches tasks without a parent, the top level of a queue. An unknown key is "
            "refused rather than read as «no children»"
        ),
        examples=[["TRK-7"]],
    ),
]
PrioritiesArg = Annotated[list[TaskPrioritySchema] | None, Field(description="Priorities")]
BlockedArg = Annotated[
    bool | None,
    Field(
        description=(
            "Whether the task has `blocked_by` on a task that is neither `done` nor `cancelled`"
        )
    ),
]
OpenQuestionsArg = Annotated[
    int | None,
    Field(description="Exact number of unanswered questions; ranges go in `query`"),
]
OpenBlockingQuestionsArg = Annotated[
    int | None,
    Field(description="Exact number of unanswered `blocking` questions; `0` means none blocks"),
]
OpenRemarksArg = Annotated[
    int | None,
    Field(description="Exact number of unresolved remarks; ranges go in `query`"),
]
RemarksInWorkArg = Annotated[
    int | None,
    Field(
        description=(
            "Number of remarks resolved as `accepted` whose continuation task is not closed yet"
        )
    ),
]
TextArg = Annotated[
    str | None,
    Field(description="Substring of the title or description, case-insensitive"),
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
TaskStatusArg = Annotated[TaskStatusSchema, Field(description="Target status")]
