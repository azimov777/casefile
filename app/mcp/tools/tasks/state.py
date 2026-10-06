"""Блок `state` и краткий ответ `get_task(brief=true)` в формах MCP (TRK-579).

Поле в поле те же, что `TaskStateRead` и `TaskBriefRead` в REST: агент и человек видят одно
состояние задачи. Блок считает домен (`app/domain/state.py`), здесь только форма.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.state import REASON_LIMIT, RECENT_LIMIT, UNMEASURED_LIMIT, TaskState
from app.mcp.enums import TaskPrioritySchema, TaskStatusSchema


class StateTransitionView(BaseModel):
    """Last status change: when, by whom and why."""

    no: int
    from_status: TaskStatusSchema | None
    to_status: TaskStatusSchema | None
    at: str
    by: str
    reason: str | None = Field(description=f"Cut at {REASON_LIMIT} characters")


class StateSummaryView(BaseModel):
    """Parts of the latest summary."""

    no: int
    at: str
    next_step: str = Field(description=f"Cut at {REASON_LIMIT} characters")
    blockers: str = Field(description=f"Cut at {REASON_LIMIT} characters")
    unmeasured: str | None = Field(
        description=f"Cut at {UNMEASURED_LIMIT} characters; `null` unless it closed the task"
    )


class StateRecentView(BaseModel):
    """Entries of agents and humans after the latest summary; all of them without one."""

    after_summary: int | None
    total: int
    lines: list[str] = Field(
        description=f"Up to {RECENT_LIMIT} latest, `#no type author time: title`"
    )


class StateQuestionView(BaseModel):
    """Open question."""

    no: int
    to: list[str]
    blocking: bool
    title: str


class StateNoteView(BaseModel):
    """Open remark or warning."""

    no: int
    by: str
    title: str


class StateChildrenView(BaseModel):
    """Children by status and the keys of those not closed."""

    total: int
    by_status: dict[str, int]
    unclosed: list[str]


class TaskStateView(BaseModel):
    """Where the task stands now, computed on read from the case and the links."""

    model_config = ConfigDict(from_attributes=True)

    status: TaskStatusSchema
    last_transition: StateTransitionView | None
    last_summary: StateSummaryView | None
    recent: StateRecentView
    questions: list[StateQuestionView]
    remarks: list[StateNoteView]
    warning: StateNoteView | None
    blockers: list[str] = Field(description="Keys of open `blocked_by` tasks")
    children: StateChildrenView
    decisions_after_card: list[int] = Field(
        description="`decision` entries filed after the last edit of the sections"
    )


def task_state(value: TaskState) -> TaskStateView:
    """Блок `state` в форме MCP — тот же набор полей, что `TaskStateRead` в REST."""
    return TaskStateView.model_validate(value, from_attributes=True)


class TaskBriefCardView(BaseModel):
    """Card header of the short answer."""

    key: str
    title: str
    status: TaskStatusSchema
    assignee: str | None
    priority: TaskPrioritySchema
    direction: str | None = Field(description="Address of the direction")
    version: int
    updated_at: datetime
