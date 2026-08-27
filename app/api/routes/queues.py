"""Очереди: настройка процесса и конфигурация целиком.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет, иначе
те же операции из MCP пошли бы другим путём и мимо будущих событий.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.catalogs import IssueTypeRead
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.queues import (
    QueueConfigRead,
    QueueCreate,
    QueueIssueTypesUpdate,
    QueueRead,
    QueueUpdate,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import actors as actors_service
from app.services import queues as service

router = APIRouter(prefix="/queues", tags=["queues"])

# Без `pattern`: параметр адресует существующую очередь, а адресация в проекте
# мягкая — `trk` находит ту же очередь, что и `TRK`. Строгий шаблон стоит в схеме
# создания, где ключ придумывают.
QueueKeyPath = Annotated[
    str,
    Path(description="Queue key, immutable once created", examples=["TRK"]),
]


@router.get("", summary="List queues")
async def list_queues(
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
    is_archived: Annotated[bool | None, Query(description="Filter by the archived flag")] = None,
    owner: Annotated[str | None, Query(description="Filter by owner actor key")] = None,
) -> CollectionResponse[QueueRead]:
    owner_actor = None if owner is None else await actors_service.get_actor_by_key(session, owner)
    page = await service.list_queues(
        session,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
        is_archived=is_archived,
        owner=owner_actor,
    )
    return CollectionResponse[QueueRead].of(
        [QueueRead.of(queue) for queue in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a queue")
async def create_queue(
    payload: QueueCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[QueueRead]:
    """Заводит очередь с рабочей конфигурацией: без указаний берёт глобальные справочники."""
    owner = (
        None
        if payload.owner is None
        else await actors_service.get_actor_by_key(session, payload.owner)
    )
    queue = await service.create_queue(
        session,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        owner=owner,
        issue_type_refs=payload.issue_types,
        default_issue_type_ref=payload.default_issue_type,
        default_status_ref=payload.default_status,
    )
    return DataResponse[QueueRead](data=QueueRead.of(queue))


@router.get("/{queue_key}", summary="Read a queue")
async def read_queue(
    queue_key: QueueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[QueueRead]:
    queue = await service.read_queue(session, queue_key, initiator=current_actor)
    return DataResponse[QueueRead](data=QueueRead.of(queue))


@router.patch("/{queue_key}", summary="Update a queue")
async def update_queue(
    queue_key: QueueKeyPath,
    payload: QueueUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[QueueRead]:
    """Меняет только переданные поля. Ключ очереди неизменяем и в схеме отсутствует."""
    queue = await service.get_queue_by_key(session, queue_key)
    changes = payload.model_dump(exclude_unset=True)
    owner_key = changes.pop("owner", None)
    queue = await service.update_queue(
        session,
        queue,
        initiator=current_actor,
        name=changes.get("name"),
        description=changes.get("description"),
        owner=(
            None if owner_key is None else await actors_service.get_actor_by_key(session, owner_key)
        ),
        default_issue_type_ref=changes.get("default_issue_type"),
        default_status_ref=changes.get("default_status"),
    )
    return DataResponse[QueueRead](data=QueueRead.of(queue))


@router.delete(
    "/{queue_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty queue",
)
async def delete_queue(
    queue_key: QueueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет очередь без задач. Очередь с задачами удалить нельзя — её архивируют."""
    queue = await service.get_queue_by_key(session, queue_key)
    await service.delete_queue(session, queue, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{queue_key}/archive", summary="Archive a queue")
async def archive_queue(
    queue_key: QueueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[QueueRead]:
    """Убирает очередь в архив: новых задач в ней не заводят, всё остальное остаётся.

    Идемпотентно — повторный запрос отвечает так же и ничего не меняет.
    """
    queue = await service.get_queue_by_key(session, queue_key)
    queue = await service.archive_queue(session, queue, initiator=current_actor)
    return DataResponse[QueueRead](data=QueueRead.of(queue))


@router.post("/{queue_key}/unarchive", summary="Restore a queue from the archive")
async def unarchive_queue(
    queue_key: QueueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[QueueRead]:
    queue = await service.get_queue_by_key(session, queue_key)
    queue = await service.unarchive_queue(session, queue, initiator=current_actor)
    return DataResponse[QueueRead](data=QueueRead.of(queue))


@router.get("/{queue_key}/config", summary="Read the whole queue configuration")
async def read_queue_config(
    queue_key: QueueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[QueueConfigRead]:
    """Типы задач, статусы и резолюции очереди одним запросом.

    Основной источник данных для формы создания задачи и для агента, впервые
    увидевшего очередь. Отдаются только активные записи.
    """
    queue = await service.get_queue_by_key(session, queue_key)
    config = await service.get_queue_config(session, queue, initiator=current_actor)
    return DataResponse[QueueConfigRead](data=QueueConfigRead.of(config))


@router.put("/{queue_key}/issue-types", summary="Replace the queue issue types")
async def set_queue_issue_types(
    queue_key: QueueKeyPath,
    payload: QueueIssueTypesUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[IssueTypeRead]:
    """Задаёт набор целиком: `PUT`, а не точечные добавления, — результат не зависит от порядка."""
    queue = await service.get_queue_by_key(session, queue_key)
    issue_types = await service.set_issue_types(
        session, queue, initiator=current_actor, refs=payload.issue_types
    )
    return CollectionResponse[IssueTypeRead].of([IssueTypeRead.of(entry) for entry in issue_types])
