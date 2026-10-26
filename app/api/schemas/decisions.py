"""Схемы решений проекта и области: решение со статусом в пакете задачи и в чтении проекта.

Решение — запись `decision` дела проекта (TRK#88) или дела области (TRK#57,
раздел 5), и её саму отдаёт чтение дела (`EntryRead`). Здесь то, чего у записи нет:
статус, посчитанный при чтении, преемник и число задач, которые на решение ссылаются. В
ленту это не едет: статус меняется без единой записи в деле решения, и кадр ленты с ним
устаревал бы.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import CollectionResponse
from app.domain.case import MAX_ENTRY_BODY_LENGTH
from app.domain.decisions import DecisionStatus, ReviewOutcome, ReviewState

_REF_DESCRIPTION = (
    "Address of the `decision` entry in its project's case (`TRK#15`) or area's case (`TRK/mcp#3`)"
)
_STATUS_DESCRIPTION = (
    "Computed on read: `superseded` once a later decision of the same case names this one "
    "in `supersedes`; `rejected` or `removed` once a person took it out of force with a "
    "`decision_review` entry (no successor); `in_force` otherwise"
)
_REVIEW_STATE_DESCRIPTION = (
    "Computed on read: `confirmed` if a person confirmed the decision with a "
    "`decision_review` entry or signed it, `unconfirmed` otherwise — every decision an agent "
    "filed before a person looked at it"
)
_REVIEW_ENTRY_DESCRIPTION = (
    "Number of the `decision_review` entry that confirmed the decision in the same case; "
    "`null` if it is unconfirmed or was signed by a person (no entry is needed)"
)


class DecisionRefRead(BaseModel):
    """Решение проекта или области, названное ссылкой: адрес, заголовок и статус."""

    ref: str = Field(examples=["TRK#15"], description=_REF_DESCRIPTION)
    title: str = Field(examples=["Сервис не строим до сигнала спроса"])
    status: DecisionStatus = Field(
        examples=[DecisionStatus.IN_FORCE], description=_STATUS_DESCRIPTION
    )


class CitedDecisionRead(DecisionRefRead):
    """Решение проекта или области, на которое ссылается задача, и его преемник
    (TRK#156).

    Та же форма, что у `get_task` в MCP (`CitedDecisionView`): пакет задачи совпадает в
    обоих интерфейсах поле в поле.
    """

    superseded_by: DecisionRefRead | None = Field(
        description=(
            "The later decision that named this one in `supersedes`, with its own status; "
            "`null` while this one is in force"
        )
    )


class ProjectDecisionRead(BaseModel):
    """Решение проекта в чтении проекта: всё, что нужно разделу «Решения» интерфейса.

    Все решения проекта, действующие и заменённые: интерфейс показывает действующие и
    сворачивает остальные (TRK#103). Тело решения — в записи дела
    (`GET /projects/{key}/entries/{no}`), задачи, которые на него ссылаются, — отбором
    `decision:` в поиске.
    """

    no: int = Field(examples=[15], description="Entry number in the project's case")
    ref: str = Field(examples=["TRK#15"], description=_REF_DESCRIPTION)
    title: str = Field(examples=["Сервис не строим до сигнала спроса"])
    author: AuthorRead
    created_at: datetime
    status: DecisionStatus = Field(
        examples=[DecisionStatus.IN_FORCE], description=_STATUS_DESCRIPTION
    )
    review_state: ReviewState = Field(
        examples=[ReviewState.UNCONFIRMED], description=_REVIEW_STATE_DESCRIPTION
    )
    review_entry: int | None = Field(examples=[None], description=_REVIEW_ENTRY_DESCRIPTION)
    supersedes: list[int] = Field(
        examples=[[12]],
        description="Numbers of the earlier decisions of this project that this one superseded",
    )
    superseded_by: int | None = Field(
        examples=[None],
        description="Number of the later decision that superseded this one; `null` while in force",
    )
    tasks: int = Field(
        examples=[3],
        description=(
            "How many tasks name this decision in their `decisions` field, in any status; "
            "they are found by the search condition `decision: TRK#15`"
        ),
    )


class DecisionReview(BaseModel):
    """Проверка решения человеком: исход и причина (TRK-755)."""

    model_config = ConfigDict(extra="forbid")

    outcome: ReviewOutcome = Field(
        examples=[ReviewOutcome.CONFIRMED],
        description=(
            "`confirmed`: the person saw the decision and agrees (a second `confirmed` of a "
            "confirmed decision answers `decision_already_confirmed`); `rejected`: disagrees; "
            "`removed`: out of date. The last two take the decision out of force with no "
            "replacement and bring back nothing it replaced; the entry stays in the case. "
            "Only a decision in force is reviewed (`decision_not_in_force`); only a person "
            "with an account reviews (`403 permission_denied`, `details.reason: "
            "account_required`)"
        ),
    )
    reason: str = Field(
        default="",
        max_length=MAX_ENTRY_BODY_LENGTH,
        examples=["Устарело после перехода на новую схему"],
        description="Why; free text, may be empty. It becomes the body of the review entry",
    )


class DecisionListRead(BaseModel):
    """Решение в списке решений поперёк проектов и областей."""

    ref: str = Field(examples=["TRK/mcp#3"], description=_REF_DESCRIPTION)
    area: str | None = Field(
        examples=["TRK/mcp"],
        description="Address of the area whose case holds the decision; `null` for a project's",
    )
    title: str = Field(examples=["Сервис не строим до сигнала спроса"])
    author: AuthorRead
    created_at: datetime
    status: DecisionStatus = Field(
        examples=[DecisionStatus.IN_FORCE], description=_STATUS_DESCRIPTION
    )
    review_state: ReviewState = Field(
        examples=[ReviewState.UNCONFIRMED], description=_REVIEW_STATE_DESCRIPTION
    )
    review_entry: int | None = Field(examples=[None], description=_REVIEW_ENTRY_DESCRIPTION)
    supersedes: list[str] = Field(
        examples=[["TRK#12"]], description="Addresses of the decisions this one superseded"
    )
    superseded_by: str | None = Field(
        examples=[None],
        description="Address of the decision that superseded this one; `null` while in force",
    )
    refs: list[str] = Field(
        examples=[["TRK-42#3"]],
        description="References of the decision itself — where it came from",
    )
    tasks: int = Field(
        examples=[3], description="How many tasks name this decision in their `decisions` field"
    )


class DecisionListResponse(CollectionResponse[DecisionListRead]):
    """Страница списка решений и число непроверенных действующих."""

    unconfirmed: int = Field(
        examples=[12],
        description=(
            "How many decisions in force are `unconfirmed` in the whole scope of the list "
            "(the named project with its active areas, or every active project): the "
            "filters `status` and `review_state` do not change it. The same number as "
            "`unconfirmed_decisions` of the project card and of `GET /api/v1/bootstrap`"
        ),
    )
