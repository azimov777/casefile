"""Воркфлоу: редактор графа, назначения типам и проверка переходов задач.

Все способы редактирования — массовое сохранение, точечные операции и клонирование —
проходят через один доменный валидатор. Живой процесс никогда не остаётся в промежуточном
состоянии с недостижимым статусом: операция либо сохраняет целый корректный граф, либо
транзакция откатывается.

Смена самой задачи остаётся у её владельца (`app/services/issues.py`). Этот модуль отвечает
на вопросы «какой процесс назначен», «есть ли такое ребро» и «какие требования выполнены»,
а единая мутация задачи пишет статус, резолюцию, историю и outbox одной транзакцией.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Status
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.models.workflow import Transition, Workflow, WorkflowStatus
from app.db.repositories import CatalogRepository, QueueRepository, WorkflowRepository
from app.domain.catalogs import CatalogKind, StatusCategory, parse_catalog_ref
from app.domain.errors import (
    CatalogEntryUnavailableError,
    InvalidWorkflowGraphError,
    TransitionNotAllowedError,
    TransitionNotFoundError,
    TransitionRequirementsError,
    WorkflowAssignmentError,
    WorkflowInUseError,
    WorkflowNameTakenError,
    WorkflowNotFoundError,
    WorkflowStatusInUseError,
)
from app.domain.fields import SYSTEM_FIELD_KEYS, parse_field_ref
from app.domain.issues import IssueField
from app.domain.workflows import (
    WORKFLOW_TEMPLATES,
    TransitionDefinition,
    WorkflowGraphDefinition,
    WorkflowStatusDefinition,
    WorkflowTemplate,
    WorkflowTemplateKey,
    missing_required_fields,
    normalize_required_fields,
    template_by_key,
    validate_graph,
    validate_transition_name,
    validate_workflow_name,
)
from app.services import catalogs as catalogs_service
from app.services import fields as fields_service
from app.services.permissions import ensure_allowed

# Системные поля, которые осмысленно требовать перед переходом: только те, что реально
# бывают пустыми. `resolution` выражена отдельным флагом перехода, а поля, которые у
# задачи заполнены всегда (`key`, `queue`, `author`, `status`, `summary`, `priority`),
# не принимаются: такое требование выполнялось бы само собой и создавало иллюзию
# проверки. Требование `followers` выполняется своими эндпоинтами подписки, остальные
# поля можно заполнить прямо в теле перехода.
REQUIRED_SYSTEM_FIELDS = frozenset(
    {
        IssueField.DESCRIPTION.value,
        IssueField.ASSIGNEE.value,
        IssueField.FOLLOWERS.value,
        IssueField.DEADLINE.value,
        IssueField.TAGS.value,
    }
)


@dataclass(frozen=True, slots=True)
class TransitionAvailability:
    """Переход для карточки задачи плюс причина, почему его пока нельзя выполнить."""

    transition: Transition
    is_available: bool
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowImpact:
    """Сколько живых задач после правки не имеет ни одного структурного выхода."""

    issues_without_outgoing_transitions: int
    by_status: dict[str, int]


@dataclass(frozen=True, slots=True)
class WorkflowView:
    """Граф вместе с назначенными типами и отчётом о влиянии на живые задачи."""

    workflow: Workflow
    issue_types: tuple[IssueType, ...]
    impact: WorkflowImpact


@dataclass(frozen=True, slots=True)
class _ResolvedTransition:
    definition: TransitionDefinition
    source: Status | None
    target: Status


@dataclass(frozen=True, slots=True)
class _ResolvedGraph:
    definition: WorkflowGraphDefinition
    initial_status: Status
    statuses: tuple[Status, ...]
    transitions: tuple[_ResolvedTransition, ...]


# --- Чтение -----------------------------------------------------------------------


def templates() -> tuple[WorkflowTemplate, ...]:
    """Два стабильных шаблона, доступных REST и будущему MCP без обращения к БД."""
    return WORKFLOW_TEMPLATES


async def get_workflow(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    initiator: Actor | None = None,
) -> Workflow:
    if initiator is not None:
        ensure_allowed(initiator, "workflow.read")
    workflow = await WorkflowRepository(session).get_by_id(workflow_id)
    if workflow is None:
        raise WorkflowNotFoundError(details={"id": str(workflow_id)})
    return workflow


async def workflow_for_issue_type(
    session: AsyncSession,
    *,
    queue_id: uuid.UUID,
    issue_type_id: uuid.UUID,
) -> Workflow:
    """Назначенный паре процесс; отсутствие означает повреждённую конфигурацию."""
    workflow = await WorkflowRepository(session).get_for_issue_type(queue_id, issue_type_id)
    if workflow is None:
        raise WorkflowAssignmentError(
            details={
                "queue_id": str(queue_id),
                "issue_type_id": str(issue_type_id),
                "reason": "workflow_not_assigned",
            }
        )
    return workflow


async def list_queue_workflows(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
) -> list[WorkflowView]:
    ensure_allowed(initiator, "workflow.list", target=queue)
    workflows = await WorkflowRepository(session).list_for_queue(queue.id)
    return [await view_workflow(session, workflow) for workflow in workflows]


async def view_workflow(session: AsyncSession, workflow: Workflow) -> WorkflowView:
    repository = WorkflowRepository(session)
    bindings = await repository.assigned_issue_types(workflow.id)
    return WorkflowView(
        workflow=workflow,
        issue_types=tuple(binding.issue_type for binding in bindings),
        impact=await workflow_impact(session, workflow),
    )


async def workflow_impact(session: AsyncSession, workflow: Workflow) -> WorkflowImpact:
    """Считает задачи в статусах без исходящего ребра после текущей конфигурации."""
    counts = await WorkflowRepository(session).issue_counts_by_status(workflow.id)
    outgoing = {
        link.status_id
        for link in workflow.status_links
        if any(
            transition.to_status_id != link.status_id
            and (transition.from_status_id is None or transition.from_status_id == link.status_id)
            for transition in workflow.transitions
        )
    }
    by_status = {
        link.status.ref: counts.get(link.status_id, 0)
        for link in workflow.status_links
        if link.status_id not in outgoing and counts.get(link.status_id, 0)
    }
    return WorkflowImpact(
        issues_without_outgoing_transitions=sum(by_status.values()),
        by_status=by_status,
    )


def graph_definition(workflow: Workflow) -> WorkflowGraphDefinition:
    """ORM-граф → чистое определение; единственный мост к доменному валидатору."""
    return WorkflowGraphDefinition(
        initial_status=workflow.initial_status.ref,
        statuses=tuple(
            WorkflowStatusDefinition(ref=link.status.ref, category=link.status.category)
            for link in workflow.status_links
        ),
        transitions=tuple(
            _transition_definition(transition) for transition in workflow.transitions
        ),
    )


# --- Создание, массовое сохранение и шаблоны --------------------------------------


async def create_workflow(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
    name: str,
    initial_status: str,
    statuses: Sequence[str],
    transitions: Sequence[TransitionDefinition],
) -> Workflow:
    ensure_allowed(initiator, "workflow.create", target=queue)
    normalized_name = validate_workflow_name(name)
    await _ensure_name_available(session, queue, normalized_name)
    resolved = await _resolve_graph(
        session,
        queue,
        initial_status=initial_status,
        status_refs=statuses,
        transitions=transitions,
    )
    validate_graph(resolved.definition)

    workflow = Workflow(
        queue=queue,
        name=normalized_name,
        initial_status=resolved.initial_status,
        status_links=[
            WorkflowStatus(status=status, position=position)
            for position, status in enumerate(resolved.statuses)
        ],
        transitions=[
            _transition_model(item, position=position)
            for position, item in enumerate(resolved.transitions)
        ],
    )
    return await WorkflowRepository(session).add(workflow)


async def replace_workflow_graph(
    session: AsyncSession,
    workflow: Workflow,
    *,
    initiator: Actor,
    name: str,
    initial_status: str,
    statuses: Sequence[str],
    transitions: Sequence[TransitionDefinition],
) -> Workflow:
    """Атомарно заменяет граф тем же представлением, которое отдаётся на чтение."""
    ensure_allowed(initiator, "workflow.update", target=workflow)
    normalized_name = validate_workflow_name(name)
    await _ensure_name_available(
        session,
        workflow.queue,
        normalized_name,
        excluding=workflow,
    )
    resolved = await _resolve_graph(
        session,
        workflow.queue,
        initial_status=initial_status,
        status_refs=statuses,
        transitions=transitions,
        existing=workflow,
    )
    validate_graph(resolved.definition)
    await _ensure_removed_statuses_unused(session, workflow, resolved.statuses)
    await _ensure_assignments_accept_graph(session, workflow, resolved)

    status_links = [
        WorkflowStatus(status=status, position=position)
        for position, status in enumerate(resolved.statuses)
    ]
    transition_models = [
        _transition_model(item, position=position)
        for position, item in enumerate(resolved.transitions)
    ]
    workflow.name = normalized_name
    return await WorkflowRepository(session).replace_graph(
        workflow,
        initial_status=resolved.initial_status,
        status_links=status_links,
        transitions=transition_models,
    )


async def clone_workflow(
    session: AsyncSession,
    workflow: Workflow,
    *,
    initiator: Actor,
    name: str,
) -> Workflow:
    """Копирует граф в той же очереди; назначения типов намеренно не копируются."""
    ensure_allowed(initiator, "workflow.create", target=workflow.queue)
    definition = graph_definition(workflow)
    return await create_workflow(
        session,
        workflow.queue,
        initiator=initiator,
        name=name,
        initial_status=definition.initial_status,
        statuses=[status.ref for status in definition.statuses],
        transitions=[
            TransitionDefinition(
                name=transition.name,
                source_status=transition.source_status,
                target_status=transition.target_status,
                required_fields=transition.required_fields,
                requires_resolution=transition.requires_resolution,
            )
            for transition in definition.transitions
        ],
    )


async def create_from_template(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
    template_key: WorkflowTemplateKey,
    name: str | None = None,
) -> Workflow:
    """Материализует простой процесс или процесс с ревью в редактируемый граф.

    Если нужной категории статуса нет, создаётся локальный статус очереди. Для review
    нужен второй статус `in_progress`; он также создаётся локально, чтобы шаблон был
    самодостаточным, а не инструкцией «сначала вручную подготовьте справочник».
    """
    template = template_by_key(template_key)
    available = await CatalogRepository(session, Status).list_available(queue.id)
    # Статус очереди по умолчанию обязан оказаться в графе: задача, заведённая без
    # явного статуса, получает именно его, и граф без него делает очередь нерабочей.
    # Поэтому он вытесняет предпочтительный ключ в узле своей категории.
    default_status = queue.default_status
    start = await _template_status(
        session,
        queue,
        initiator=initiator,
        available=available,
        category=StatusCategory.NEW,
        preferred_key="open",
        name="Open",
        preferred=default_status,
    )
    work = await _template_status(
        session,
        queue,
        initiator=initiator,
        available=available,
        category=StatusCategory.IN_PROGRESS,
        preferred_key="in_progress",
        name="In progress",
        excluded={start.id},
        preferred=default_status,
    )
    done = await _template_status(
        session,
        queue,
        initiator=initiator,
        available=available,
        category=StatusCategory.DONE,
        preferred_key="closed",
        name="Closed",
        excluded={start.id, work.id},
        preferred=default_status,
    )

    statuses = [start, work]
    transitions = [_draft("Start progress", start, work)]
    if template.includes_review:
        review = await _template_status(
            session,
            queue,
            initiator=initiator,
            available=available,
            category=StatusCategory.IN_PROGRESS,
            preferred_key="review",
            name="Review",
            excluded={start.id, work.id, done.id},
        )
        statuses.append(review)
        transitions.extend(
            [
                _draft("Send to review", work, review),
                _draft("Return to work", review, work),
                _draft("Complete", review, done, requires_resolution=True),
            ]
        )
    else:
        transitions.append(_draft("Complete", work, done, requires_resolution=True))
    statuses.append(done)
    transitions.append(_draft("Reopen", done, start))

    return await create_workflow(
        session,
        queue,
        initiator=initiator,
        name=name or template.name,
        initial_status=start.ref,
        statuses=[status.ref for status in statuses],
        transitions=transitions,
    )


async def create_default_workflow(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
) -> Workflow:
    """Простой процесс, который получает каждая новая очередь."""
    return await create_from_template(
        session,
        queue,
        initiator=initiator,
        template_key=WorkflowTemplateKey.SIMPLE,
        name="Default workflow",
    )


# --- Назначение и удаление --------------------------------------------------------


async def assign_workflow(
    session: AsyncSession,
    workflow: Workflow,
    issue_type: IssueType,
    *,
    initiator: Actor,
) -> Workflow:
    ensure_allowed(initiator, "workflow.assign", target=workflow)
    binding = await QueueRepository(session).get_issue_type_binding(
        workflow.queue_id,
        issue_type.id,
    )
    if binding is None:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.ISSUE_TYPE.value,
                "ref": issue_type.ref,
                "queue": workflow.queue.key,
                "reason": "not_allowed_in_queue",
            }
        )

    definition = graph_definition(workflow)
    validate_graph(definition)
    status_ids = {link.status_id for link in workflow.status_links}
    if workflow.queue.default_status_id not in status_ids:
        raise WorkflowAssignmentError(
            details={
                "workflow_id": str(workflow.id),
                "issue_type": issue_type.ref,
                "reason": "queue_default_status_outside_graph",
                "status": workflow.queue.default_status.ref,
                "hint": "add the queue default status to the workflow first",
            }
        )
    outside = await WorkflowRepository(session).count_issues_outside_statuses(
        queue_id=workflow.queue_id,
        issue_type_id=issue_type.id,
        status_ids=status_ids,
    )
    if outside:
        raise WorkflowAssignmentError(
            details={
                "workflow_id": str(workflow.id),
                "issue_type": issue_type.ref,
                "reason": "issues_outside_graph",
                "issues": outside,
                "hint": "move the issues to statuses in this workflow first",
            }
        )
    await _ensure_required_fields_applicable(
        session,
        workflow.queue,
        issue_type,
        definition.transitions,
    )
    binding.workflow = workflow
    await session.flush()
    return workflow


async def delete_workflow(
    session: AsyncSession,
    workflow: Workflow,
    *,
    initiator: Actor,
) -> None:
    ensure_allowed(initiator, "workflow.delete", target=workflow)
    assignments = await WorkflowRepository(session).count_assignments(workflow.id)
    if assignments:
        raise WorkflowInUseError(
            details={
                "workflow_id": str(workflow.id),
                "issue_types": assignments,
                "hint": "assign another workflow to those issue types first",
            }
        )
    await WorkflowRepository(session).delete(workflow)


# --- Точечное редактирование ------------------------------------------------------


async def add_status(
    session: AsyncSession,
    workflow: Workflow,
    *,
    initiator: Actor,
    status_ref: str,
    transitions: Sequence[TransitionDefinition],
) -> Workflow:
    """Добавляет узел вместе с рёбрами, необходимыми для целостности живого графа."""
    ensure_allowed(initiator, "workflow.update", target=workflow)
    status = await _resolve_status(session, workflow.queue, status_ref, require_active=True)
    if status.id in {link.status_id for link in workflow.status_links}:
        # Отказ, а не тихий выход: вместе со статусом приходят рёбра, и молчаливое
        # «уже есть» отбросило бы их, вернув клиенту успешный ответ без его правок.
        raise InvalidWorkflowGraphError(
            details={"problems": [{"reason": "duplicate_status", "status": status.ref}]}
        )

    resolved_transitions = await _resolve_transitions(
        session,
        workflow.queue,
        transitions,
        statuses=[*(link.status for link in workflow.status_links), status],
    )
    current = graph_definition(workflow)
    future = WorkflowGraphDefinition(
        initial_status=workflow.initial_status.ref,
        statuses=(
            *current.statuses,
            WorkflowStatusDefinition(ref=status.ref, category=status.category),
        ),
        transitions=(
            *current.transitions,
            *(item.definition for item in resolved_transitions),
        ),
    )
    validate_graph(future)
    await _ensure_assignments_accept_definition(session, workflow, future)

    workflow.status_links.append(WorkflowStatus(status=status, position=len(workflow.status_links)))
    workflow.transitions.extend(
        _transition_model(item, position=len(workflow.transitions) + offset)
        for offset, item in enumerate(resolved_transitions)
    )
    await session.flush()
    return workflow


async def remove_status(
    session: AsyncSession,
    workflow: Workflow,
    *,
    initiator: Actor,
    status_ref: str,
    new_initial_status: str | None = None,
) -> Workflow:
    ensure_allowed(initiator, "workflow.update", target=workflow)
    status = await _resolve_status(session, workflow.queue, status_ref, require_active=False)
    link = next((item for item in workflow.status_links if item.status_id == status.id), None)
    if link is None:
        # Удаление идемпотентно: результат вызова — граф без этого статуса, и он уже
        # такой. Ошибка здесь заставляла бы клиента сверять граф перед каждой правкой.
        return workflow

    issues = await WorkflowRepository(session).count_issues_for_status(workflow.id, status.id)
    if issues:
        raise WorkflowStatusInUseError(
            details={
                "workflow_id": str(workflow.id),
                "status": status.ref,
                "issues": issues,
                "hint": "move the issues to another status first",
            }
        )

    initial = workflow.initial_status
    if initial.id == status.id:
        if new_initial_status is None:
            raise InvalidWorkflowGraphError(
                details={
                    "problems": [
                        {"reason": "replacement_initial_status_required", "status": status.ref}
                    ]
                }
            )
        initial = await _resolve_status(
            session,
            workflow.queue,
            new_initial_status,
            require_active=False,
        )

    remaining_links = [item for item in workflow.status_links if item.status_id != status.id]
    remaining_transitions = [
        transition
        for transition in workflow.transitions
        if transition.from_status_id != status.id and transition.to_status_id != status.id
    ]
    future = WorkflowGraphDefinition(
        initial_status=initial.ref,
        statuses=tuple(
            WorkflowStatusDefinition(ref=item.status.ref, category=item.status.category)
            for item in remaining_links
        ),
        transitions=tuple(_transition_definition(item) for item in remaining_transitions),
    )
    validate_graph(future)
    await _ensure_assignments_accept_definition(session, workflow, future)

    workflow.initial_status = initial
    workflow.status_links = remaining_links
    workflow.transitions = remaining_transitions
    _renumber(workflow)
    await session.flush()
    return workflow


async def add_transition(
    session: AsyncSession,
    workflow: Workflow,
    *,
    initiator: Actor,
    transition: TransitionDefinition,
) -> Transition:
    ensure_allowed(initiator, "workflow.update", target=workflow)
    resolved = (
        await _resolve_transitions(
            session,
            workflow.queue,
            [transition],
            statuses=[link.status for link in workflow.status_links],
        )
    )[0]
    current = graph_definition(workflow)
    future = WorkflowGraphDefinition(
        initial_status=workflow.initial_status.ref,
        statuses=current.statuses,
        transitions=(*current.transitions, resolved.definition),
    )
    validate_graph(future)
    await _ensure_assignments_accept_definition(session, workflow, future)

    model = _transition_model(resolved, position=len(workflow.transitions))
    workflow.transitions.append(model)
    await session.flush()
    return model


async def update_transition(
    session: AsyncSession,
    workflow: Workflow,
    transition_id: uuid.UUID,
    *,
    initiator: Actor,
    definition: TransitionDefinition,
) -> Transition:
    ensure_allowed(initiator, "workflow.update", target=workflow)
    transition = await _transition_in_workflow(session, workflow, transition_id)
    resolved = (
        await _resolve_transitions(
            session,
            workflow.queue,
            [definition],
            statuses=[link.status for link in workflow.status_links],
        )
    )[0]
    definitions = [
        resolved.definition if item.id == transition.id else _transition_definition(item)
        for item in workflow.transitions
    ]
    future = WorkflowGraphDefinition(
        initial_status=workflow.initial_status.ref,
        statuses=graph_definition(workflow).statuses,
        transitions=tuple(definitions),
    )
    validate_graph(future)
    await _ensure_assignments_accept_definition(session, workflow, future)

    transition.name = resolved.definition.name
    transition.from_status = resolved.source
    transition.to_status = resolved.target
    transition.required_fields = list(resolved.definition.required_fields)
    transition.requires_resolution = resolved.definition.requires_resolution
    await session.flush()
    return transition


async def delete_transition(
    session: AsyncSession,
    workflow: Workflow,
    transition_id: uuid.UUID,
    *,
    initiator: Actor,
) -> None:
    ensure_allowed(initiator, "workflow.update", target=workflow)
    transition = await _transition_in_workflow(session, workflow, transition_id)
    remaining = [item for item in workflow.transitions if item.id != transition.id]
    future = WorkflowGraphDefinition(
        initial_status=workflow.initial_status.ref,
        statuses=graph_definition(workflow).statuses,
        transitions=tuple(_transition_definition(item) for item in remaining),
    )
    validate_graph(future)
    await _ensure_assignments_accept_definition(session, workflow, future)

    workflow.transitions = remaining
    _renumber(workflow)
    await session.flush()


# --- Движок переходов -------------------------------------------------------------


async def available_transitions(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    filled_fields: frozenset[str],
) -> list[TransitionAvailability]:
    ensure_allowed(initiator, "issue.transition", target=issue)
    workflow = await workflow_for_issue_type(
        session,
        queue_id=issue.queue_id,
        issue_type_id=issue.issue_type_id,
    )
    result: list[TransitionAvailability] = []
    for transition in _outgoing_transitions(workflow, issue.status_id):
        missing = missing_required_fields(_transition_definition(transition), filled_fields)
        result.append(
            TransitionAvailability(
                transition=transition,
                is_available=not missing,
                missing_fields=missing,
            )
        )
    return result


async def ensure_transition_allowed(
    session: AsyncSession,
    issue: Issue,
    *,
    target_status: Status,
    initiator: Actor,
) -> None:
    """Проверяет наличие ребра; сигнатура точки-заглушки из задачи 05 сохранена."""
    ensure_allowed(initiator, "issue.transition", target=issue)
    workflow = await workflow_for_issue_type(
        session,
        queue_id=issue.queue_id,
        issue_type_id=issue.issue_type_id,
    )
    candidates = [
        transition
        for transition in _outgoing_transitions(workflow, issue.status_id)
        if transition.to_status_id == target_status.id
    ]
    if not candidates:
        raise TransitionNotAllowedError(
            details={
                "issue": issue.key,
                "workflow_id": str(workflow.id),
                "from_status": issue.status.ref,
                "to_status": target_status.ref,
                "reason": "transition_missing",
            }
        )


async def ensure_transition_requirements(
    session: AsyncSession,
    issue: Issue,
    *,
    target_status: Status,
    filled_fields: frozenset[str],
) -> None:
    """Для прямого PATCH разрешает переход, если выполнено хотя бы одно ребро к цели."""
    workflow = await workflow_for_issue_type(
        session,
        queue_id=issue.queue_id,
        issue_type_id=issue.issue_type_id,
    )
    candidates = [
        transition
        for transition in _outgoing_transitions(workflow, issue.status_id)
        if transition.to_status_id == target_status.id
    ]
    missing_by_transition = [
        (
            transition,
            missing_required_fields(_transition_definition(transition), filled_fields),
        )
        for transition in candidates
    ]
    if any(not missing for _, missing in missing_by_transition):
        return
    missing = sorted({field for _, fields in missing_by_transition for field in fields})
    raise TransitionRequirementsError(
        details={
            "issue": issue.key,
            "from_status": issue.status.ref,
            "to_status": target_status.ref,
            "missing_fields": missing,
            "transitions": [
                {"id": str(transition.id), "missing_fields": list(fields)}
                for transition, fields in missing_by_transition
            ],
        }
    )


async def selected_transition(
    session: AsyncSession,
    issue: Issue,
    transition_id: uuid.UUID,
    *,
    initiator: Actor,
) -> Transition:
    """Выбранное ребро принадлежит процессу задачи и выходит из её статуса.

    Требования полей здесь не проверяются: их проверяет `ensure_transition_fields`
    уже по будущему состоянию задачи. Единой мутации нужен именно такой порядок —
    сначала право и само ребро, потом нормализация резолюции, и только затем поля.
    """
    ensure_allowed(initiator, "issue.transition", target=issue)
    workflow = await workflow_for_issue_type(
        session,
        queue_id=issue.queue_id,
        issue_type_id=issue.issue_type_id,
    )
    transition = await _transition_in_workflow(session, workflow, transition_id)
    if transition not in _outgoing_transitions(workflow, issue.status_id):
        raise TransitionNotAllowedError(
            details={
                "issue": issue.key,
                "transition_id": str(transition.id),
                "from_status": issue.status.ref,
                "reason": "wrong_source_status",
            }
        )
    return transition


def ensure_transition_fields(
    issue: Issue,
    transition: Transition,
    *,
    filled_fields: frozenset[str],
) -> None:
    """Требования уже выбранного ребра в будущем состоянии задачи. Без обращения к БД."""
    missing = missing_required_fields(_transition_definition(transition), filled_fields)
    if missing:
        raise TransitionRequirementsError(
            details={
                "issue": issue.key,
                "transition_id": str(transition.id),
                "missing_fields": list(missing),
            }
        )


async def ensure_status_in_assigned_workflow(
    session: AsyncSession,
    *,
    queue: Queue,
    issue_type: IssueType,
    status: Status,
) -> Workflow:
    """Создание и смена типа не могут оставить задачу в статусе вне её процесса."""
    workflow = await workflow_for_issue_type(
        session,
        queue_id=queue.id,
        issue_type_id=issue_type.id,
    )
    if status.id not in {link.status_id for link in workflow.status_links}:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.STATUS.value,
                "ref": status.ref,
                "queue": queue.key,
                "issue_type": issue_type.ref,
                "workflow_id": str(workflow.id),
                "reason": "status_not_in_workflow",
            }
        )
    return workflow


async def ensure_queue_default_status_supported(
    session: AsyncSession,
    queue: Queue,
    status: Status,
) -> None:
    """Статус по умолчанию обязан входить в процесс каждого разрешённого типа.

    Клиент может указать тип задачи и не указать статус, поэтому проверять только
    процесс типа по умолчанию недостаточно: общий статус подставляется для любой
    связки очереди и типа.
    """
    bindings = await WorkflowRepository(session).queue_assignments(queue.id)
    unsupported = [
        binding.issue_type.ref
        for binding in bindings
        if status.id not in {link.status_id for link in binding.workflow.status_links}
    ]
    if unsupported:
        raise WorkflowAssignmentError(
            details={
                "queue": queue.key,
                "status": status.ref,
                "reason": "queue_default_status_outside_workflows",
                "issue_types": unsupported,
                "hint": "add the status to every assigned workflow first",
            }
        )


# --- Внутреннее -------------------------------------------------------------------


async def _ensure_name_available(
    session: AsyncSession,
    queue: Queue,
    name: str,
    *,
    excluding: Workflow | None = None,
) -> None:
    existing = await WorkflowRepository(session).get_by_name(queue.id, name)
    if existing is not None and (excluding is None or existing.id != excluding.id):
        raise WorkflowNameTakenError(
            details={"queue": queue.key, "name": name, "workflow_id": str(existing.id)}
        )


async def _resolve_graph(
    session: AsyncSession,
    queue: Queue,
    *,
    initial_status: str,
    status_refs: Sequence[str],
    transitions: Sequence[TransitionDefinition],
    existing: Workflow | None = None,
) -> _ResolvedGraph:
    existing_ids = set() if existing is None else {link.status_id for link in existing.status_links}
    resolved_statuses: list[Status] = []
    for ref in status_refs:
        resolved_statuses.append(
            await _resolve_status(
                session,
                queue,
                ref,
                require_active=False,
            )
        )
    statuses = tuple(resolved_statuses)
    for status in statuses:
        if not status.is_active and status.id not in existing_ids:
            raise CatalogEntryUnavailableError(
                details={
                    "kind": CatalogKind.STATUS.value,
                    "ref": status.ref,
                    "queue": queue.key,
                    "reason": "inactive",
                }
            )
    initial = await _resolve_status(session, queue, initial_status, require_active=False)
    resolved_transitions = await _resolve_transitions(
        session,
        queue,
        transitions,
        statuses=statuses,
    )
    _ensure_transition_ids_valid(resolved_transitions, existing=existing)
    definition = WorkflowGraphDefinition(
        initial_status=initial.ref,
        statuses=tuple(
            WorkflowStatusDefinition(ref=status.ref, category=status.category)
            for status in statuses
        ),
        transitions=tuple(item.definition for item in resolved_transitions),
    )
    return _ResolvedGraph(
        definition=definition,
        initial_status=initial,
        statuses=statuses,
        transitions=resolved_transitions,
    )


async def _resolve_transitions(
    session: AsyncSession,
    queue: Queue,
    transitions: Sequence[TransitionDefinition],
    *,
    statuses: Sequence[Status],
) -> tuple[_ResolvedTransition, ...]:
    status_by_ref = {status.ref: status for status in statuses}
    result: list[_ResolvedTransition] = []
    for draft in transitions:
        source_ref = None
        if draft.source_status is not None:
            source_ref = (
                await _resolve_status(
                    session,
                    queue,
                    draft.source_status,
                    require_active=False,
                )
            ).ref
        target = await _resolve_status(
            session,
            queue,
            draft.target_status,
            require_active=False,
        )
        source = None if source_ref is None else status_by_ref.get(source_ref)
        if source_ref is not None and source is None:
            # Объект всё равно разрешён, чтобы ошибка была «узел не входит в граф», а
            # не «статуса нет». Домен ниже сформирует точную проблему.
            source = await _resolve_status(session, queue, source_ref, require_active=False)
        required_fields = await _resolve_required_fields(
            session,
            queue,
            draft.required_fields,
        )
        definition = TransitionDefinition(
            id=draft.id,
            name=validate_transition_name(draft.name),
            source_status=source_ref,
            target_status=target.ref,
            required_fields=required_fields,
            requires_resolution=draft.requires_resolution,
        )
        result.append(
            _ResolvedTransition(
                definition=definition,
                source=source,
                target=target,
            )
        )
    return tuple(result)


async def _resolve_status(
    session: AsyncSession,
    queue: Queue,
    ref: str,
    *,
    require_active: bool,
) -> Status:
    parsed = parse_catalog_ref(ref, kind=CatalogKind.STATUS)
    if parsed.queue_key is not None and parsed.queue_key != queue.key:
        raise CatalogEntryUnavailableError(
            details={
                "kind": CatalogKind.STATUS.value,
                "ref": ref,
                "queue": queue.key,
                "reason": "belongs_to_another_queue",
            }
        )
    entry = await catalogs_service.get_entry(
        session,
        CatalogKind.STATUS,
        key=parsed.key,
        queue=queue if parsed.queue_key is not None else None,
    )
    assert isinstance(entry, Status)
    if require_active:
        catalogs_service.ensure_available_in_queue(entry, kind=CatalogKind.STATUS, queue=queue)
    return entry


async def _resolve_required_fields(
    session: AsyncSession,
    queue: Queue,
    fields: Iterable[str],
) -> tuple[str, ...]:
    resolved: list[str] = []
    for ref in normalize_required_fields(fields):
        if ref in REQUIRED_SYSTEM_FIELDS:
            resolved.append(ref)
            continue
        if ref in SYSTEM_FIELD_KEYS:
            reason = (
                "use_requires_resolution" if ref == IssueField.RESOLUTION.value else "unsupported"
            )
            raise InvalidWorkflowGraphError(
                details={
                    "problems": [
                        {"reason": "invalid_required_field", "field": ref, "detail": reason}
                    ]
                }
            )
        parsed = parse_field_ref(ref)
        if parsed.queue_key is not None and parsed.queue_key != queue.key:
            raise InvalidWorkflowGraphError(
                details={
                    "problems": [
                        {
                            "reason": "required_field_belongs_to_another_queue",
                            "field": ref,
                            "queue": queue.key,
                        }
                    ]
                }
            )
        field = await fields_service.get_field(
            session,
            key=parsed.key,
            queue=queue if parsed.queue_key is not None else None,
        )
        if field.is_hidden:
            raise InvalidWorkflowGraphError(
                details={"problems": [{"reason": "required_field_hidden", "field": ref}]}
            )
        resolved.append(fields_service.field_ref(field))
    return normalize_required_fields(resolved)


async def _ensure_removed_statuses_unused(
    session: AsyncSession,
    workflow: Workflow,
    statuses: Sequence[Status],
) -> None:
    remaining_ids = {status.id for status in statuses}
    for link in workflow.status_links:
        if link.status_id in remaining_ids:
            continue
        issues = await WorkflowRepository(session).count_issues_for_status(
            workflow.id,
            link.status_id,
        )
        if issues:
            raise WorkflowStatusInUseError(
                details={
                    "workflow_id": str(workflow.id),
                    "status": link.status.ref,
                    "issues": issues,
                    "hint": "move the issues to another status first",
                }
            )


async def _ensure_assignments_accept_graph(
    session: AsyncSession,
    workflow: Workflow,
    graph: _ResolvedGraph,
) -> None:
    status_ids = {status.id for status in graph.statuses}
    bindings = await WorkflowRepository(session).assigned_issue_types(workflow.id)
    if bindings and workflow.queue.default_status_id not in status_ids:
        raise WorkflowAssignmentError(
            details={
                "workflow_id": str(workflow.id),
                "status": workflow.queue.default_status.ref,
                "reason": "queue_default_status_outside_graph",
            }
        )
    for binding in bindings:
        outside = await WorkflowRepository(session).count_issues_outside_statuses(
            queue_id=workflow.queue_id,
            issue_type_id=binding.issue_type_id,
            status_ids=status_ids,
        )
        if outside:
            raise WorkflowAssignmentError(
                details={
                    "workflow_id": str(workflow.id),
                    "issue_type": binding.issue_type.ref,
                    "reason": "issues_outside_graph",
                    "issues": outside,
                }
            )
        await _ensure_required_fields_applicable(
            session,
            workflow.queue,
            binding.issue_type,
            graph.definition.transitions,
        )


async def _ensure_assignments_accept_definition(
    session: AsyncSession,
    workflow: Workflow,
    definition: WorkflowGraphDefinition,
) -> None:
    bindings = await WorkflowRepository(session).assigned_issue_types(workflow.id)
    status_refs = {status.ref for status in definition.statuses}
    if bindings and workflow.queue.default_status.ref not in status_refs:
        raise WorkflowAssignmentError(
            details={
                "workflow_id": str(workflow.id),
                "status": workflow.queue.default_status.ref,
                "reason": "queue_default_status_outside_graph",
            }
        )
    for binding in bindings:
        await _ensure_required_fields_applicable(
            session,
            workflow.queue,
            binding.issue_type,
            definition.transitions,
        )


async def _ensure_required_fields_applicable(
    session: AsyncSession,
    queue: Queue,
    issue_type: IssueType,
    transitions: Sequence[TransitionDefinition],
) -> None:
    custom_required = {
        field
        for transition in transitions
        for field in transition.required_fields
        if field not in REQUIRED_SYSTEM_FIELDS
    }
    if not custom_required:
        return
    applicable = {
        fields_service.field_ref(field)
        for field in await fields_service.applicable_fields(
            session,
            queue=queue,
            issue_type=issue_type,
        )
    }
    missing = sorted(custom_required - applicable)
    if missing:
        raise WorkflowAssignmentError(
            details={
                "queue": queue.key,
                "issue_type": issue_type.ref,
                "reason": "required_fields_not_applicable",
                "fields": missing,
            }
        )


async def _transition_in_workflow(
    session: AsyncSession,
    workflow: Workflow,
    transition_id: uuid.UUID,
) -> Transition:
    transition = await WorkflowRepository(session).get_transition(workflow.id, transition_id)
    if transition is None:
        raise TransitionNotFoundError(
            details={"workflow_id": str(workflow.id), "transition_id": str(transition_id)}
        )
    return transition


def _outgoing_transitions(workflow: Workflow, status_id: uuid.UUID) -> list[Transition]:
    return [
        transition
        for transition in workflow.transitions
        if transition.to_status_id != status_id
        and (transition.from_status_id is None or transition.from_status_id == status_id)
    ]


def _transition_definition(transition: Transition) -> TransitionDefinition:
    return TransitionDefinition(
        id=transition.id,
        name=transition.name,
        source_status=None if transition.from_status is None else transition.from_status.ref,
        target_status=transition.to_status.ref,
        required_fields=transition.required_field_names,
        requires_resolution=transition.requires_resolution,
    )


def _transition_model(item: _ResolvedTransition, *, position: int) -> Transition:
    values = {
        "from_status": item.source,
        "to_status": item.target,
        "name": item.definition.name,
        "required_fields": list(item.definition.required_fields),
        "requires_resolution": item.definition.requires_resolution,
        "position": position,
    }
    if item.definition.id is not None:
        values["id"] = item.definition.id
    return Transition(
        **values,
    )


def _ensure_transition_ids_valid(
    transitions: Sequence[_ResolvedTransition],
    *,
    existing: Workflow | None,
) -> None:
    supplied = [item.definition.id for item in transitions if item.definition.id is not None]
    if len(supplied) != len(set(supplied)):
        raise InvalidWorkflowGraphError(
            details={"problems": [{"reason": "duplicate_transition_id"}]}
        )
    if existing is None and supplied:
        raise InvalidWorkflowGraphError(
            details={"problems": [{"reason": "transition_id_not_allowed_on_create"}]}
        )
    if existing is None:
        return
    known = {transition.id for transition in existing.transitions}
    unknown = [str(transition_id) for transition_id in supplied if transition_id not in known]
    if unknown:
        raise InvalidWorkflowGraphError(
            details={
                "problems": [
                    {"reason": "transition_id_belongs_to_another_workflow", "ids": unknown}
                ]
            }
        )


def _draft(
    name: str,
    source: Status,
    target: Status,
    *,
    requires_resolution: bool = False,
) -> TransitionDefinition:
    return TransitionDefinition(
        name=name,
        source_status=source.ref,
        target_status=target.ref,
        requires_resolution=requires_resolution,
    )


async def _template_status(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
    available: list[Status],
    category: StatusCategory,
    preferred_key: str,
    name: str,
    excluded: set[uuid.UUID] | None = None,
    preferred: Status | None = None,
) -> Status:
    excluded = excluded or set()
    if (
        preferred is not None
        and preferred.category is category
        and preferred.id not in excluded
        and preferred.is_active
    ):
        return preferred
    preferred_by_key = next(
        (
            status
            for status in available
            if status.id not in excluded
            and status.is_active
            and status.category is category
            and status.key == preferred_key
        ),
        None,
    )
    if preferred_by_key is not None:
        return preferred_by_key
    same_category = next(
        (
            status
            for status in available
            if status.id not in excluded and status.is_active and status.category is category
        ),
        None,
    )
    if same_category is not None:
        return same_category

    repository = CatalogRepository(session, Status)
    key = preferred_key
    suffix = 2
    while (
        await repository.get(key, queue.id) is not None
        or await repository.get(key, None) is not None
    ):
        key = f"{preferred_key}_{suffix}"
        suffix += 1
    created = await catalogs_service.create_entry(
        session,
        CatalogKind.STATUS,
        initiator=initiator,
        key=key,
        name=name,
        queue=queue,
        category=category,
    )
    assert isinstance(created, Status)
    available.append(created)
    return created


def _renumber(workflow: Workflow) -> None:
    for position, link in enumerate(workflow.status_links):
        link.position = position
    for position, transition in enumerate(workflow.transitions):
        transition.position = position
