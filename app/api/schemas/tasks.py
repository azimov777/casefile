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
from app.api.schemas.entries import (
    ClosingEntryCreate,
    EntryHeadingRead,
    QuestionEntryRead,
    RemarkEntryRead,
    SummaryEntryRead,
    SummaryPartsPayload,
)
from app.api.schemas.links import LinkTaskRead, TaskLinkRead
from app.domain.case import MAX_ENTRY_BODY_LENGTH, MAX_SUMMARY_PART_LENGTH, VerdictOutcome
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH
from app.domain.tasks import (
    FIRST_CHECK_NUMBER,
    MAX_ASSIGNEE_LENGTH,
    MAX_CHECK_LENGTH,
    MAX_CHECKS,
    MAX_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
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


class TaskRead(BaseModel):
    """Задача в ответе."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str = Field(examples=["TRK-42"], description="Immutable and never reused")
    project: TaskProjectRead
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


class TaskPackageRead(BaseModel):
    """Пакет преемника (`CONCEPT.md`, 4.2).

    Всё, что нужно агенту с чистым контекстом, одним вызовом. Полно хранится, по
    оглавлению читается: карточка, связи, признаки, последняя сводка и открытые вопросы
    приходят целиком, остальные записи — строками описи, а их тела запрашиваются
    точечно.
    """

    task: TaskRead
    parent: LinkTaskRead | None = Field(
        default=None,
        description=(
            "The parent of this task: key, title and status; `null` for a top-level task. "
            "A task has at most one parent. Set with the same `link` call as any other "
            "link, but shown here and not in `links`"
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
    features: TaskFeaturesRead
    summary: SummaryEntryRead | None = Field(
        default=None,
        description=(
            "The latest summary in full: what was done, what is left, what is in the "
            "way, what is next. Null until the case has one"
        ),
    )
    questions: list[QuestionEntryRead] = Field(
        description="Every question with no answer yet, in full"
    )
    remarks: list[RemarkEntryRead] = Field(
        description="Every remark with no resolution yet, in full"
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
    — он меняется переходом; ключа нет — он неизменяем. Лишнее поле схема отвергает, а
    не игнорирует: клиент должен узнать, что изменения не произошло, из ответа.
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
        description="Proof of the outcome; it becomes the body of the verdict entry",
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
