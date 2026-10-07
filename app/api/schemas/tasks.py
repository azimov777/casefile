"""Схемы задач.

Из них же собирается OpenAPI, поэтому описания и примеры пишутся здесь, а не в роутере.
Границы длины повторяют домен (`app/domain/tasks.py`): в схеме они ради документации и
раннего отсева, настоящую проверку делает домен — одинаково для REST и MCP.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import unset_field
from app.api.schemas.decisions import CitedDecisionRead
from app.api.schemas.discussions import TaskDiscussionRead
from app.api.schemas.entries import (
    ClosingEntryCreate,
    EntryHeadingRead,
    RemarkEntryRead,
    SummaryEntryRead,
    SummaryPartsPayload,
    TaskQuestionRead,
)
from app.api.schemas.links import LinkTaskRead, TaskLinkRead
from app.domain.areas import MAX_AREA_DESCRIPTION_LENGTH
from app.domain.case import MAX_ENTRY_BODY_LENGTH, MAX_SUMMARY_PART_LENGTH, VerdictOutcome
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.domain.state import REASON_LIMIT, RECENT_LIMIT, UNMEASURED_LIMIT
from app.domain.tasks import (
    FIRST_CHECK_NUMBER,
    MAX_ASSIGNEE_LENGTH,
    MAX_CHECK_LENGTH,
    MAX_CHECKS,
    MAX_DECISIONS,
    MAX_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    PARENT_GOAL_LIMIT,
    TaskPriority,
    TaskStatus,
)

_TITLE_EXAMPLE = "Починить выдачу ключей задач"
_DESCRIPTION_EXAMPLE = "Ключ выдаётся до валидации и сгорает на неудачном запросе"
_SECTION_DESCRIPTION = "Markdown section; editable only in `backlog`"
_CHECKS_DESCRIPTION = (
    "Ordered list of checks, numbered from 1 by position; each one must be written so "
    "that it can fail. The assignee runs them and records a verdict per check before "
    "`done`. Editable only in `backlog`"
)
_ASSIGNEE_DESCRIPTION = (
    "Participant name or temporary agent label; free text the tracker never validates "
    "against the registry. Only the assignee can move the task into `in_progress`: "
    "the caller's signature (participant name or agent label) must match it, case-insensitively"
)
_CHECKS_EXAMPLE = ["docker compose run --rm test: the whole suite is green"]
_AREA_DESCRIPTION = (
    "Address `PROJECT/key` of an area of the task's own project. "
    "Another project's area answers `area_project_mismatch`, an unknown one "
    "`area_not_found`, an archived one `area_archived` (a task in an archived area can "
    "move to another one). Not inherited from the parent; set in any status but `done` "
    "and `cancelled`"
)
_NOT_BEFORE_EXAMPLE = "2026-10-08T09:00:00+02:00"
_NOT_BEFORE_DESCRIPTION = (
    "Moment before which the task cannot enter `in_progress` (`task_deferred`): ISO 8601 "
    "date and time with a UTC offset, by the clock of the device that sets it; null for "
    "none. A time without an offset or a date without a time answers `task_fields_invalid`. "
    "The moment arrives with no entry and no status change: the `deferred` feature is "
    "computed on read by the database clock. Set in any status but `done` and `cancelled`; "
    "every change files `field_changed`"
)
_DECISIONS_DESCRIPTION = (
    "Project decisions the task relies on: references `PROJECT#N` to `decision` entries of "
    f"a project's case, up to {MAX_DECISIONS}, in the order set. A task entry (`TRK-42#7`) "
    "answers `task_fields_invalid` with reason `task_entry`, a project entry of another "
    "type `not_a_decision`. A reference not yet in the field must lead to a decision in "
    "force, otherwise `decision_not_in_force` names its successor"
)


class ProjectRefRead(BaseModel):
    """Проект одной строкой: ключ и название — в строке выдачи поиска.

    Описания здесь нет намеренно: строк в выдаче много, и одно и то же описание проекта
    на каждой стоило бы контекста без новой информации. Его несёт карточка задачи
    (`TaskProjectRead`).
    """

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(examples=["TRK"])
    title: str = Field(examples=["Трекер"])


class TaskProjectRead(ProjectRefRead):
    """Проект в карточке задачи: ключ, название, короткое описание и архив (`CONCEPT.md`, 4.2).

    Описание не длиннее 320 знаков как раз затем, чтобы ехать здесь: агент получает
    контекст проекта тем же чтением задачи, без второго вызова. `archived_at` по той же
    причине: заморожен ли проект, видно до первого отказа `project_archived` (TRK-167).
    """

    description: str = Field(
        examples=["Бэкенд трекера задач для агентов: REST API и MCP-сервер"],
        description=(
            f'Short "what this is" of the project, up to {MAX_PROJECT_DESCRIPTION_LENGTH} '
            "characters; may be empty"
        ),
    )
    archived_at: datetime | None = Field(
        examples=[None],
        description="When the project was archived; `null` while it is active",
    )


class TaskAreaRead(BaseModel):
    """Область в карточке задачи: адрес, название, описание и архив (`CONCEPT.md`, 4.2).

    Атрибуты и дело области в карточку не едут: они читаются у самой области по
    адресу. Описание не длиннее 320 знаков по той же причине, что у проекта.
    """

    model_config = ConfigDict(from_attributes=True)

    address: str = Field(
        examples=["TRK/promotion"],
        description="Address of the area: the project key and the area key",
    )
    title: str = Field(examples=["Популяризация"])
    description: str = Field(
        examples=["Каталоги, публикации и день запуска"],
        description=(
            f'Short "what this is" of the area, up to {MAX_AREA_DESCRIPTION_LENGTH} '
            "characters; may be empty"
        ),
    )
    archived_at: datetime | None = Field(
        examples=[None],
        description=(
            "When the area was archived; `null` while it is active. A task cannot be "
            "put into an archived area, but can be taken out of it"
        ),
    )


class TaskRead(BaseModel):
    """Задача в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str = Field(
        examples=["TRK-42"],
        description=(
            "Current key; changes only when the task moves to another project, and the "
            "key it leaves keeps leading to the task (`previous_keys`). Never handed to "
            "another task"
        ),
    )
    previous_keys: list[str] = Field(
        examples=[["UI-124"]],
        description=(
            "Keys the task had before moves to other projects, in the order they were "
            "left; empty for a task never moved. Each one leads to this task wherever a "
            "key is accepted"
        ),
    )
    project: TaskProjectRead
    area: TaskAreaRead | None = Field(
        examples=[None],
        description=(
            "The area of the task inside its project, or `null`: at most one. Taken "
            "from no one: a child does not inherit it from its parent"
        ),
    )
    title: str = Field(examples=[_TITLE_EXAMPLE])
    description: str = Field(examples=[_DESCRIPTION_EXAMPLE])
    goal: str = Field(examples=["Ключи не сгорают на отклонённых запросах"])
    context: str = Field(examples=["Номер выдаёт `projects.next_task_number`"])
    constraints: str = Field(examples=["Счётчик проекта не переписывать"])
    output: str = Field(examples=["Тест на несгоревший номер"])
    checks: list[str] = Field(examples=[_CHECKS_EXAMPLE], description=_CHECKS_DESCRIPTION)
    status: TaskStatus = Field(examples=[TaskStatus.BACKLOG])
    assignee: str | None = Field(examples=["release_bot"], description=_ASSIGNEE_DESCRIPTION)
    priority: TaskPriority = Field(examples=[TaskPriority.NORMAL])
    not_before: datetime | None = Field(
        examples=["2026-10-08T07:00:00Z"],
        description=(
            "Moment before which the task cannot enter `in_progress`, in UTC; `null` for "
            "none. Whether it is still ahead by the database clock is the `deferred` feature"
        ),
    )
    version: int = Field(
        examples=[3],
        description="Grows with every actual change; send it back to detect a lost update",
    )
    created_by: AuthorRead
    created_at: datetime
    updated_at: datetime


class TaskFeaturesRead(BaseModel):
    """Вычисляемые признаки задачи (`CONCEPT.md`, 4.3).

    Не хранятся колонками, а считаются из дела и связей: колонка была бы вторым местом,
    где живёт правда, и разошлась бы с делом при первом же откате.
    """

    blocked: bool = Field(
        examples=[False],
        description=(
            "Whether the task has a `blocked_by` link to a task that is neither `done` "
            "nor `cancelled`. Entering `in_progress` is refused while it is true"
        ),
    )
    deferred: bool = Field(
        examples=[False],
        description=(
            "Whether the task's `not_before` is still ahead by the database clock; false "
            "without one. Entering `in_progress` is refused with `task_deferred` while it is "
            "true; it turns false by itself when the moment arrives"
        ),
    )
    open_questions: int = Field(examples=[2], description="Questions with no answer")
    open_blocking_questions: int = Field(
        examples=[1], description="Of those, the ones marked `blocking`"
    )
    open_remarks: int = Field(
        examples=[1],
        description=(
            "Remarks with no resolution: someone said the result is not what was needed "
            "and nobody has answered yet"
        ),
    )
    open_warnings: int = Field(
        examples=[0],
        description=(
            "1 while the task carries an open warning: it was closed with checks "
            "`partial` or `unverifiable`, and no `acceptance` or `remark` has been filed "
            "after the warning; otherwise 0"
        ),
    )
    last_summary_at: datetime | None = Field(
        default=None,
        description="When the latest summary was filed; null if the case has none",
    )
    last_entry_at: datetime | None = Field(
        default=None,
        description=(
            "When an entry by an agent or a human was last filed into the case. "
            "Service entries (`created`, `status_changed`, `section_changed`, "
            "`assignee_changed`, `link_added`, `link_removed`) do not count: "
            "`link_added` is filed into both cases when a link is made from the other "
            "side, and a task nobody touched would look alive. Null while the case has "
            "no such entry — a freshly created task holds only `created`. This is not "
            "`updated_at`: that one moves when the card changes"
        ),
    )


class PackageParentRead(LinkTaskRead):
    """Родитель в карточке ребёнка: как у любой связи, плюс его цель (`CONCEPT.md`, 4.2).

    Цель нужна затем, чтобы агент, взявший задачу из программы, видел, чему она служит, без
    второго вызова. Только у прямого родителя и не длиннее потолка
    (`app/domain/tasks.py`, `PARENT_GOAL_LIMIT`); детям и другим связям цель не едет.
    """

    goal: str = Field(
        examples=["Агент одним запросом находит все задачи программы"],
        description=(
            f"The parent's `goal` section, cut at {PARENT_GOAL_LIMIT} characters; empty "
            "if the parent has none. The whole text is `get_task` of the parent"
        ),
    )
    goal_truncated: bool = Field(
        description="`true` when `goal` was cut at the limit and the parent's text is longer"
    )


class StateTransitionRead(BaseModel):
    """Последний переход статуса: когда, кто и почему (TRK-579)."""

    model_config = ConfigDict(from_attributes=True)

    no: int = Field(description="Number of the `status_changed` entry")
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    at: str = Field(examples=["2026-10-06T11:59Z"], description="UTC, to the minute")
    by: str = Field(description="Signature of the author")
    reason: str | None = Field(
        description=f"Reason of the move, cut at {REASON_LIMIT} characters; `null` if none"
    )


class StateSummaryRead(BaseModel):
    """Части последней сводки, нужные для входа: следующий шаг, мешающее, `unmeasured`."""

    model_config = ConfigDict(from_attributes=True)

    no: int
    at: str = Field(examples=["2026-10-06T11:59Z"], description="UTC, to the minute")
    next_step: str = Field(description=f"Cut at {REASON_LIMIT} characters")
    blockers: str = Field(description=f"Cut at {REASON_LIMIT} characters")
    unmeasured: str | None = Field(
        description=(
            f"Cut at {UNMEASURED_LIMIT} characters; `null` unless the summary closed the task"
        )
    )


class StateQuestionRead(BaseModel):
    """Открытый вопрос: кого спросили, мешает ли он работе и в каком обсуждении."""

    model_config = ConfigDict(from_attributes=True)

    no: int = Field(description="Number in the case of the discussion, or of the task if none")
    to: list[str] = Field(description="Addressees")
    blocking: bool
    title: str
    discussion: str | None = Field(
        examples=["TRK~7"],
        description=(
            "Address of the discussion the question is in; `null` for an earlier question "
            "of the task's own case"
        ),
    )


class StateNoteRead(BaseModel):
    """Открытое замечание или предупреждение: номер записи, автор, заголовок."""

    model_config = ConfigDict(from_attributes=True)

    no: int
    by: str
    title: str


class TaskStateRead(BaseModel):
    """Состояние задачи на момент чтения (`CONCEPT.md`, 4.2; TRK-579).

    Никто не пишет и ничего не хранится: блок считается из дела и связей при каждом
    чтении, поэтому не устаревает. Он так же информативен, как то, что агенты уже пишут:
    причина перехода, `next_step`, заголовки записей.
    """

    model_config = ConfigDict(from_attributes=True)

    status: TaskStatus
    last_transition: StateTransitionRead | None
    last_summary: StateSummaryRead | None
    after_summary: int | None = Field(
        description="Summary the entries below follow; `null` without one"
    )
    recent: list[str] = Field(
        description=(
            f"Up to {RECENT_LIMIT} latest entries of agents and humans after the summary "
            "(all of them without one), in order: `#no type author time: title`"
        )
    )
    recent_total: int = Field(description="How many such entries there are in all")
    questions: list[StateQuestionRead] = Field(description="Open questions")
    remarks: list[StateNoteRead] = Field(description="Open remarks")
    warning: StateNoteRead | None = Field(description="Open warning, if the task has one")
    blockers: list[str] = Field(description="Keys of open `blocked_by` tasks")
    children: dict[str, int] = Field(description="Children by status; empty without children")
    children_unclosed: list[str] = Field(description="Keys of children not `done` or `cancelled`")
    decisions_after_card: list[int] = Field(
        description=(
            "Numbers of `decision` entries filed after the last edit of the sections: "
            "the statement may not account for them"
        )
    )
    discussions_after_card: list[str] = Field(
        examples=[["TRK~7#5"]],
        description=(
            "Conclusions and entries of people in the task's discussions filed after the "
            "last edit of the sections, as references `TRK~7#5`: they set the work too, "
            "and the statement may not account for them"
        ),
    )


class TaskBriefCardRead(BaseModel):
    """Шапка задачи в кратком ответе: без разделов, проекта и описания."""

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(examples=["TRK-42"])
    title: str
    status: TaskStatus
    assignee: str | None
    priority: TaskPriority
    area: str | None = Field(description="Address of the area, or `null`")
    version: int
    updated_at: datetime


class TaskBriefRead(BaseModel):
    """Краткий ответ чтения задачи, `brief=true` (`CONCEPT.md`, 4.2; TRK-579).

    Шапка, родитель без цели, признаки, `state` и переходы: 200–500 токенов вместо
    2–8 тысяч. Разделов, связей, описи, карточки проекта и сводки целиком здесь нет:
    чтобы взять задачу в работу, читают полный ответ.
    """

    state: TaskStateRead
    task: TaskBriefCardRead
    parent: LinkTaskRead | None
    features: TaskFeaturesRead
    transitions: list[TaskStatus]


class TaskPackageRead(BaseModel):
    """Пакет преемника (`CONCEPT.md`, 4.2).

    Всё, что нужно агенту с чистым контекстом, одним вызовом. Полно хранится, по
    оглавлению читается: карточка, связи, признаки, последняя сводка и открытые вопросы
    приходят целиком, остальные записи — строками описи, а их тела запрашиваются
    точечно.
    """

    state: TaskStateRead = Field(
        description="Where the task stands now, computed on read; first in the answer"
    )
    task: TaskRead
    parent: PackageParentRead | None = Field(
        default=None,
        description=(
            "The parent of this task: key, title, status and its goal; `null` for a "
            "top-level task. A task has at most one parent. Set with the same `link` call "
            "as any other link, but shown here and not in `links`"
        ),
    )
    children: list[LinkTaskRead] = Field(
        description=(
            "Children of this task: key, title and status of each, in the order they were "
            "linked; empty if none. Set with `link`, shown here and not in `links`"
        )
    )
    links: list[TaskLinkRead] = Field(
        description=(
            "Other links: `blocks`, `blocked_by`, `relates`, each named from this task's "
            "point of view, with the status of the task on the other side. Parent and "
            "children are not here: they are the `parent` and `children` fields"
        )
    )
    decisions: list[CitedDecisionRead] = Field(
        description=(
            "Project decisions the task relies on, in the order of its `decisions` field, "
            "each with its status computed on read and, once superseded, its successor. "
            "The project's other decisions are part of the project read"
        )
    )
    features: TaskFeaturesRead
    summary: SummaryEntryRead | None = Field(
        default=None,
        description=(
            "The latest summary in full: what was done, what is left, what is in the "
            "way, what is next. Null until the case has one"
        ),
    )
    questions: list[TaskQuestionRead] = Field(
        description="Every question of the task's case with no answer yet, in full"
    )
    remarks: list[RemarkEntryRead] = Field(
        description="Every remark with no resolution yet, in full"
    )
    discussions: list[TaskDiscussionRead] = Field(
        description=(
            "Discussions the task is attached to, open and closed, by address: whose move "
            "it is, open questions and the latest conclusion in full"
        )
    )
    transitions: list[TaskStatus] = Field(
        examples=[[TaskStatus.OPEN, TaskStatus.CANCELLED]],
        description=(
            "Targets allowed by the transition table from the current status. Transition "
            "validations (sections, summary, verdicts, blockers) are checked on the move"
        ),
    )
    index: list[EntryHeadingRead] = Field(
        description="Case index: heading of every entry, in order; bodies are read separately"
    )


class TaskCreate(BaseModel):
    """Создание задачи. Статуса нет: новая задача рождается в `backlog`.

    Ключа тоже нет — его выдаёт счётчик проекта. Разделы можно оставить пустыми и
    дописать в `backlog`; перед `open` они обязаны быть заполнены.
    """

    model_config = ConfigDict(extra="forbid")

    project: str = Field(examples=["TRK"], description="Project key; matching ignores case")
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH, examples=[_TITLE_EXAMPLE])
    description: str = Field(
        min_length=1, max_length=MAX_TEXT_LENGTH, examples=[_DESCRIPTION_EXAMPLE]
    )
    goal: str = Field(default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    context: str = Field(default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    constraints: str = Field(
        default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION
    )
    output: str = Field(default="", max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    checks: list[str] = Field(
        default_factory=list,
        max_length=MAX_CHECKS,
        examples=[_CHECKS_EXAMPLE],
        description=_CHECKS_DESCRIPTION,
    )
    assignee: str | None = Field(
        default=None,
        max_length=MAX_ASSIGNEE_LENGTH,
        examples=["release_bot"],
        description=_ASSIGNEE_DESCRIPTION,
    )
    priority: TaskPriority = Field(default=TaskPriority.NORMAL)
    area: str | None = Field(
        default=None,
        examples=["TRK/promotion"],
        description=(
            f"{_AREA_DESCRIPTION}. Required: without it `422 area_required`, with the "
            "project's areas in `details.areas`"
        ),
    )
    # Строка, а не `datetime`: форму момента разбирает домен, как и у MCP, и отказ на
    # время без пояса один на оба канала — `task_fields_invalid`, а не `validation_error`.
    not_before: str | None = Field(
        default=None,
        examples=[_NOT_BEFORE_EXAMPLE],
        description=_NOT_BEFORE_DESCRIPTION,
        json_schema_extra={"format": "date-time"},
    )
    decisions: list[str] = Field(
        default_factory=list,
        max_length=MAX_DECISIONS,
        examples=[["TRK#15"]],
        description=_DECISIONS_DESCRIPTION,
    )


class CheckUpdate(BaseModel):
    """Правка одной проверки: её номер и новый текст.

    Заведена затем, что список правился только целиком: чтобы поменять третью строку из
    восьми, приходилось переслать все восемь, и опечатка в неизменённых семи проходила
    молча. Пересылка списка осталась и лишней не стала — она единственный способ
    изменить **состав**: добавить проверку, снять или переставить.
    """

    model_config = ConfigDict(extra="forbid")

    no: int = Field(
        ge=FIRST_CHECK_NUMBER,
        examples=[3],
        description="Position in the current `checks` list, numbered from 1",
    )
    text: str = Field(
        min_length=1,
        max_length=MAX_CHECK_LENGTH,
        examples=["`docker compose run --rm test`: the whole suite is green"],
        description="New wording of that check; the rest of the list stays byte for byte",
    )


class TaskUpdate(BaseModel):
    """Частичное обновление: применяется только переданное.

    `assignee` объявлен как `str | None`: `null` осмыслен и снимает исполнителя. У
    остальных полей `null` смысла не имеет, и схема его не пропустит. Статуса здесь нет
    — он меняется переходом; ключа нет — он меняется только переносом (`move`). Лишнее
    поле схема отвергает, а не игнорирует: клиент должен узнать, что изменения не
    произошло, из ответа.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(min_length=1, max_length=MAX_TITLE_LENGTH, examples=[_TITLE_EXAMPLE])
    description: str = unset_field(
        min_length=1, max_length=MAX_TEXT_LENGTH, examples=[_DESCRIPTION_EXAMPLE]
    )
    goal: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    context: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    constraints: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    output: str = unset_field(max_length=MAX_TEXT_LENGTH, description=_SECTION_DESCRIPTION)
    checks: list[str] = unset_field(
        max_length=MAX_CHECKS,
        examples=[_CHECKS_EXAMPLE],
        description=(
            f"{_CHECKS_DESCRIPTION}. Replaces the whole list: use it to change the **set** "
            "of checks — add one, drop one, reorder. To reword one check in place send "
            "`check` instead"
        ),
    )
    check: CheckUpdate = unset_field(
        description=(
            "Rewords one check in place, leaving the rest of the list byte for byte. The "
            "main way to edit a check: rewording is what happens in practice, and sending "
            "the whole list back for it lets a typo into the lines nobody meant to touch. "
            "Not accepted together with `checks`: the two would answer the same question "
            "differently"
        ),
    )
    assignee: str | None = unset_field(
        max_length=MAX_ASSIGNEE_LENGTH,
        examples=["release_bot"],
        description=f"{_ASSIGNEE_DESCRIPTION}. Pass null to unassign",
    )
    priority: TaskPriority = unset_field(examples=[TaskPriority.HIGH])
    area: str | None = unset_field(
        examples=["TRK/promotion"],
        description=(
            f"{_AREA_DESCRIPTION}. Null is refused with `422 area_required`: an area can be "
            "changed, not taken off"
        ),
    )
    not_before: str | None = unset_field(
        examples=[_NOT_BEFORE_EXAMPLE],
        description=f"{_NOT_BEFORE_DESCRIPTION}. Pass null to clear the moment",
        json_schema_extra={"format": "date-time"},
    )
    decisions: list[str] = unset_field(
        max_length=MAX_DECISIONS,
        examples=[["TRK#15"]],
        description=(
            f"{_DECISIONS_DESCRIPTION}. Replaces the whole list in any status but `done` and "
            "`cancelled`; a reference already in it stays after its decision is superseded"
        ),
    )
    version: int | None = Field(
        default=None,
        ge=1,
        examples=[3],
        description=(
            "Version the client last saw. Sent back it turns a lost update into a "
            "`version_conflict` instead of a silent overwrite; omit it to skip the check"
        ),
    )


class TaskClosingVerdict(BaseModel):
    """Исход одной обзорной проверки с доказательством."""

    model_config = ConfigDict(extra="forbid")

    check_no: int = Field(
        ge=FIRST_CHECK_NUMBER,
        examples=[3],
        description="Position in the task `checks` list, numbered from 1",
    )
    outcome: VerdictOutcome = Field(examples=[VerdictOutcome.PASSED])
    evidence: str = Field(
        default="",
        max_length=MAX_ENTRY_BODY_LENGTH,
        examples=["docker compose run --rm test: 214 passed"],
        description=(
            "Proof of the outcome; it becomes the body of the verdict entry. Required with "
            "`partial` and `unverifiable`: it names the missing part or why the check "
            "cannot run as written"
        ),
    )


class ClosingSummaryPayload(SummaryPartsPayload):
    """Закрывающая сводка: те же четыре части и обязательный `unmeasured`.

    Третья модель одной сводки, и каждая отвечает своей роли: `SummaryPartsPayload` —
    что подшивают посреди работы, `SummaryPayload` — что читают, эта — чем закрывают.
    Общей быть они не могут: у чтения часть необязательна (дела, закрытые до её
    появления), у создания её нет вовсе, у закрытия она обязательна. Схема, обещающая
    клиенту необязательность там, где домен требует, отправила бы его узнавать правила
    из `422` вместо контракта, — а расхождение границ двух входов трекер уже проходил
    (TRK-76).
    """

    unmeasured: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Прод-команда экрана не мерилась ни одной проверкой: гонял только дев-путь"],
        description=(
            "Which part of the goal no review check measured, and which risk the author "
            "considers theoretical. Required when closing: a verdict answers its check, "
            "not the goal, and only the author knows the gap"
        ),
    )


class TaskClosing(BaseModel):
    """Чем закрывают задачу: записи, вердикты и финальная сводка одного вызова."""

    model_config = ConfigDict(extra="forbid")

    summary: ClosingSummaryPayload = Field(
        description=(
            "The closing summary. Filed last, after the entries and the verdicts, so "
            "that it speaks of their outcome"
        )
    )
    verdicts: list[TaskClosingVerdict] = Field(
        default_factory=list,
        examples=[[]],
        description=(
            "Verdicts filed by this call. May be empty: verdicts filed earlier during "
            "the work count as well, and the transition checks the case, not the request"
        ),
    )
    entries: list[ClosingEntryCreate] = Field(
        default_factory=list,
        examples=[[]],
        description=(
            "Entries filed before the verdicts, usually an `artifact` pointing at the result"
        ),
    )
    version: int | None = Field(
        default=None,
        ge=1,
        examples=[3],
        description="Version the client last saw; omit it to skip the check",
    )


class TaskTransition(BaseModel):
    """Перевод статуса по таблице переходов."""

    model_config = ConfigDict(extra="forbid")

    to: TaskStatus = Field(examples=[TaskStatus.OPEN], description="Target status")
    reason: str | None = Field(
        default=None,
        max_length=MAX_TEXT_LENGTH,
        examples=["Нужны уточнения по разделу context"],
        description=(
            "Why the task moves. Required for any step back along the chain and for "
            "`cancelled`; optional otherwise. Recorded in the `status_changed` entry"
        ),
    )
    version: int | None = Field(
        default=None,
        ge=1,
        examples=[3],
        description="Version the client last saw; omit it to skip the check",
    )


class TaskMove(BaseModel):
    """Перенос задачи в другой проект (`CONCEPT.md`, 3.3)."""

    model_config = ConfigDict(extra="forbid")

    project: str = Field(
        min_length=1,
        examples=["TRK"],
        description="Key of the project the task moves to, case-insensitive",
    )
    reason: str = Field(
        max_length=MAX_TEXT_LENGTH,
        examples=["Репозиторий один, задачи интерфейса ведутся в TRK"],
        description=(
            "Why the task moves; a blank one answers `422 task_move_reason_required`. "
            "Filed in the `moved` entry"
        ),
    )
    area: str | None = Field(
        default=None,
        examples=["TRK/promotion"],
        description=(
            "Address `PROJECT/key` of an area of the target project; required: without it "
            "`422 area_required`, with the target project's areas in `details.areas`. "
            "Replaces the old area, which stays in the old project"
        ),
    )
    version: int | None = Field(
        default=None,
        ge=1,
        examples=[3],
        description="Version the client last saw; omit it to skip the check",
    )
