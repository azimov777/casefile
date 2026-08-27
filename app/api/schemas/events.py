"""Схемы истории изменений задачи.

Запись истории отдаётся в том же виде, в каком лежит в базе и в полезной нагрузке
события: поле, «было», «стало». Три формы одних и тех же данных разошлись бы, а
фронтенду и агенту нужна одна.

`before` и `after` объявлены как `JsonValue`, а не `Any`: у них нет одного типа —
у названия это строка, у наблюдателей список ключей, у дедлайна строка ISO 8601, у
кастомного поля что угодно из описанного в реестре. `Any` приехал бы на фронт как
`unknown` и убил бы смысл генерации клиента, `JsonValue` даёт честный union.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, JsonValue

from app.db.models.event import ChangelogEntry
from app.domain.events import EventType


class IssueChangeRead(BaseModel):
    """Одно изменение поля: что было и что стало."""

    field: str = Field(
        examples=["status"],
        description=(
            "System field name (`status`, `assignee`) or a custom field reference "
            "(`severity`, `TRK.severity`)"
        ),
    )
    before: JsonValue = Field(
        default=None,
        examples=["open"],
        description="Value before the change; null when the field had none",
    )
    after: JsonValue = Field(
        default=None,
        examples=["in_progress"],
        description="Value after the change; null when the field was cleared",
    )


class ChangelogEntryRead(BaseModel):
    """Запись истории изменений задачи."""

    id: uuid.UUID
    issue: str = Field(examples=["TRK-123"], description="Key of the issue")
    actor: str = Field(examples=["alice"], description="Key of the actor behind the change")
    event: EventType = Field(
        examples=[EventType.ISSUE_STATUS_CHANGED],
        description="Event type this entry was recorded for",
    )
    changes: list[IssueChangeRead] = Field(
        default_factory=list,
        description="Field-by-field difference; empty for `issue.created`",
    )
    created_at: datetime

    @classmethod
    def of(cls, entry: ChangelogEntry, *, issue_key: str) -> ChangelogEntryRead:
        """Ключ задачи приходит извне: страница истории всегда про одну задачу.

        Связь на задачу ради одного ключа означала бы лишний запрос на каждую страницу
        и ничего бы не добавила — ключ уже известен вызывающему.
        """
        return cls(
            id=entry.id,
            issue=issue_key,
            actor=entry.actor.key,
            event=EventType(entry.event_type),
            changes=[IssueChangeRead(**change) for change in entry.changes],
            created_at=entry.created_at,
        )
