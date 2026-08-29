"""REST редактора воркфлоу и переходов конкретной задачи.

Два разных потребителя в одном роутере. Редактор (`/workflows/...`) собирает процесс:
граф статусов и рёбер, который очередь назначает своим типам задач. Переходы задачи
(`/issues/{issue_key}/transitions`) — то, что видит пользователь в карточке: какие
кнопки у задачи есть прямо сейчас и что мешает нажать остальные.

Граф правится двумя способами, и оба нужны: целиком (`PUT /workflows/{id}`) — так
работает редактор процесса, где пользователь двигает всё сразу; по одному элементу
(`/statuses`, `/transitions`) — так работает агент, которому дешевле добавить одно
ребро, чем прислать граф из двадцати.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentActorDep,
    IssueKeyPath,
    IssueTypeRefPath,
    QueueKeyPath,
    SessionDep,
)
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
    """Готовые процессы, из которых можно собрать воркфлоу очереди одним запросом.

    Набор хранится в коде и одинаков на всех установках. Это стартовые точки, а не
    режимы работы: созданный из шаблона процесс дальше правится как любой другой.
    """
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
    queue_key: QueueKeyPath,
    payload: WorkflowGraphWrite,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    """Заводит процесс очереди одним запросом: статусы, начальный статус и все рёбра.

    Граф целиком, а не по частям: промежуточные состояния (статус без входящих рёбер,
    ребро в статус, которого ещё нет) процесс отвергает, и собирать его по одному
    означало бы отбиваться от собственных проверок на каждом шаге.

    Назначить процесс типам задач можно тем же запросом — `issue_types` в теле.
    """
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
    queue_key: QueueKeyPath,
    payload: WorkflowFromTemplateCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    """Материализует готовый шаблон в редактируемый граф этой очереди.

    Шаблон — стартовая точка, а не режим работы: получившийся процесс дальше правится
    как любой другой. Статуса нужной категории в справочнике может не оказаться — тогда
    он заводится локальным статусом очереди, чтобы шаблон был самодостаточным, а не
    инструкцией «сначала подготовьте справочник руками».
    """
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
    """Граф процесса целиком: статусы, рёбра, назначения типам задач и живой охват.

    Охват (`impact`) — сколько задач стоит сейчас в каждом статусе графа. Он здесь
    затем, чтобы правку процесса делали, видя её цену: удаление статуса, в котором
    стоят сорок задач, — это не то же самое, что удаление пустого.
    """
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
    """Заменяет граф целиком. Принимает и то, что отдал `GET`, — без переписывания.

    Редактор процесса читает граф, правит его и присылает обратно, поэтому тело
    принимается в двух видах: коротком (`WorkflowGraphWrite`) и ровно таком, какой
    отдало чтение. Второй вариант несёт `id`, и он обязан совпасть с адресуемым
    процессом: иначе сохранение уехало бы в чужой граф, а клиент увидел бы успех.

    Рёбра, оставшиеся со своими идентификаторами, сохраняют их. Это важно для доски и
    автоматики: они ссылаются на переход по идентификатору, и перевыпуск всех рёбер при
    каждой правке процесса рвал бы эти ссылки без всякой причины.
    """
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
    """Удаляет процесс, не назначенный ни одному типу задач.

    Назначенный не удаляется: у типа задачи не осталось бы процесса, и в очереди стало
    бы нельзя завести задачу. Сначала назначьте типу другой процесс.
    """
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
    """Копия процесса внутри той же очереди, под новым именем.

    Обычный способ безопасно поменять процесс: скопировать, поправить копию, назначить
    её типу задач. Копия получает свои идентификаторы рёбер — ссылаться на переход
    оригинала она не должна.
    """
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
    queue_key: QueueKeyPath,
    issue_type_ref: IssueTypeRefPath,
    payload: WorkflowAssignmentWrite,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[WorkflowGraphRead]:
    """Переключает тип задач очереди на другой процесс.

    Процесс обязан принадлежать этой же очереди и содержать её статус по умолчанию:
    иначе задача, заведённая без явного статуса, попадала бы в статус вне графа и
    осталась бы без единого доступного перехода.
    """
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
    """Добавляет статус в граф вместе с рёбрами, которые делают его достижимым.

    Рёбра — тем же запросом, а не следующим: статус без входящего ребра недостижим, и
    граф с ним процесс не примет. Отвечает графом целиком — правка одного элемента
    меняет и охват, и доступность соседей.
    """
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
    """Убирает статус из графа вместе со всеми его рёбрами.

    Статус, в котором стоят задачи, не убирается: они остались бы вне процесса и без
    переходов. Сколько их — видно в охвате, который отдаёт чтение графа; перенести их
    умеет `POST /statuses/{status_ref}/move-issues`.
    """
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
    """Добавляет ребро между статусами, которые уже есть в графе.

    Ребро без исходного статуса (`source_status: null`) означает «откуда угодно» — так
    описывают отмену, доступную из любого места процесса.
    """
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
    """Заменяет ребро целиком, сохраняя его идентификатор.

    Идентификатор сохраняется намеренно: на переход ссылаются доска и автоматика, и
    правка названия не должна рвать эти ссылки.
    """
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
    """Убирает ребро из графа.

    Отвечает графом, а не `204`: после удаления обычно надо увидеть, не остался ли
    статус недостижимым, — а это видно только по графу целиком.
    """
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
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[IssueTransitionRead]:
    """Кнопки карточки задачи: рёбра из её текущего статуса, доступные и нет.

    Недоступные приезжают вместе с причиной — списком полей, которых им не хватает
    (`missing_fields`). Прятать их значило бы оставить пользователя гадать, почему
    задача не двигается; показывать без причины — предлагать кнопку, которая откажет.
    """
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
    issue_key: IssueKeyPath,
    transition_id: TransitionIdPath,
    payload: IssueTransitionExecute,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Выполняет переход вместе с полями, которых он требует, — одной мутацией.

    Резолюция, исполнитель и значения полей передаются тем же запросом и проверяются в
    целевом состоянии. Поэтому закрытие не требует предварительного `PATCH` и всё равно
    даёт одну версию, одну запись истории и одно событие.

    `version` здесь **обязателен**, в отличие от `PATCH /issues/{issue_key}`, где его
    можно опустить. Переход — это ход в процессе, а не правка поля: если задачу успели
    сдвинуть, повторять ход вслепую нельзя, и ответ будет `409 version_conflict`.
    """
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
