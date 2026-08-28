"""Схемы автоматики: правило, его настройка, запись журнала и ручной запуск.

Правило отдаётся двумя половинами в одном объекте: неизменяемое объявление из кода
(`kind`, `events`, `schedule`, `params_schema`) и изменяемое состояние из базы
(`is_enabled`, `queue`, `params`, `saved_filter`). Разделять их на два ресурса было бы
честнее по происхождению и бесполезно на практике: интерфейс правил показывает обе
половины на одном экране, а по отдельности ни одна не отвечает на вопрос «работает ли и
что делает».

`params` и `params_schema` — то самое место, где схема API вынужденно допускает
свободную форму. Она задокументирована: `params_schema` — это JSON Schema, по которой
интерфейс строит форму настройки, а `params` — значения по ней. Прибить их к типу нельзя,
потому что у каждого правила своя схема, объявленная в его же модуле.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.db.models.automation import AutomationRun
from app.domain.automation import RuleKind, RunStatus, RunTrigger
from app.services.automation import RuleView


class AutomationRuleRead(BaseModel):
    """Правило автоматики в ответе: объявление из кода плюс состояние из базы."""

    key: str = Field(
        examples=["close_children_with_parent"],
        description="Stable rule key; it addresses the rule and never changes",
    )
    name: str = Field(
        examples=["Закрытие родителя и его подзадачи"],  # noqa: RUF001
        description="Display name from the rule declaration",
    )
    description: str = Field(
        default="",
        description="What the rule does, from its declaration",
    )
    kind: RuleKind | None = Field(
        default=None,
        description="Rule form; null when the rule has no declaration in the code any more",
    )
    events: list[str] = Field(
        default_factory=list,
        examples=[["issue.status_changed"]],
        description="Event types a trigger reacts to; empty for other forms",
    )
    schedule_seconds: int | None = Field(
        default=None,
        examples=[21600],
        description="Period of a scheduled rule in seconds; null for other forms",
    )
    query: str | None = Field(
        default=None,
        description="Selection declared in the code for a scheduled rule; a saved filter wins",
    )
    is_available: bool = Field(
        description="Whether the rule still has a declaration in the code and can run",
    )
    is_enabled: bool = Field(description="Whether the rule is allowed to run")
    queue: str | None = Field(
        default=None,
        examples=["TRK"],
        description="Queue the rule is limited to; null means every queue",
    )
    saved_filter: uuid.UUID | None = Field(
        default=None,
        description="Saved filter used instead of the declared query; scheduled rules only",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Rule settings, validated against `params_schema` when saved",
    )
    params_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema of `params`, taken from the rule declaration",
    )
    last_run_at: datetime | None = None
    next_run_at: datetime | None = Field(
        default=None,
        description="When a scheduled rule is due next; null when it is not scheduled",
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, view: RuleView) -> AutomationRuleRead:
        rule = view.rule
        definition = view.definition
        return cls(
            key=rule.rule_key,
            name=rule.rule_key if definition is None else definition.name,
            description="" if definition is None else definition.description,
            kind=None if definition is None else definition.kind,
            events=[] if definition is None else list(definition.events),
            schedule_seconds=(
                None
                if definition is None or definition.schedule is None
                else int(definition.schedule.total_seconds())
            ),
            query=None if definition is None else definition.query,
            is_available=view.is_available,
            is_enabled=rule.is_enabled,
            queue=None if rule.queue is None else rule.queue.key,
            saved_filter=rule.saved_filter_id,
            params=dict(rule.params),
            params_schema={} if definition is None else definition.params_schema(),
            last_run_at=rule.last_run_at,
            next_run_at=rule.next_run_at,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


class AutomationRuleUpdate(BaseModel):
    """Частичное обновление правила: меняются только переданные поля.

    Объявления здесь нет и быть не может: форма, события и расписание живут в коде.
    Попытка прислать их — ошибка валидации, а не молчаливое игнорирование: иначе
    клиент считал бы, что переключил правило с триггера на автодействие.
    """

    model_config = ConfigDict(extra="forbid")

    is_enabled: bool = unset_field(description="Turn the rule on or off")
    queue: str | None = unset_field(
        examples=["TRK"],
        description="Queue key to limit the rule to; pass null to let it see every queue",
    )
    saved_filter: uuid.UUID | None = unset_field(
        description=(
            "Saved filter to select issues with, replacing the query declared in the code; "
            "scheduled rules only, pass null to go back to the declared query"
        ),
    )
    params: dict[str, Any] = unset_field(
        description="Rule settings; replaced as a whole and validated against `params_schema`",
    )


class AutomationRunRead(BaseModel):
    """Запись журнала срабатываний."""

    id: uuid.UUID
    rule: str = Field(examples=["close_children_with_parent"], description="Rule key")
    issue: str | None = Field(
        default=None,
        examples=["TRK-123"],
        description="Issue the rule worked on; null for runs not bound to an issue",
    )
    trigger: RunTrigger = Field(description="What started the run")
    status: RunStatus
    reason: str | None = Field(
        default=None,
        examples=["rate_limited"],
        description="Why the run was skipped; null when it was not",
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="What the rule did, in order",
    )
    error: str | None = Field(default=None, description="Failure text; null when it did not fail")
    initiator: str | None = Field(
        default=None,
        examples=["alice"],
        description="Actor whose action led to the run; the rule itself runs as `system`",
    )
    event: uuid.UUID | None = Field(default=None, description="Event that started the run")
    event_type: str | None = Field(default=None, examples=["issue.status_changed"])
    chain_depth: int = Field(
        description="0 means a human action started the chain, 1 means another rule did",
    )
    duration_ms: int
    created_at: datetime

    @classmethod
    def of(cls, run: AutomationRun) -> AutomationRunRead:
        return cls(
            id=run.id,
            rule=run.rule_key,
            issue=run.issue_key,
            trigger=run.trigger,
            status=run.status,
            reason=run.reason,
            actions=list(run.actions),
            error=run.error,
            initiator=run.initiator_key,
            event=run.event_id,
            event_type=run.event_type,
            chain_depth=run.chain_depth,
            duration_ms=run.duration_ms,
            created_at=run.created_at,
        )


class MacroRunRequest(BaseModel):
    """Ручной запуск макроса по конкретной задаче."""

    model_config = ConfigDict(extra="forbid")

    issue: str = Field(
        examples=["TRK-123"],
        description="Issue key the macro is run for",
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Settings for this run only; merged over the stored ones and validated the same way"
        ),
    )
