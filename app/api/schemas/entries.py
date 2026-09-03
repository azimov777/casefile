"""Схемы записей дела.

`payload` — одно из двух мест контракта со свободной формой, разрешённых соглашениями
(второе — `details` ошибки): его форма зависит от типа записи. Служебные формы описаны
в `app/db/models/entry.py`; типизацию по каждому типу отдельной моделью и размеченное
объединение в OpenAPI делает задача 23 вместе с записями агента — до неё поле остаётся
исключением, названным в `tests/test_openapi.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.api.schemas.authors import AuthorRead
from app.db.models.entry import Entry
from app.domain.case import EntryType


class EntryHeadingRead(BaseModel):
    """Строка описи дела: то, что видно о записи, не читая её тела."""

    model_config = ConfigDict(from_attributes=True)

    no: int = Field(examples=[12], description="Number inside the task, from 1; `TRK-42#12`")
    type: EntryType = Field(examples=[EntryType.STATUS_CHANGED])
    author: AuthorRead
    created_at: datetime
    title: str = Field(examples=["Status changed: backlog -> open"])


class EntryRead(BaseModel):
    """Запись дела целиком."""

    id: uuid.UUID
    seq: int = Field(examples=[1024], description="Tracker-wide monotonic number; journal cursor")
    no: int = Field(examples=[12], description="Number inside the task, from 1; `TRK-42#12`")
    task_key: str = Field(examples=["TRK-42"])
    type: EntryType = Field(examples=[EntryType.STATUS_CHANGED])
    author: AuthorRead
    title: str = Field(examples=["Status changed: backlog -> open"])
    body: str = Field(
        examples=[""],
        description="Markdown; empty for service entries, whose content is the payload",
    )
    payload: dict[str, JsonValue] = Field(
        default_factory=dict,
        description=(
            "Structured fields by entry type. `status_changed`: from, to, reason; "
            "`section_changed`: field, before, after; `assignee_changed`: before, after; "
            "`created`: empty"
        ),
    )
    refs: list[str] = Field(
        default_factory=list,
        examples=[["TRK-42#3", "TRK-7"]],
        description="References to entries `KEY-N#M`, tasks `KEY-N` and URLs",
    )
    created_at: datetime

    @classmethod
    def of(cls, entry: Entry, *, task_key: str) -> EntryRead:
        """Ключ задачи приходит от вызывающего: у записи связи с задачей нет, только `task_id`."""
        return cls(
            id=entry.id,
            seq=entry.seq,
            no=entry.no,
            task_key=task_key,
            type=entry.type,
            author=AuthorRead.model_validate(entry.author),
            title=entry.title,
            body=entry.body,
            payload=entry.payload,
            refs=list(entry.refs),
            created_at=entry.created_at,
        )
