"""Справочники: статусы, типы задач, резолюции.

Три ресурса одной формы. Общий у них и способ адресации: глобальная запись — голым
ключом (`/statuses/open`), локальная — с префиксом очереди (`/statuses/TRK.open`).
Разрешение ссылки в запись — общая для всех трёх функция сценария; здесь только
перевод HTTP в вызов и обратно.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.catalogs import (
    IssueTypeCreate,
    IssueTypeRead,
    IssueTypeUpdate,
    MoveIssuesRequest,
    MoveIssuesResult,
    ResolutionCreate,
    ResolutionRead,
    ResolutionUpdate,
    StatusCreate,
    StatusRead,
    StatusUpdate,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.db.models.queue import Queue
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.catalogs import CatalogKind
from app.services import catalogs as service
from app.services import queues as queues_service

router = APIRouter(tags=["catalogs"])

statuses_router = APIRouter(prefix="/statuses", tags=["catalogs"])
issue_types_router = APIRouter(prefix="/issue-types", tags=["catalogs"])
resolutions_router = APIRouter(prefix="/resolutions", tags=["catalogs"])


def _ref_path(kind: str) -> object:
    """Параметр пути со ссылкой на запись справочника.

    Без `pattern`: адресация в проекте мягкая, регистр приводит домен, а невнятную
    ссылку отвергает `parse_catalog_ref` кодом `invalid_catalog_ref` — с объяснением
    ожидаемого формата в `details`, чего проверка по шаблону дать не может.
    """
    return Path(
        description=f"{kind} reference: `key` for a global entry, `QUEUE.key` for a local one",
        examples=["open", "TRK.open"],
    )


StatusRefPath = Annotated[str, _ref_path("Status")]
IssueTypeRefPath = Annotated[str, _ref_path("Issue type")]
ResolutionRefPath = Annotated[str, _ref_path("Resolution")]

QueueFilterQuery = Annotated[
    str | None,
    Query(
        description=(
            "Queue key: return entries usable in this queue — global ones plus its own. "
            "Omit to list global entries only."
        ),
    ),
]
ActiveFilterQuery = Annotated[bool | None, Query(description="Filter by the activity flag")]


async def _scope(session: AsyncSession, queue_key: str | None) -> Queue | None:
    """Очередь-область по ключу: `None` — глобальная область."""
    return await queues_service.resolve_scope(session, queue_key)


# --- Статусы ---------------------------------------------------------------------


@statuses_router.get("", summary="List statuses")
async def list_statuses(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueFilterQuery = None,
    is_active: ActiveFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[StatusRead]:
    page = await service.list_entries(
        session,
        CatalogKind.STATUS,
        initiator=current_actor,
        queue=await _scope(session, queue),
        is_active=is_active,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[StatusRead].of(
        [StatusRead.of(entry) for entry in page.items],
        next_cursor=page.next_cursor,
    )


@statuses_router.post("", status_code=status.HTTP_201_CREATED, summary="Create a status")
async def create_status(
    payload: StatusCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[StatusRead]:
    """Категория обязательна: на неё опираются доски, прогресс проектов и автоматика."""
    entry = await service.create_entry(
        session,
        CatalogKind.STATUS,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        queue=await _scope(session, payload.queue),
        category=payload.category,
    )
    return DataResponse[StatusRead](data=StatusRead.of(entry))


@statuses_router.get("/{status_ref}", summary="Read a status")
async def read_status(
    status_ref: StatusRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[StatusRead]:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, status_ref, initiator=current_actor
    )
    return DataResponse[StatusRead](data=StatusRead.of(entry))


@statuses_router.patch("/{status_ref}", summary="Update a status")
async def update_status(
    status_ref: StatusRefPath,
    payload: StatusUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[StatusRead]:
    """Меняет название, активность и категорию. Ключ статуса неизменяем."""
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, status_ref, initiator=current_actor
    )
    changes = payload.model_dump(exclude_unset=True)
    entry = await service.update_entry(
        session, entry, CatalogKind.STATUS, initiator=current_actor, **changes
    )
    return DataResponse[StatusRead](data=StatusRead.of(entry))


@statuses_router.delete(
    "/{status_ref}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a status",
)
async def delete_status(
    status_ref: StatusRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Отклоняется, если в статусе стоят задачи или он выбран очередью по умолчанию.

    Задачи переносят отдельным вызовом `POST /statuses/{ref}/move-issues`, после чего
    удаление проходит. Ненужный, но используемый статус правильнее отключить
    (`PATCH` с `is_active: false`): история изменений останется читаемой.
    """
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, status_ref, initiator=current_actor
    )
    await service.delete_entry(session, entry, CatalogKind.STATUS, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@statuses_router.post("/{status_ref}/move-issues", summary="Move issues to another status")
async def move_status_issues(
    status_ref: StatusRefPath,
    payload: MoveIssuesRequest,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[MoveIssuesResult]:
    """Переносит задачи из статуса в другой — явный шаг перед удалением непустого статуса."""
    source = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, status_ref, initiator=current_actor
    )
    target = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, payload.target_status, initiator=current_actor
    )
    moved = await service.move_issues(
        session,
        initiator=current_actor,
        source=source,
        target=target,
        queue=await _scope(session, payload.queue),
    )
    return DataResponse[MoveIssuesResult](
        data=MoveIssuesResult(
            source_status=service.format_entry_ref(moved.source),
            target_status=service.format_entry_ref(moved.target),
            moved=moved.moved,
        )
    )


# --- Типы задач ------------------------------------------------------------------


@issue_types_router.get("", summary="List issue types")
async def list_issue_types(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueFilterQuery = None,
    is_active: ActiveFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueTypeRead]:
    """Все типы области. Какие из них разрешены в очереди — в её конфигурации."""
    page = await service.list_entries(
        session,
        CatalogKind.ISSUE_TYPE,
        initiator=current_actor,
        queue=await _scope(session, queue),
        is_active=is_active,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[IssueTypeRead].of(
        [IssueTypeRead.of(entry) for entry in page.items],
        next_cursor=page.next_cursor,
    )


@issue_types_router.post("", status_code=status.HTTP_201_CREATED, summary="Create an issue type")
async def create_issue_type(
    payload: IssueTypeCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueTypeRead]:
    entry = await service.create_entry(
        session,
        CatalogKind.ISSUE_TYPE,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        queue=await _scope(session, payload.queue),
        icon=payload.icon,
    )
    return DataResponse[IssueTypeRead](data=IssueTypeRead.of(entry))


@issue_types_router.get("/{issue_type_ref}", summary="Read an issue type")
async def read_issue_type(
    issue_type_ref: IssueTypeRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueTypeRead]:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, issue_type_ref, initiator=current_actor
    )
    return DataResponse[IssueTypeRead](data=IssueTypeRead.of(entry))


@issue_types_router.patch("/{issue_type_ref}", summary="Update an issue type")
async def update_issue_type(
    issue_type_ref: IssueTypeRefPath,
    payload: IssueTypeUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueTypeRead]:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, issue_type_ref, initiator=current_actor
    )
    changes = payload.model_dump(exclude_unset=True)
    entry = await service.update_entry(
        session, entry, CatalogKind.ISSUE_TYPE, initiator=current_actor, **changes
    )
    return DataResponse[IssueTypeRead](data=IssueTypeRead.of(entry))


@issue_types_router.delete(
    "/{issue_type_ref}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an issue type",
)
async def delete_issue_type(
    issue_type_ref: IssueTypeRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Отклоняется, если тип используется задачами или выбран очередью по умолчанию.

    Разрешения «этот тип можно заводить в такой-то очереди» удаляются вместе с типом:
    без самого типа они ничего не значат.
    """
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, issue_type_ref, initiator=current_actor
    )
    await service.delete_entry(session, entry, CatalogKind.ISSUE_TYPE, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Резолюции -------------------------------------------------------------------


@resolutions_router.get("", summary="List resolutions")
async def list_resolutions(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueFilterQuery = None,
    is_active: ActiveFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ResolutionRead]:
    page = await service.list_entries(
        session,
        CatalogKind.RESOLUTION,
        initiator=current_actor,
        queue=await _scope(session, queue),
        is_active=is_active,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[ResolutionRead].of(
        [ResolutionRead.of(entry) for entry in page.items],
        next_cursor=page.next_cursor,
    )


@resolutions_router.post("", status_code=status.HTTP_201_CREATED, summary="Create a resolution")
async def create_resolution(
    payload: ResolutionCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ResolutionRead]:
    entry = await service.create_entry(
        session,
        CatalogKind.RESOLUTION,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        queue=await _scope(session, payload.queue),
    )
    return DataResponse[ResolutionRead](data=ResolutionRead.of(entry))


@resolutions_router.get("/{resolution_ref}", summary="Read a resolution")
async def read_resolution(
    resolution_ref: ResolutionRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ResolutionRead]:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.RESOLUTION, resolution_ref, initiator=current_actor
    )
    return DataResponse[ResolutionRead](data=ResolutionRead.of(entry))


@resolutions_router.patch("/{resolution_ref}", summary="Update a resolution")
async def update_resolution(
    resolution_ref: ResolutionRefPath,
    payload: ResolutionUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ResolutionRead]:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.RESOLUTION, resolution_ref, initiator=current_actor
    )
    changes = payload.model_dump(exclude_unset=True)
    entry = await service.update_entry(
        session, entry, CatalogKind.RESOLUTION, initiator=current_actor, **changes
    )
    return DataResponse[ResolutionRead](data=ResolutionRead.of(entry))


@resolutions_router.delete(
    "/{resolution_ref}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resolution",
)
async def delete_resolution(
    resolution_ref: ResolutionRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Отклоняется, если резолюцией закрыты задачи."""
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.RESOLUTION, resolution_ref, initiator=current_actor
    )
    await service.delete_entry(session, entry, CatalogKind.RESOLUTION, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


router.include_router(statuses_router)
router.include_router(issue_types_router)
router.include_router(resolutions_router)
