"""Формы записи дела: запись целиком, строка описи с фактами, короткий ответ подшивки.

Отдают их инструменты дела, `get_task` (сводка, вопросы, замечания, опись), `close_task`
(записи закрытия) и `wait_journal`. Почему ответ подшивки короче записи — в шапке
`app/mcp/views.py`.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, JsonValue, SerializerFunctionWrapHandler, model_serializer

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
    MovedFacts,
    NoFacts,
    QuestionFacts,
    ResolutionFacts,
    SectionChangedFacts,
    StatusChangedFacts,
    VerdictFacts,
    WarningFacts,
    read_payload,
)
from app.mcp.enums import (
    AnswerOutcomeSchema,
    DecisionStatusSchema,
    EntryTypeSchema,
    LinkKindSchema,
    RemarkOutcomeSchema,
    TaskFieldSchema,
    TaskStatusSchema,
    VerdictOutcomeSchema,
)
from app.mcp.views import AuthorView, author
from app.services.decisions import Standing


class NoFactsView(BaseModel):
    """No facts: the author writes the entry title."""

    type: Literal[
        EntryType.SUMMARY,
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.REMARK,
        EntryType.ACCEPTANCE,
        EntryType.NOTE,
        EntryType.CREATED,
        EntryType.ARCHIVED,
        EntryType.RESTORED,
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
    """Answer: the question of the same task it closes, how, and what replaced it."""

    type: Literal[EntryType.ANSWER]
    question_no: int | None
    outcome: AnswerOutcomeSchema | None
    replaced_by: int | None


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


class MovedFactsView(BaseModel):
    """Task moved to another project: the key it left and the key it got."""

    type: Literal[EntryType.MOVED]
    from_key: str | None
    to_key: str | None


class WarningFactsView(BaseModel):
    """Warning: numbers of the checks closed `partial` and `unverifiable`."""

    type: Literal[EntryType.WARNING]
    partial: list[int] | None
    unverifiable: list[int] | None


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
    | AttributeFactsView
    | MovedFactsView
    | WarningFactsView,
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
            return AnswerFactsView(
                type=value.type,
                question_no=value.question_no,
                outcome=value.outcome,
                replaced_by=value.replaced_by,
            )
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
        case MovedFacts():
            return MovedFactsView(type=value.type, from_key=value.from_key, to_key=value.to_key)
        case WarningFacts():
            return WarningFactsView(
                type=value.type,
                partial=None if value.partial is None else list(value.partial),
                unverifiable=None if value.unverifiable is None else list(value.unverifiable),
            )
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
        description="Key of the owning task; `null` for an entry of a project's or direction's case"
    )
    project_key: str | None = Field(
        description=(
            "Key of the owning project for an entry of a project's case (`TRK#7`); `null` otherwise"
        )
    )
    direction: str | None = Field(
        default=None,
        description="Address of the owning direction (`TRK/promotion#3`); `null` otherwise",
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
    status: DecisionStatusSchema | None = Field(
        default=None,
        description=(
            "Present only on a `decision` or `finding` of a project's case read by "
            "`read_project_entries`: `superseded` once a later entry of the same type in "
            "the case names this one in `supersedes`, `in_force` until then. Absent on "
            "other types, in a task's or a direction's case and in `wait_journal`"
        ),
    )
    superseded_by: int | None = Field(
        default=None,
        description=(
            "Present together with `status`: number of the entry in the same case that "
            "superseded this one, the direct successor rather than the end of a chain; "
            "`null` while in force"
        ),
    )

    # Статус записи есть только у решений и заметок дела проекта; у остальных записей два
    # ключа были бы `null` в каждой строке `read_entries`, `get_task`, `wait_journal`, то
    # есть шумом в контексте агента (TRK-665). Ключи уходят вместе, по `status`: у
    # действующей записи `superseded_by: null` значим. Схему сериализатор не портит
    # (см. `FoundTaskView`): оба поля необязательны, и `outputSchema` это показывает.
    @model_serializer(mode="wrap")
    def _standing_only_where_it_has_meaning(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Убирает `status` и `superseded_by` из ответа, когда статуса у записи нет."""
        dumped: dict[str, Any] = handler(self)
        if self.status is None:
            dumped.pop("status", None)
            dumped.pop("superseded_by", None)
        return dumped


def entry(
    value: Entry,
    *,
    task_key: str | None = None,
    project_key: str | None = None,
    direction: str | None = None,
    standing: Standing | None = None,
) -> EntryView:
    """Запись дела целиком. Ключ владельца приходит извне: у записи только `task_id`,
    `project_id` или `direction_id`. Передаётся ровно один — как и в REST (`entry_read`).
    Нагрузка читается тем же правилом, что и в REST, — `read_payload`: ответ, подшитый до
    исходов, приходит с `outcome: answered`, а не без ключа. `standing` — статус решения
    или заметки, посчитанный чтением дела проекта; без него `status` и `superseded_by`
    в ответе MCP нет вовсе (в REST — `null`)."""
    owners = [key for key in (task_key, project_key, direction) if key is not None]
    assert len(owners) == 1, "entry owner is exactly one key"
    return EntryView(
        id=str(value.id),
        seq=value.seq,
        no=value.no,
        task_key=task_key,
        project_key=project_key,
        direction=direction,
        type=value.type,
        author=author(value.author),
        title=value.title,
        body=value.body,
        payload=read_payload(value.type, value.payload),
        refs=list(value.refs),
        created_at=value.created_at,
        action_id=None if value.action_id is None else str(value.action_id),
        status=None if standing is None else standing.status,
        superseded_by=None if standing is None else standing.superseded_by,
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


# Ответ `add_project_entry`: то же, что у записи задачи, но адрес — ключ проекта или адрес
# направления (`CONCEPT.md`, 3.7), и заголовка нет вовсе: у всех типов записи проекта его
# присылает сам агент (`app/domain/case.py`, `PROJECT_ENTRY_TYPES`), и поле всегда было бы
# `null`. Поле адреса осталось `project_key` — форма ответа создающего инструмента живёт
# сутки в ключах идемпотентности, и переименование уронило бы повтор вчерашнего вызова.
class AppendedProjectEntryView(BaseModel):
    """A filed project or direction case entry, by its address rather than its content;
    the entry in full is returned by `read_project_entries`.
    """

    no: int = Field(
        description="Entry number in the case; with the key it forms `TRK#7` or `TRK/promotion#3`"
    )
    seq: int = Field(description="Journal sequence number, usable as `after` of `wait_journal`")
    project_key: str = Field(description="Project key or direction address of the case")
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
