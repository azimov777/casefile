"""Схемы чеклиста задачи.

Позиция пункта наружу не отдаётся и клиентом не задаётся. Это внутреннее число
разреженной шкалы (`app/domain/checklists.py`): клиенту нужен порядок, а не координата,
и место при перемещении задаётся соседом. Отдать позицию значило бы позвать клиента
считать её самому — и однажды получить два пункта на одном месте.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.db.models.checklist import ChecklistItem
from app.domain.checklists import MAX_CHECKLIST_ITEMS, MAX_CHECKLIST_TEXT_LENGTH

TextField = Field(
    min_length=1,
    max_length=MAX_CHECKLIST_TEXT_LENGTH,
    examples=["Прогнать тесты на реальной базе"],
    description=(
        f"Single line, at most {MAX_CHECKLIST_TEXT_LENGTH} characters. A task needing a "
        f"process of its own is a subtask, not a checklist item; at most "
        f"{MAX_CHECKLIST_ITEMS} items per issue"
    ),
)
DeadlineDescription = "ISO 8601 with a UTC offset; a value without a timezone is rejected"
AssigneeDescription = "Actor key, or null when nobody is responsible for this item"


class ChecklistItemRead(BaseModel):
    """Пункт чеклиста в ответе."""

    id: uuid.UUID
    issue: str = Field(examples=["TRK-123"], description="Key of the owning issue")
    text: str = TextField
    is_done: bool = Field(description="Whether the item is checked")
    checked_by: str | None = Field(
        default=None,
        examples=["alice"],
        description="Key of the actor who checked it; null while the item is open",
    )
    checked_at: datetime | None = Field(
        default=None,
        description="Set together with `checked_by` and cleared together with it",
    )
    assignee: str | None = Field(default=None, examples=["alice"], description=AssigneeDescription)
    deadline: datetime | None = Field(default=None, description=DeadlineDescription)

    @classmethod
    def of(cls, item: ChecklistItem, *, issue_key: str) -> ChecklistItemRead:
        return cls(
            id=item.id,
            issue=issue_key,
            text=item.text,
            is_done=item.is_done,
            checked_by=None if item.checked_by is None else item.checked_by.key,
            checked_at=item.checked_at,
            assignee=None if item.assignee is None else item.assignee.key,
            deadline=item.deadline,
        )


class ChecklistItemCreate(BaseModel):
    """Новый пункт. Встаёт в конец списка: место выбирают перемещением, а не вставкой."""

    model_config = ConfigDict(extra="forbid")

    text: str = TextField
    assignee: str | None = Field(default=None, examples=["alice"], description=AssigneeDescription)
    deadline: datetime | None = Field(default=None, description=DeadlineDescription)


class ChecklistItemUpdate(BaseModel):
    """Частичное обновление пункта: применяются только переданные поля.

    Отметки о выполнении здесь нет намеренно — она ставится своим маршрутом, у которого
    своё событие (`checklist.item_checked`). Смешать их значило бы заставить автоматику
    разбирать нагрузку каждой правки текста ради вопроса «пункт закрыли?».
    """

    model_config = ConfigDict(extra="forbid")

    text: str = unset_field(min_length=1, max_length=MAX_CHECKLIST_TEXT_LENGTH)
    assignee: str | None = unset_field(
        description=f"{AssigneeDescription}. Pass null to unassign the item"
    )
    deadline: datetime | None = unset_field(
        description=f"{DeadlineDescription}. Pass null to drop the deadline"
    )


class ChecklistItemCheck(BaseModel):
    """Отметка о выполнении. `false` снимает её вместе с тем, кто и когда её поставил."""

    model_config = ConfigDict(extra="forbid")

    is_done: bool = Field(examples=[True], description="True checks the item, false unchecks it")


class ChecklistItemMove(BaseModel):
    """Перемещение пункта: место задаётся соседом, а не индексом.

    `after` — идентификатор пункта, после которого встать; `null` означает «в начало
    списка». Индекс разошёлся бы с состоянием списка, который тем временем изменил
    кто-то ещё, а позиция — внутреннее число, которого клиент не видит.
    """

    model_config = ConfigDict(extra="forbid")

    after: uuid.UUID | None = Field(
        default=None,
        description="Item to place this one after; null moves it to the top of the list",
    )
