"""Блок `state` и краткий ответ `get_task(brief=true)` в формах MCP (TRK-579).

Поле в поле те же, что `TaskStateRead` и `TaskBriefRead` в REST: агент и человек видят одно
состояние задачи. Блок считает домен (`app/domain/state.py`), здесь только форма.

Описаний у полей почти нет намеренно: схема ответа едет в `tools/list` каждому агенту, и
каждая строка описания стоит токенов в каждом сеансе. Смысл полей сказан в описании
`get_task` и в `CONCEPT.md`, 4.2; имена говорят сами за себя. Статусы — строками, а не
перечислением: перечисление встало бы в схему копией у каждого поля.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.state import TaskState


def _without_titles(schema: dict[str, Any]) -> None:
    """Снимает из схемы модели заголовки полей: «After Summary» повторяет имя `after_summary`."""
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)


#: Общая настройка форм этого файла: схема без заголовков полей (токены в каждом сеансе).
COMPACT = ConfigDict(json_schema_extra=_without_titles)


class StateTransitionView(BaseModel):
    model_config = COMPACT

    no: int
    from_status: str | None
    to_status: str | None
    at: str
    by: str
    reason: str | None


class StateSummaryView(BaseModel):
    model_config = COMPACT

    no: int
    at: str
    next_step: str
    blockers: str
    unmeasured: str | None


class StateQuestionView(BaseModel):
    model_config = COMPACT

    no: int
    to: list[str]
    blocking: bool
    title: str
    discussion: str | None


class StateNoteView(BaseModel):
    model_config = COMPACT

    no: int
    by: str
    title: str


class TaskStateView(BaseModel):
    """Where the task stands now, computed on read from the case and the links."""

    model_config = ConfigDict(from_attributes=True, json_schema_extra=_without_titles)

    status: str
    last_transition: StateTransitionView | None
    last_summary: StateSummaryView | None
    after_summary: int | None
    recent: list[str] = Field(description="`#no type author time: title`, latest last")
    recent_total: int
    questions: list[StateQuestionView]
    remarks: list[StateNoteView]
    warning: StateNoteView | None
    blockers: list[str]
    children: dict[str, int]
    children_unclosed: list[str]
    decisions_after_card: list[int]
    discussions_after_card: list[str]


def task_state(value: TaskState) -> TaskStateView:
    """Блок `state` в форме MCP — тот же набор полей, что `TaskStateRead` в REST."""
    return TaskStateView.model_validate(value, from_attributes=True)


class TaskBriefCardView(BaseModel):
    """Card header in the short answer."""

    model_config = COMPACT

    key: str
    title: str
    status: str
    assignee: str | None
    priority: str
    area: str | None
    version: int
    updated_at: datetime
