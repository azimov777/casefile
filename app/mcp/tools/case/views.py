"""Формы записи дела: запись целиком, строка описи с фактами, короткий ответ подшивки.

Отдают их инструменты дела, `get_task` (сводка, вопросы, замечания, опись), `close_task`
(записи закрытия) и `wait_journal`. Почему ответ подшивки короче записи — в шапке
`app/mcp/views.py`.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue

from app.db.models.entry import Entry
from app.domain.case import (
    TITLED_ENTRY_TYPES,
    AnswerFacts,
    AssigneeChangedFacts,
    AttributeFacts,
    EntryFacts,
    EntryHeading,
    EntryType,
    FieldChangedFacts,
    LinkFacts,
    NoFacts,
    QuestionFacts,
    ResolutionFacts,
    SectionChangedFacts,
    StatusChangedFacts,
    VerdictFacts,
)
from app.mcp.enums import (
    EntryTypeSchema,
    LinkKindSchema,
    RemarkOutcomeSchema,
    TaskFieldSchema,
    TaskStatusSchema,
    VerdictOutcomeSchema,
)
from app.mcp.views import AuthorView, author


class NoFactsView(BaseModel):
    """No facts: the author writes the entry title."""

    type: Literal[
        EntryType.SUMMARY,
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.REMARK,
        EntryType.NOTE,
        EntryType.CREATED,
    ]


class StatusChangedFactsView(BaseModel):
    """Status change: both ends and whether a reason was given."""

    type: Literal[EntryType.STATUS_CHANGED]
    from_status: TaskStatusSchema | None
    to_status: TaskStatusSchema | None
    has_reason: bool | None


class SectionChangedFactsView(BaseModel):
    """Section change: which field, and which check for a single-check edit."""

    type: Literal[EntryType.SECTION_CHANGED]
    field: TaskFieldSchema | None
    check_no: int | None


class FieldChangedFactsView(BaseModel):
    """Change of a non-section field: which one."""

    type: Literal[EntryType.FIELD_CHANGED]
    field: TaskFieldSchema | None


class AssigneeChangedFactsView(BaseModel):
    """Assignee change: both names."""

    type: Literal[EntryType.ASSIGNEE_CHANGED]
    assignee_from: str | None
    assignee_to: str | None


class LinkFactsView(BaseModel):
    """Link added or removed: its kind and the other side."""

    type: Literal[EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
    link_kind: LinkKindSchema | None
    other_key: str | None


class QuestionFactsView(BaseModel):
    """Question: addressees and whether it blocks the work."""

    type: Literal[EntryType.QUESTION]
    addressees: list[str] | None
    blocking: bool | None


class AnswerFactsView(BaseModel):
    """Answer: the question of the same task it answers."""

    type: Literal[EntryType.ANSWER]
    question_no: int | None


class VerdictFactsView(BaseModel):
    """Verdict: which check, its outcome and whether the check was rewritten since."""

    type: Literal[EntryType.VERDICT]
    check_no: int | None
    outcome: VerdictOutcomeSchema | None
    outdated: bool | None


class ResolutionFactsView(BaseModel):
    """Resolution: which remark, its outcome and the continuation task."""

    type: Literal[EntryType.RESOLUTION]
    remark_no: int | None
    outcome: RemarkOutcomeSchema | None
    continuation_key: str | None


class AttributeFactsView(BaseModel):
    """Project attribute created, changed or removed: its name."""

    type: Literal[
        EntryType.ATTRIBUTE_CREATED, EntryType.ATTRIBUTE_CHANGED, EntryType.ATTRIBUTE_REMOVED
    ]
    name: str | None


type FactsView = Annotated[
    NoFactsView
    | StatusChangedFactsView
    | SectionChangedFactsView
    | FieldChangedFactsView
    | AssigneeChangedFactsView
    | LinkFactsView
    | QuestionFactsView
    | AnswerFactsView
    | VerdictFactsView
    | ResolutionFactsView
    | AttributeFactsView,
    Field(discriminator="type"),
]
"""Факты записи: те же формы и те же поля в том же порядке, что в схеме REST."""


def facts(value: EntryFacts) -> FactsView:
    """Факты записи для описи: те же формы и поля, что в схеме REST.

    Пакет преемника обязан совпадать с ответом REST поле в поле (обзорная проверка
    задачи 03, `tests/test_mcp_tools.py`), поэтому «отдать факты только интерфейсу»
    нельзя: расхождение здесь означало бы два разных описания одного дела. Разметка по
    `type` едет и сюда — по ней агент видит состав полей своей записи в `outputSchema`
    инструмента, до вызова, а не по тому, какие ключи пришли непустыми.

    Разбор — по форме факта, а не по типу записи: форм меньше, чем типов, и
    сопоставление одного с другим живёт в одном месте, в домене (`FACTS_BY_ENTRY_TYPE`).
    """
    match value:
        case NoFacts():
            return NoFactsView(type=value.type)
        case StatusChangedFacts():
            return StatusChangedFactsView(
                type=value.type,
                from_status=value.from_status,
                to_status=value.to_status,
                has_reason=value.has_reason,
            )
        case SectionChangedFacts():
            return SectionChangedFactsView(
                type=value.type, field=value.field, check_no=value.check_no
            )
        case FieldChangedFacts():
            return FieldChangedFactsView(type=value.type, field=value.field)
        case AssigneeChangedFacts():
            return AssigneeChangedFactsView(
                type=value.type,
                assignee_from=value.assignee_from,
                assignee_to=value.assignee_to,
            )
        case LinkFacts():
            return LinkFactsView(
                type=value.type, link_kind=value.link_kind, other_key=value.other_key
            )
        case QuestionFacts():
            return QuestionFactsView(
                type=value.type,
                addressees=None if value.addressees is None else list(value.addressees),
                blocking=value.blocking,
            )
        case AnswerFacts():
            return AnswerFactsView(type=value.type, question_no=value.question_no)
        case VerdictFacts():
            return VerdictFactsView(
                type=value.type,
                check_no=value.check_no,
                outcome=value.outcome,
                outdated=value.outdated,
            )
        case ResolutionFacts():
            return ResolutionFactsView(
                type=value.type,
                remark_no=value.remark_no,
                outcome=value.outcome,
                continuation_key=value.continuation_key,
            )
        case AttributeFacts():
            return AttributeFactsView(type=value.type, name=value.name)
    # Форма фактов, заведённая в домене без представления здесь, — дефект объединения, а
    # не рабочее состояние: молча вернуть `None` значило бы отдать агенту опись без строки.
    raise TypeError(f"форма фактов без представления MCP: {type(value).__name__}")


class HeadingView(BaseModel):
    """Line of the case index: what is known of an entry without its body."""

    no: int
    type: EntryTypeSchema
    author: AuthorView
    created_at: datetime
    title: str
    action_id: str | None = Field(
        default=None,
        description=(
            "Marks the single call that filed this entry: entries of one call share "
            "the same value, entries of another call never do. `null` on entries "
            "filed before this field existed"
        ),
    )
    facts: FactsView


def heading(value: EntryHeading) -> HeadingView:
    """Строка описи дела: то, что видно о записи, не читая её тела."""
    return HeadingView(
        no=value.no,
        type=value.type,
        author=author(value.author),
        created_at=value.created_at,
        title=value.title,
        action_id=None if value.action_id is None else str(value.action_id),
        facts=facts(value.facts),
    )


# Запись дела целиком.
#
# `payload` — единственное поле слоя без объявленной формы, и это то же исключение,
# что и в схеме REST (`docs/notes/api.md`, «`payload` записи дела — исключение из
# типизации, названное по месту»): нагрузка своя у каждого типа записи, и типизирует
# её отдельная задача — сразу в обоих интерфейсах, иначе они разойдутся. `JsonValue`,
# а не `Any`: форма свободна, но значение обязано быть представимо в JSON.
class EntryView(BaseModel):
    """Case entry in full."""

    id: str
    seq: int = Field(description="Journal sequence number, usable as `after` of `wait_journal`")
    no: int
    task_key: str | None = Field(
        description="Key of the owning task; `null` for an entry of a project's case"
    )
    project_key: str | None = Field(
        description=(
            "Key of the owning project for an entry of a project's case (`TRK#7`); "
            "`null` for a task entry"
        )
    )
    type: EntryTypeSchema
    author: AuthorView
    title: str
    body: str
    payload: dict[str, JsonValue]
    refs: list[str]
    created_at: datetime
    action_id: str | None = Field(
        default=None,
        description=(
            "Marks the single call that filed this entry: entries of one call share "
            "the same value, entries of another call never do. `null` on entries "
            "filed before this field existed"
        ),
    )


def entry(
    value: Entry, *, task_key: str | None = None, project_key: str | None = None
) -> EntryView:
    """Запись дела целиком. Ключ владельца приходит извне: у записи только `task_id` или
    `project_id`. Передаётся ровно один — как и в REST (`entry_read`)."""
    assert (task_key is None) != (project_key is None), "entry owner is exactly one key"
    return EntryView(
        id=str(value.id),
        seq=value.seq,
        no=value.no,
        task_key=task_key,
        project_key=project_key,
        type=value.type,
        author=author(value.author),
        title=value.title,
        body=value.body,
        payload=dict(value.payload),
        refs=list(value.refs),
        created_at=value.created_at,
        action_id=None if value.action_id is None else str(value.action_id),
    )


# Ответ подшивающего инструмента: чем запись адресуют, без самой записи.
#
# `title` непуст только там, где заголовок собрал трекер: у сводки, ответа, вердикта и
# резолюции его не принимают вовсе (`app/domain/case.py`, `TITLED_ENTRY_TYPES`). Где
# заголовок прислал агент, здесь стоит `null` — «в описи ровно то, что ты прислал».
class AppendedEntryView(BaseModel):
    """A filed entry, by its address rather than its content; the entry in full is
    returned by `read_entries`.
    """

    no: int = Field(
        description="Entry number in the task's case; with the key it forms `TRK-42#12`"
    )
    seq: int = Field(description="Journal sequence number, usable as `after` of `wait_journal`")
    task_key: str
    author: AuthorView
    title: str | None = Field(
        description=(
            "The title the tracker built, for entry types whose title is not sent "
            "(summary, answer, verdict, resolution, service entries); `null` when the "
            "caller sent the title"
        )
    )
    created_at: datetime


def appended_entry(value: Entry, *, task_key: str) -> AppendedEntryView:
    """Ответ подшивающего инструмента: чем запись адресуют, без самой записи.

    Почему не запись целиком — в шапке `app/mcp/views.py`. Здесь важно, откуда берётся `title`:
    из принадлежности типа к `TITLED_ENTRY_TYPES`, а не из списка типов, переписанного
    по месту. Заголовок, выведенный у нового типа записи, приедет сюда сам.
    """
    return AppendedEntryView(
        no=value.no,
        seq=value.seq,
        task_key=task_key,
        author=author(value.author),
        title=None if value.type in TITLED_ENTRY_TYPES else value.title,
        created_at=value.created_at,
    )


# Ответ `add_project_entry`: то же, что у записи задачи, но адрес — ключ проекта, и
# заголовка нет вовсе: у всех типов записи проекта его присылает сам агент
# (`app/domain/case.py`, `PROJECT_ENTRY_TYPES`), и поле всегда было бы `null`.
class AppendedProjectEntryView(BaseModel):
    """A filed project case entry, by its address rather than its content; the entry in
    full is returned by `read_project_entries`.
    """

    no: int = Field(description="Entry number in the project's case; with the key it forms `TRK#7`")
    seq: int = Field(description="Journal sequence number, usable as `after` of `wait_journal`")
    project_key: str
    author: AuthorView
    created_at: datetime


def appended_project_entry(value: Entry, *, project_key: str) -> AppendedProjectEntryView:
    """Ответ `add_project_entry`: адрес записи в деле проекта, без самой записи."""
    return AppendedProjectEntryView(
        no=value.no,
        seq=value.seq,
        project_key=project_key,
        author=author(value.author),
        created_at=value.created_at,
    )
