"""Сервис воркфлоу: назначения, живой граф и единая мутация задачи."""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.errors import (
    CatalogEntryUnavailableError,
    FieldInUseError,
    InvalidWorkflowGraphError,
    IssueResolutionNotAllowedError,
    TransitionNotAllowedError,
    TransitionRequirementsError,
    WorkflowAssignmentError,
    WorkflowNameTakenError,
    WorkflowStatusInUseError,
)
from app.domain.events import EventType
from app.domain.fields import FieldValueType
from app.domain.workflows import TransitionDefinition, WorkflowTemplateKey
from app.services import catalogs as catalogs_service
from app.services import events as events_service
from app.services import fields as fields_service
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services import workflow as service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _default_workflow(
    session: AsyncSession,
    queue: Queue,
    owner: Actor,
):
    views = await service.list_queue_workflows(session, queue, initiator=owner)
    assert len(views) == 1
    return views[0].workflow


async def _entry(
    session: AsyncSession,
    owner: Actor,
    kind: CatalogKind,
    ref: str,
):
    return await queues_service.resolve_catalog_ref(session, kind, ref, initiator=owner)


def _simple_transitions() -> list[TransitionDefinition]:
    return [
        TransitionDefinition(
            name="Complete",
            source_status="open",
            target_status="closed",
            requires_resolution=True,
        ),
        TransitionDefinition(
            name="Reopen",
            source_status="closed",
            target_status="open",
        ),
    ]


async def test_new_queue_has_one_default_workflow_assigned_to_every_type(
    db_session: AsyncSession,
    queue: Queue,
    owner: Actor,
) -> None:
    (view,) = await service.list_queue_workflows(db_session, queue, initiator=owner)

    assert view.workflow.name == "Default workflow"
    assert view.workflow.initial_status.ref == "open"
    assert [link.status.ref for link in view.workflow.status_links] == [
        "open",
        "in_progress",
        "closed",
    ]
    assert {entry.ref for entry in view.issue_types} == {"task", "bug", "epic"}
    assert view.impact.issues_without_outgoing_transitions == 0


async def test_forbidden_direct_status_change_is_rejected(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    closed = await _entry(db_session, owner, CatalogKind.STATUS, "closed")
    resolution = await _entry(db_session, owner, CatalogKind.RESOLUTION, "done")

    with pytest.raises(TransitionNotAllowedError) as error:
        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(status=closed, resolution=resolution),
        )

    assert error.value.details["from_status"] == "open"
    assert error.value.details["to_status"] == "closed"


async def test_transition_requirements_use_the_future_issue_state(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    workflow = await _default_workflow(db_session, queue, owner)
    start = next(item for item in workflow.transitions if item.name == "Start progress")
    await service.update_transition(
        db_session,
        workflow,
        start.id,
        initiator=owner,
        definition=TransitionDefinition(
            name=start.name,
            source_status="open",
            target_status="in_progress",
            required_fields=("description",),
        ),
    )
    issue = await make_issue(description="")

    (availability,) = await service.available_transitions(
        db_session,
        issue,
        initiator=owner,
        filled_fields=issues_service.filled_fields_for(issue),
    )
    assert availability.is_available is False
    assert availability.missing_fields == ("description",)

    with pytest.raises(TransitionRequirementsError) as error:
        await issues_service.transition_issue(
            db_session,
            issue,
            start.id,
            initiator=owner,
        )
    assert error.value.details["missing_fields"] == ["description"]

    mutation = await issues_service.transition_issue(
        db_session,
        issue,
        start.id,
        initiator=owner,
        changes=issues_service.IssueChanges(description="Контекст добавлен"),
    )
    assert mutation.issue.status.ref == "in_progress"
    assert {change.field for change in mutation.changes} == {"description", "status"}


async def test_close_and_reopen_keep_resolution_history_in_the_same_mutation(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    workflow = await _default_workflow(db_session, queue, owner)
    start = next(item for item in workflow.transitions if item.name == "Start progress")
    complete = next(item for item in workflow.transitions if item.name == "Complete")
    reopen = next(item for item in workflow.transitions if item.name == "Reopen")
    resolution = await _entry(db_session, owner, CatalogKind.RESOLUTION, "done")
    issue = await make_issue()

    await issues_service.transition_issue(db_session, issue, start.id, initiator=owner)
    closed = await issues_service.transition_issue(
        db_session,
        issue,
        complete.id,
        initiator=owner,
        changes=issues_service.IssueChanges(resolution=resolution),
    )
    assert closed.issue.status.ref == "closed"
    assert closed.issue.resolution.ref == "done"
    assert [change.field for change in closed.changes] == ["status", "resolution"]

    reopened = await issues_service.transition_issue(
        db_session,
        issue,
        reopen.id,
        initiator=owner,
    )
    assert reopened.issue.status.ref == "open"
    assert reopened.issue.resolution is None
    assert [change.field for change in reopened.changes] == ["status", "resolution"]

    history = await events_service.list_changelog(db_session, issue, initiator=owner)
    assert history.items[-1].event_type == EventType.ISSUE_STATUS_CHANGED
    assert history.items[-1].changes == [
        {"field": "status", "before": "closed", "after": "open"},
        {"field": "resolution", "before": "done", "after": None},
    ]


async def test_resolution_cannot_be_set_while_issue_is_not_done(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    resolution = await _entry(db_session, owner, CatalogKind.RESOLUTION, "done")

    with pytest.raises(IssueResolutionNotAllowedError):
        await make_issue(resolution=resolution)


async def test_removing_status_with_issues_reports_the_count(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    workflow = await _default_workflow(db_session, queue, owner)
    in_progress = await _entry(db_session, owner, CatalogKind.STATUS, "in_progress")
    await make_issue(status=in_progress)
    await make_issue(status=in_progress)

    with pytest.raises(WorkflowStatusInUseError) as error:
        await service.remove_status(
            db_session,
            workflow,
            initiator=owner,
            status_ref="in_progress",
        )

    assert error.value.details["issues"] == 2
    assert error.value.details["hint"] == "move the issues to another status first"


async def test_assignment_rejects_existing_issues_outside_the_graph(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    bug = await _entry(db_session, owner, CatalogKind.ISSUE_TYPE, "bug")
    in_progress = await _entry(db_session, owner, CatalogKind.STATUS, "in_progress")
    await make_issue(issue_type=bug, status=in_progress)
    workflow = await service.create_workflow(
        db_session,
        queue,
        initiator=owner,
        name="Without work",
        initial_status="open",
        statuses=["open", "closed"],
        transitions=_simple_transitions(),
    )

    with pytest.raises(WorkflowAssignmentError) as error:
        await service.assign_workflow(db_session, workflow, bug, initiator=owner)

    assert error.value.details["reason"] == "issues_outside_graph"
    assert error.value.details["issues"] == 1


async def test_terminal_done_status_is_reported_in_live_impact(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    workflow = await _default_workflow(db_session, queue, owner)
    start = next(item for item in workflow.transitions if item.name == "Start progress")
    complete = next(item for item in workflow.transitions if item.name == "Complete")
    resolution = await _entry(db_session, owner, CatalogKind.RESOLUTION, "done")
    issue = await make_issue()
    await issues_service.transition_issue(db_session, issue, start.id, initiator=owner)
    await issues_service.transition_issue(
        db_session,
        issue,
        complete.id,
        initiator=owner,
        changes=issues_service.IssueChanges(resolution=resolution),
    )

    await service.replace_workflow_graph(
        db_session,
        workflow,
        initiator=owner,
        name=workflow.name,
        initial_status="open",
        statuses=["open", "in_progress", "closed"],
        transitions=[
            TransitionDefinition(
                name="Start progress",
                source_status="open",
                target_status="in_progress",
            ),
            TransitionDefinition(
                name="Complete",
                source_status="in_progress",
                target_status="closed",
                requires_resolution=True,
            ),
        ],
    )
    impact = await service.workflow_impact(db_session, workflow)

    assert impact.issues_without_outgoing_transitions == 1
    assert impact.by_status == {"closed": 1}


async def test_templates_clone_and_duplicate_names(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    review = await service.create_from_template(
        db_session,
        queue,
        initiator=owner,
        template_key=WorkflowTemplateKey.REVIEW,
        name="Review process",
    )
    clone = await service.clone_workflow(
        db_session,
        review,
        initiator=owner,
        name="Review copy",
    )

    assert [link.status.category.value for link in review.status_links] == [
        "new",
        "in_progress",
        "in_progress",
        "done",
    ]
    source = service.graph_definition(review)
    copied = service.graph_definition(clone)
    assert copied.initial_status == source.initial_status
    assert copied.statuses == source.statuses
    assert [
        (
            item.name,
            item.source_status,
            item.target_status,
            item.required_fields,
            item.requires_resolution,
        )
        for item in copied.transitions
    ] == [
        (
            item.name,
            item.source_status,
            item.target_status,
            item.required_fields,
            item.requires_resolution,
        )
        for item in source.transitions
    ]

    with pytest.raises(WorkflowNameTakenError):
        await service.clone_workflow(
            db_session,
            review,
            initiator=owner,
            name="Review copy",
        )


async def test_mass_move_into_done_requires_and_records_resolution(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    source = await _entry(db_session, owner, CatalogKind.STATUS, "in_progress")
    target = await _entry(db_session, owner, CatalogKind.STATUS, "closed")
    resolution = await _entry(db_session, owner, CatalogKind.RESOLUTION, "done")
    issue = await make_issue(status=source)

    moved = await catalogs_service.move_issues(
        db_session,
        initiator=owner,
        source=source,
        target=target,
        resolution=resolution,
    )
    await db_session.refresh(issue)

    assert moved.moved == 1
    assert issue.status_id == target.id
    assert issue.resolution_id == resolution.id
    history = await events_service.list_changelog(db_session, issue, initiator=owner)
    assert history.items[-1].changes == [
        {"field": "status", "before": "in_progress", "after": "closed"},
        {"field": "resolution", "before": None, "after": "done"},
    ]


async def test_required_custom_field_cannot_be_hidden_deleted_or_narrowed(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    field = await fields_service.create_field(
        db_session,
        initiator=owner,
        key="context",
        name="Context",
        value_type=FieldValueType.STRING,
    )
    workflow = await _default_workflow(db_session, queue, owner)
    start = next(item for item in workflow.transitions if item.name == "Start progress")
    await service.update_transition(
        db_session,
        workflow,
        start.id,
        initiator=owner,
        definition=TransitionDefinition(
            name=start.name,
            source_status="open",
            target_status="in_progress",
            required_fields=("context",),
        ),
    )

    with pytest.raises(FieldInUseError) as hidden:
        await fields_service.update_field(
            db_session,
            field,
            initiator=owner,
            is_hidden=True,
        )
    assert hidden.value.details["reason"] == "workflows_exist"

    bug = await _entry(db_session, owner, CatalogKind.ISSUE_TYPE, "bug")
    with pytest.raises(FieldInUseError) as narrowed:
        await fields_service.update_field(
            db_session,
            field,
            initiator=owner,
            issue_types=[bug],
        )
    assert narrowed.value.details["reason"] == "required_field_not_applicable"

    with pytest.raises(FieldInUseError) as deleted:
        await fields_service.delete_field(db_session, field, initiator=owner)
    assert deleted.value.details["reason"] == "workflows_exist"


async def test_queue_default_status_is_always_part_of_its_workflow(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Шаблон обязан взять статус очереди по умолчанию, а не предпочтённый ключ.

    Иначе очередь создаётся с процессом, в котором нет её собственного стартового
    статуса, и первая же задача без явного статуса упирается в `status_not_in_workflow`.
    """
    await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="backlog",
        name="Бэклог",
        category=StatusCategory.NEW,
    )

    queue = await queues_service.create_queue(
        db_session,
        initiator=owner,
        key="BLG",
        name="Бэклог-очередь",
        default_status_ref="backlog",
    )
    (view,) = await service.list_queue_workflows(db_session, queue, initiator=owner)

    assert view.workflow.initial_status.ref == "backlog"
    assert "backlog" in {link.status.ref for link in view.workflow.status_links}

    issue = await issues_service.create_issue(
        db_session,
        initiator=owner,
        queue=queue,
        summary="Первая задача новой очереди",
    )
    assert issue.status.ref == "backlog"


async def test_done_status_cannot_be_the_queue_default(
    db_session: AsyncSession,
    queue: Queue,
    owner: Actor,
) -> None:
    """Задача без явного статуса попадала бы в `done`, а он требует резолюции."""
    with pytest.raises(CatalogEntryUnavailableError) as created:
        await queues_service.create_queue(
            db_session,
            initiator=owner,
            key="FIN",
            name="Завершённое",
            default_status_ref="closed",
        )
    assert created.value.details["reason"] == "default_status_cannot_be_done"

    with pytest.raises(CatalogEntryUnavailableError) as updated:
        await queues_service.update_queue(
            db_session,
            queue,
            initiator=owner,
            default_status_ref="closed",
        )
    assert updated.value.details["reason"] == "default_status_cannot_be_done"


async def test_adding_an_existing_status_does_not_swallow_its_transitions(
    db_session: AsyncSession,
    queue: Queue,
    owner: Actor,
) -> None:
    """Тихий выход отбросил бы присланные рёбра и вернул успех без правок."""
    workflow = await _default_workflow(db_session, queue, owner)

    with pytest.raises(InvalidWorkflowGraphError) as error:
        await service.add_status(
            db_session,
            workflow,
            initiator=owner,
            status_ref="in_progress",
            transitions=[
                TransitionDefinition(
                    name="Дубль",
                    source_status="open",
                    target_status="in_progress",
                )
            ],
        )
    assert error.value.details["problems"] == [
        {"reason": "duplicate_status", "status": "in_progress"}
    ]
