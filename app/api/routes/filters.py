"""Сохранённые фильтры: именованные запросы, которые переиспользуют фронт, MCP и автоматика.

Ресурс адресуется идентификатором, а не именем: имя уникально только у владельца, и путь
по имени пришлось бы дополнять владельцем — то есть двумя изменяемыми частями вместо
одной неизменной.

Запускается фильтр не отдельным маршрутом, а параметром поиска
(`GET /api/v1/search/issues?saved_filter=...`). Иначе выполнение фильтра и выполнение
запроса стали бы двумя разными путями с двумя наборами возможностей — например, без
выбора возвращаемых полей у первого.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.filters import SavedFilterCreate, SavedFilterRead, SavedFilterUpdate
from app.core.sentinels import UNSET
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import actors as actors_service
from app.services import saved_filters as service

router = APIRouter(prefix="/filters", tags=["filters"])

FilterIdPath = Annotated[uuid.UUID, Path(description="Saved filter UUID")]
OwnerQuery = Annotated[
    str | None,
    Query(description="Owner actor key: list this actor's filters only"),
]


@router.get("", summary="List saved filters")
async def list_saved_filters(
    session: SessionDep,
    current_actor: CurrentActorDep,
    owner: OwnerQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[SavedFilterRead]:
    """Страница фильтров в порядке создания.

    Без владельца отдаются все: в v1 ролей нет, фильтры общие, и список чужих — способ
    найти полезный фильтр, а не утечка.
    """
    page = await service.list_saved_filters(
        session,
        initiator=current_actor,
        owner=None if owner is None else await actors_service.get_actor_by_key(session, owner),
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[SavedFilterRead].of(
        [SavedFilterRead.of(saved) for saved in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a saved filter")
async def create_saved_filter(
    payload: SavedFilterCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SavedFilterRead]:
    """Заводит фильтр. Описание проверяется целиком: невыполнимый фильтр не сохраняется."""
    saved = await service.create_saved_filter(
        session,
        initiator=current_actor,
        name=payload.name,
        description=payload.description,
        query=payload.query,
        structured=(
            None if payload.filter is None else [term.to_term() for term in payload.filter]
        ),
        sort=payload.sort,
        owner=(
            None
            if payload.owner is None
            else await actors_service.get_actor_by_key(session, payload.owner)
        ),
    )
    return DataResponse[SavedFilterRead](data=SavedFilterRead.of(saved))


@router.get("/{filter_id}", summary="Read a saved filter")
async def read_saved_filter(
    filter_id: FilterIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SavedFilterRead]:
    """Сохранённый фильтр: имя, строка запроса и разобранные условия.

    Разобранные условия отдаются вместе со строкой затем, чтобы интерфейс мог показать
    фильтр конструктором, не разбирая язык запросов у себя.
    """
    saved = await service.read_saved_filter(session, filter_id, initiator=current_actor)
    return DataResponse[SavedFilterRead](data=SavedFilterRead.of(saved))


@router.patch("/{filter_id}", summary="Update a saved filter")
async def update_saved_filter(
    filter_id: FilterIdPath,
    payload: SavedFilterUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SavedFilterRead]:
    """Меняет только переданные поля. Источник отбора заменяется целиком.

    Передали `query` — фильтр стал текстовым и структурная часть снята; передали
    `filter` — наоборот. Держать оба описания сразу нельзя: вопрос «какое из них
    главное» ответа не имеет, и база это запрещает отдельной проверкой.
    """
    saved = await service.read_saved_filter(session, filter_id, initiator=current_actor)
    given = payload.model_dump(exclude_unset=True)
    updated = await service.update_saved_filter(
        session,
        saved,
        initiator=current_actor,
        name=given.get("name", UNSET),
        description=given.get("description", UNSET),
        query=given.get("query", UNSET),
        structured=([term.to_term() for term in payload.filter] if "filter" in given else UNSET),
        sort=given.get("sort", UNSET),
    )
    return DataResponse[SavedFilterRead](data=SavedFilterRead.of(updated))


@router.delete(
    "/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved filter",
)
async def delete_saved_filter(
    filter_id: FilterIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет фильтр насовсем: описание отбора истории не образует."""
    saved = await service.read_saved_filter(session, filter_id, initiator=current_actor)
    await service.delete_saved_filter(session, saved, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
