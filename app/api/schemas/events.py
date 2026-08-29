"""Схемы событий: история изменений задачи и внешний вид события для каналов наружу.

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
    event_type: EventType = Field(
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
            event_type=EventType(entry.event_type),
            changes=[IssueChangeRead(**change) for change in entry.changes],
            created_at=entry.created_at,
        )


class EventOriginRead(BaseModel):
    """Само событие: что произошло, кто это сделал и когда."""

    id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Bus event id; null for a call made by an automation rule, which has no bus "
            "event behind it. Also the value to resume an event stream from"
        ),
    )
    type: str = Field(
        examples=["issue.status_changed"],
        description="Event type; `webhook.direct` marks a call made by an automation rule",
    )
    actor: str = Field(examples=["alice"], description="Key of the actor behind the change")
    occurred_at: datetime


class EventObjectRead(BaseModel):
    """Объект, которого событие касается."""

    type: str = Field(examples=["issue"], description="Kind of the object")
    key: str = Field(
        examples=["TRK-123"],
        description="Key of the object; `TRK-123:<uuid>` for a comment or a checklist item",
    )


class EventViewRead(BaseModel):
    """Событие в том виде, в каком его видит внешний получатель.

    Одна форма на два канала — вебхук и живой поток, — и это требование, а не экономия:
    одно событие обязано читаться одинаково у внешнего подписчика и у фронтенда. Собирает
    её домен (`app/domain/event_stream.py`), схема лишь описывает результат.

    Снимка задачи со всеми полями здесь нет намеренно. Наружу уходит то, по чему
    получатель принимает решение и может сходить в API за остальным: на чужой стороне
    объём полезной нагрузки — это объём утечки, а фронтенд всё равно перезапросит свежее.
    """

    event: EventOriginRead
    object: EventObjectRead
    issue: str | None = Field(
        default=None,
        examples=["TRK-123"],
        description="Key of the issue involved; null for project, board and bulk events",
    )
    queue: str | None = Field(default=None, examples=["TRK"], description="Key of the queue")
    projects: list[str] = Field(
        default_factory=list,
        description=(
            "Projects the issue belongs to. Both the previous and the new key are listed "
            "when the event moved the issue between projects"
        ),
    )
    summary: str = Field(
        examples=["TRK-123 status: TRK.open -> TRK.in_progress"],
        description="Ready English text, the same one the inbox shows",
    )
    details: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Identifiers for programmatic decisions; shape depends on the event type",
    )


class StreamEventRead(EventViewRead):
    """Кадр живого потока. Ровно `EventViewRead`, отдельным именем ради читаемости клиента.

    Отдаётся не как JSON-ответ, а как поле `data` кадра `text/event-stream`: поток —
    единственное место в API, где оболочки `{"data": ...}` нет, потому что её нет в самом
    формате SSE. Идентификатор кадра (`id:`) равен `event.id` — с него продолжают поток
    после обрыва.
    """
