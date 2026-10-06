"""Схемы решений проекта: решение со статусом в пакете задачи и в чтении проекта.

Решение проекта — запись `decision` дела проекта (`CONCEPT.md`, 3.2), и её саму отдаёт
чтение дела (`EntryRead`). Здесь то, чего у записи нет: статус, посчитанный при чтении,
преемник и число задач, которые на решение ссылаются. В ленту это не едет: статус меняется
без единой записи в деле решения, и кадр ленты с ним устаревал бы.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.authors import AuthorRead
from app.domain.decisions import DecisionStatus

_REF_DESCRIPTION = "Address of the `decision` entry in the project's case"
_STATUS_DESCRIPTION = (
    "Computed on read: `superseded` once a later decision of the project names this one in "
    "`supersedes`, `in_force` until then"
)


class DecisionRefRead(BaseModel):
    """Решение проекта, названное ссылкой: адрес, заголовок и статус."""

    ref: str = Field(examples=["TRK#15"], description=_REF_DESCRIPTION)
    title: str = Field(examples=["Сервис не строим до сигнала спроса"])
    status: DecisionStatus = Field(
        examples=[DecisionStatus.IN_FORCE], description=_STATUS_DESCRIPTION
    )


class CitedDecisionRead(DecisionRefRead):
    """Решение проекта, на которое ссылается задача, и его преемник (`CONCEPT.md`, 4.2).

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
    сворачивает остальные (`CONCEPT.md`, 5.1). Тело решения — в записи дела
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
