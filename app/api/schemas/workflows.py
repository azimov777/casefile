"""Схемы редактора воркфлоу и выполнения переходов задачи."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.api.schemas.common import unset_field
from app.db.models.workflow import Transition
from app.domain.catalogs import StatusCategory
from app.domain.workflows import (
    MAX_TRANSITION_NAME_LENGTH,
    MAX_WORKFLOW_NAME_LENGTH,
    TransitionDefinition,
    WorkflowTemplate,
    WorkflowTemplateKey,
)
from app.services.workflow import TransitionAvailability, WorkflowImpact, WorkflowView

StatusRefDescription = (
    "Status reference: bare key for a global status, `QUEUE.key` for a queue-local one"
)
RequiredFieldsDescription = (
    "System field names or custom field references that must be filled in the target state"
)


class WorkflowTransitionWrite(BaseModel):
    """Полное описание ребра для массового или точечного сохранения."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_TRANSITION_NAME_LENGTH)
    from_status: str | None = Field(
        default=None,
        description=f"{StatusRefDescription}; null means any source status",
    )
    to_status: str = Field(description=StatusRefDescription)
    required_fields: list[str] = Field(
        default_factory=list,
        description=RequiredFieldsDescription,
    )
    requires_resolution: bool = Field(
        default=False,
        description="Must be true for transitions to a status in category `done`",
    )

    def definition(self) -> TransitionDefinition:
        return TransitionDefinition(
            name=self.name,
            source_status=self.from_status,
            target_status=self.to_status,
            required_fields=tuple(self.required_fields),
            requires_resolution=self.requires_resolution,
        )


class WorkflowGraphWrite(BaseModel):
    """Полный граф: тем же телом процесс создаётся и заменяется целиком."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_WORKFLOW_NAME_LENGTH)
    initial_status: str = Field(description=StatusRefDescription)
    statuses: list[str] = Field(
        min_length=1,
        description="Ordered status references included in the graph",
    )
    transitions: list[WorkflowTransitionWrite] = Field(default_factory=list)
    issue_types: list[str] = Field(
        default_factory=list,
        description="Issue types to assign after creating the workflow; ignored on replacement",
    )

    def status_refs(self) -> list[str]:
        return list(self.statuses)

    def transition_definitions(self) -> list[TransitionDefinition]:
        return [item.definition() for item in self.transitions]


class WorkflowCloneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_WORKFLOW_NAME_LENGTH)


class WorkflowFromTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: WorkflowTemplateKey
    name: str | None = Field(default=None, min_length=1, max_length=MAX_WORKFLOW_NAME_LENGTH)
    issue_types: list[str] = Field(default_factory=list)


class WorkflowAssignmentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: uuid.UUID


class WorkflowStatusAdd(BaseModel):
    """Добавление узла вместе с рёбрами, сохраняющими целостность графа."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description=StatusRefDescription)
    transitions: list[WorkflowTransitionWrite] = Field(
        min_length=1,
        description="Edges that make the new status reachable and give it a path to done",
    )


class WorkflowTemplateRead(BaseModel):
    key: WorkflowTemplateKey
    name: str
    description: str

    @classmethod
    def of(cls, template: WorkflowTemplate) -> WorkflowTemplateRead:
        return cls(key=template.key, name=template.name, description=template.description)


class WorkflowStatusRead(BaseModel):
    ref: str = Field(description=StatusRefDescription)
    name: str
    category: StatusCategory
    is_initial: bool


class WorkflowTransitionRead(BaseModel):
    id: uuid.UUID
    name: str
    from_status: str | None = Field(description="Null means any source status")
    to_status: str
    required_fields: list[str] = Field(default_factory=list)
    requires_resolution: bool

    @classmethod
    def of(cls, transition: Transition) -> WorkflowTransitionRead:
        return cls(
            id=transition.id,
            name=transition.name,
            from_status=(None if transition.from_status is None else transition.from_status.ref),
            to_status=transition.to_status.ref,
            required_fields=list(transition.required_fields),
            requires_resolution=transition.requires_resolution,
        )

    def definition(self) -> TransitionDefinition:
        return TransitionDefinition(
            id=self.id,
            name=self.name,
            source_status=self.from_status,
            target_status=self.to_status,
            required_fields=tuple(self.required_fields),
            requires_resolution=self.requires_resolution,
        )


class WorkflowImpactStatusRead(BaseModel):
    status: str = Field(description=StatusRefDescription)
    issues: int = Field(ge=0)


class WorkflowImpactRead(BaseModel):
    issues_without_outgoing_transitions: int
    by_status: list[WorkflowImpactStatusRead] = Field(
        default_factory=list,
        description="Issue counts for statuses without an outgoing transition",
    )

    @classmethod
    def of(cls, impact: WorkflowImpact) -> WorkflowImpactRead:
        return cls(
            issues_without_outgoing_transitions=impact.issues_without_outgoing_transitions,
            by_status=[
                WorkflowImpactStatusRead(status=status, issues=issues)
                for status, issues in impact.by_status.items()
            ],
        )


class WorkflowGraphRead(BaseModel):
    """Граф, пригодный для визуального редактора и для агента."""

    id: uuid.UUID
    queue: str
    name: str
    issue_types: list[str]
    initial_status: str
    statuses: list[WorkflowStatusRead]
    transitions: list[WorkflowTransitionRead]
    impact: WorkflowImpactRead
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, view: WorkflowView) -> WorkflowGraphRead:
        workflow = view.workflow
        return cls(
            id=workflow.id,
            queue=workflow.queue.key,
            name=workflow.name,
            issue_types=[issue_type.ref for issue_type in view.issue_types],
            initial_status=workflow.initial_status.ref,
            statuses=[
                WorkflowStatusRead(
                    ref=link.status.ref,
                    name=link.status.name,
                    category=link.status.category,
                    is_initial=link.status_id == workflow.initial_status_id,
                )
                for link in workflow.status_links
            ],
            transitions=[WorkflowTransitionRead.of(item) for item in workflow.transitions],
            impact=WorkflowImpactRead.of(view.impact),
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )

    def status_refs(self) -> list[str]:
        return [status.ref for status in self.statuses]

    def transition_definitions(self) -> list[TransitionDefinition]:
        return [item.definition() for item in self.transitions]


type WorkflowGraphSave = WorkflowGraphWrite | WorkflowGraphRead


class IssueTransitionRead(WorkflowTransitionRead):
    is_available: bool
    missing_fields: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, item: TransitionAvailability) -> IssueTransitionRead:
        transition = WorkflowTransitionRead.of(item.transition)
        return cls(
            **transition.model_dump(),
            is_available=item.is_available,
            missing_fields=list(item.missing_fields),
        )


class IssueTransitionExecute(BaseModel):
    """Поля, которые можно заполнить атомарно вместе со сменой статуса."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Issue version seen by the caller")
    description: str = unset_field(description="Optional description update")
    resolution: str | None = unset_field(
        description="Resolution reference; required when the target category is done"
    )
    assignee: str | None = unset_field(description="Actor key, or null to unassign")
    deadline: datetime | None = unset_field(description="ISO 8601 with a UTC offset")
    tags: list[str] = unset_field(description="Replaces the whole tag set")
    values: dict[str, JsonValue] = unset_field(
        description="Custom field changes keyed by field reference; null removes a value"
    )
