"""REST редактора воркфлоу и переходов конкретной задачи."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActorDep, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.issues import IssueRead
from app.api.schemas.workflows import (
    IssueTransitionExecute,
    IssueTransitionRead,
    WorkflowAssignmentWrite,
    WorkflowCloneCreate,
    WorkflowFromTemplateCreate,
    WorkflowGraphRead,
    WorkflowGraphSave,
    WorkflowGraphWrite,
    WorkflowStatusAdd,
    WorkflowTemplateRead,
    WorkflowTransitionWrite,
)
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution
from app.db.models.workflow import Workflow
from app.domain.catalogs import CatalogKind
from app.domain.errors import WorkflowAssignmentError
from app.services import actors as actors_service
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services import workflow as service

router = APIRouter(tags=["workflows"])

WorkflowIdPath = Annotated[uuid.UUID, Path(description="Workflow UUID")]
TransitionIdPath = Annotated[uuid.UUID, Path(description="Transition UUID")]


@router.get("/workflow-templates", summary="List ready workflow templates")
async def list_workflow_templates(
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[WorkflowTemplateRead]:
    # `session` и актор присутствуют сознательно: маршрут защищён общей зависимостью,
    # а будущая модель прав не должна иметь публичную лазейку только потому, что набор
    # пока хранится в коде.
    del session, current_actor
    return CollectionResponse[WorkflowTemplateRead].of(
        [WorkflowTemplateRead.of(template) for template in service.templates()]
    )


@router.post(
    "/queues/{queue_key}/workflows",
    status_code=status.HTTP_201_CREATED,
    summary="Create a workflow as a complete graph",
)
async def create_workflow(
    queue_key: str,
    payload: WorkflowGraphWrite,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    queue = await queues_service.get_queue_by_key(session, queue_key)
    workflow = await service.create_workflow(
        session,
        queue,
        initiator=current_actor,
        name=payload.name,
        initial_status=payload.initial_status,
        statuses=payload.status_refs(),
        transitions=payload.transition_definitions(),
    )
    await _assign_issue_types(
        session,
        workflow,
        payload.issue_types,
        current_actor=current_actor,
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.post(
    "/queues/{queue_key}/workflows/from-template",
    status_code=status.HTTP_201_CREATED,
    summary="Create a workflow from a ready template",
)
async def create_workflow_from_template(
    queue_key: str,
    payload: WorkflowFromTemplateCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    queue = await queues_service.get_queue_by_key(session, queue_key)
    workflow = await service.create_from_template(
        session,
        queue,
        initiator=current_actor,
        template_key=payload.template,
        name=payload.name,
    )
    await _assign_issue_types(
        session,
        workflow,
        payload.issue_types,
        current_actor=current_actor,
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.get("/workflows/{workflow_id}", summary="Read a workflow graph")
async def read_workflow(
    workflow_id: WorkflowIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id, initiator=current_actor)
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.put("/workflows/{workflow_id}", summary="Replace a workflow graph")
async def replace_workflow(
    workflow_id: WorkflowIdPath,
    payload: WorkflowGraphSave,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id)
    if isinstance(payload, WorkflowGraphRead) and payload.id != workflow.id:
        raise WorkflowAssignmentError(
            details={
                "workflow_id": str(workflow.id),
                "payload_workflow_id": str(payload.id),
                "reason": "payload_belongs_to_another_workflow",
            }
        )
    workflow = await service.replace_workflow_graph(
        session,
        workflow,
        initiator=current_actor,
        name=payload.name,
        initial_status=payload.initial_status,
        statuses=payload.status_refs(),
        transitions=payload.transition_definitions(),
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.delete(
    "/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unassigned workflow",
)
async def delete_workflow(
    workflow_id: WorkflowIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    workflow = await service.get_workflow(session, workflow_id)
    await service.delete_workflow(session, workflow, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/workflows/{workflow_id}/clone",
    status_code=status.HTTP_201_CREATED,
    summary="Clone a workflow",
)
async def clone_workflow(
    workflow_id: WorkflowIdPath,
    payload: WorkflowCloneCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    source = await service.get_workflow(session, workflow_id)
    workflow = await service.clone_workflow(
        session,
        source,
        initiator=current_actor,
        name=payload.name,
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.put(
    "/queues/{queue_key}/issue-types/{issue_type_ref}/workflow",
    summary="Assign a workflow to a queue issue type",
)
async def assign_workflow(
    queue_key: str,
    issue_type_ref: str,
    payload: WorkflowAssignmentWrite,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    queue = await queues_service.get_queue_by_key(session, queue_key)
    issue_type = await _resolve_issue_type(
        session,
        issue_type_ref,
        current_actor=current_actor,
    )
    workflow = await service.get_workflow(session, payload.workflow_id)
    if workflow.queue_id != queue.id:
        raise WorkflowAssignmentError(
            details={
                "workflow_id": str(workflow.id),
                "workflow_queue": workflow.queue.key,
                "requested_queue": queue.key,
                "reason": "belongs_to_another_queue",
            }
        )
    await service.assign_workflow(
        session,
        workflow,
        issue_type,
        initiator=current_actor,
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.post("/workflows/{workflow_id}/statuses", summary="Add a status to a workflow")
async def add_workflow_status(
    workflow_id: WorkflowIdPath,
    payload: WorkflowStatusAdd,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id)
    await service.add_status(
        session,
        workflow,
        initiator=current_actor,
        status_ref=payload.status,
        transitions=[item.definition() for item in payload.transitions],
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.delete(
    "/workflows/{workflow_id}/statuses/{status_ref}",
    summary="Remove an unused status from a workflow",
)
async def remove_workflow_status(
    workflow_id: WorkflowIdPath,
    status_ref: Annotated[str, Path(description="Status reference")],
    session: SessionDep,
    current_actor: CurrentActorDep,
    new_initial_status: Annotated[
        str | None,
        Query(description="Required when removing the current initial status"),
    ] = None,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id)
    await service.remove_status(
        session,
        workflow,
        initiator=current_actor,
        status_ref=status_ref,
        new_initial_status=new_initial_status,
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.post("/workflows/{workflow_id}/transitions", summary="Add a workflow transition")
async def add_workflow_transition(
    workflow_id: WorkflowIdPath,
    payload: WorkflowTransitionWrite,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id)
    await service.add_transition(
        session,
        workflow,
        initiator=current_actor,
        transition=payload.definition(),
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.put(
    "/workflows/{workflow_id}/transitions/{transition_id}",
    summary="Replace a workflow transition",
)
async def replace_workflow_transition(
    workflow_id: WorkflowIdPath,
    transition_id: TransitionIdPath,
    payload: WorkflowTransitionWrite,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id)
    await service.update_transition(
        session,
        workflow,
        transition_id,
        initiator=current_actor,
        definition=payload.definition(),
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.delete(
    "/workflows/{workflow_id}/transitions/{transition_id}",
    summary="Delete a workflow transition",
)
async def delete_workflow_transition(
    workflow_id: WorkflowIdPath,
    transition_id: TransitionIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    workflow = await service.get_workflow(session, workflow_id)
    await service.delete_transition(
        session,
        workflow,
        transition_id,
        initiator=current_actor,
    )
    return DataResponse[WorkflowGraphRead](
        data=WorkflowGraphRead.of(await service.view_workflow(session, workflow))
    )


@router.get("/issues/{issue_key}/transitions", summary="List transitions for an issue")
async def list_issue_transitions(
    issue_key: str,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[IssueTransitionRead]:
    issue = await issues_service.get_issue_by_key(session, issue_key)
    transitions = await service.available_transitions(
        session,
        issue,
        initiator=current_actor,
        filled_fields=issues_service.filled_fields_for(issue),
    )
    return CollectionResponse[IssueTransitionRead].of(
        [IssueTransitionRead.of(item) for item in transitions]
    )


@router.post(
    "/issues/{issue_key}/transitions/{transition_id}",
    summary="Perform a workflow transition",
)
async def perform_issue_transition(
    issue_key: str,
    transition_id: TransitionIdPath,
    payload: IssueTransitionExecute,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    issue = await issues_service.get_issue_by_key(session, issue_key)
    values = payload.model_dump(exclude_unset=True)
    expected_version = values.pop("version")
    resolution_ref = values.pop("resolution", _MISSING)
    assignee_key = values.pop("assignee", _MISSING)
    if resolution_ref is not _MISSING:
        values["resolution"] = (
            None
            if resolution_ref is None
            else await _resolve_resolution(
                session,
                resolution_ref,
                current_actor=current_actor,
            )
        )
    if assignee_key is not _MISSING:
        values["assignee"] = (
            None
            if assignee_key is None
            else await actors_service.get_actor_by_key(session, assignee_key)
        )
    mutation = await issues_service.transition_issue(
        session,
        issue,
        transition_id,
        initiator=current_actor,
        changes=issues_service.IssueChanges(**values),
        expected_version=expected_version,
    )
    return DataResponse[IssueRead](data=IssueRead.of(mutation.issue))


_MISSING = object()


async def _assign_issue_types(
    session: AsyncSession,
    workflow: Workflow,
    refs: list[str],
    *,
    current_actor: Actor,
) -> None:
    for ref in refs:
        issue_type = await _resolve_issue_type(
            session,
            ref,
            current_actor=current_actor,
        )
        await service.assign_workflow(
            session,
            workflow,
            issue_type,
            initiator=current_actor,
        )


async def _resolve_issue_type(
    session: AsyncSession,
    ref: str,
    *,
    current_actor: Actor,
) -> IssueType:
    entry = await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.ISSUE_TYPE,
        ref,
        initiator=current_actor,
    )
    assert isinstance(entry, IssueType)
    return entry


async def _resolve_resolution(
    session: AsyncSession,
    ref: str,
    *,
    current_actor: Actor,
) -> Resolution:
    entry = await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.RESOLUTION,
        ref,
        initiator=current_actor,
    )
    assert isinstance(entry, Resolution)
    return entry
