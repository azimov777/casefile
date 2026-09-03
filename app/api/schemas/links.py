"""Схемы связей между задачами.

Наружу связь всегда показывается **со стороны той задачи, у которой её спрашивают**:
одна и та же строка приходит в карточке `A` как `blocks TRK-2`, а в карточке `B` — как
`blocked_by TRK-1`. Поэтому в ответе нет ни «источника», ни «цели»: у стороны есть
только вид связи и задача на другом конце.

Задача на другом конце отдаётся не целиком, а тремя полями: ключ, название и статус.
Статус здесь обязателен по концепции (`CONCEPT.md`, 4.2) — по нему видно, открыт ли
блокер, — а карточка целиком превратила бы чтение одной задачи в чтение всех соседних.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.domain.links import LinkKind
from app.domain.tasks import TaskStatus

_KIND_DESCRIPTION = (
    "What this task is to the other one: `parent`, `child`, `blocks`, `blocked_by` or "
    "`relates`. The same link shows up on the other side under the opposite kind"
)
_OTHER_DESCRIPTION = "Key of the task on the other side; matching ignores case"


class LinkTaskRead(BaseModel):
    """Задача на другой стороне связи: ключ, название и статус."""

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(examples=["TRK-7"])
    title: str = Field(examples=["Выдать номера очередям"])
    status: TaskStatus = Field(
        examples=[TaskStatus.OPEN],
        description="Status of the other task; `blocked` is computed from exactly this",
    )


class TaskLinkRead(BaseModel):
    """Связь со стороны одной задачи."""

    model_config = ConfigDict(from_attributes=True)

    kind: LinkKind = Field(examples=[LinkKind.BLOCKED_BY], description=_KIND_DESCRIPTION)
    other: LinkTaskRead
    author: AuthorRead
    created_at: datetime


class LinkCreate(BaseModel):
    """Постановка связи. Вид называет роль **этой** задачи, а не той, что в `other`."""

    model_config = ConfigDict(extra="forbid")

    kind: LinkKind = Field(examples=[LinkKind.BLOCKED_BY], description=_KIND_DESCRIPTION)
    other: str = Field(examples=["TRK-7"], description=_OTHER_DESCRIPTION)
