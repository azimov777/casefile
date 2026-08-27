"""Акторы и их токены доступа.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет,
иначе те же операции из MCP пошли бы другим путём.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentActorDep, SessionDep
from app.api.schemas.actors import (
    ActorCreate,
    ActorRead,
    ActorUpdate,
    ApiTokenCreate,
    ApiTokenIssued,
    ApiTokenRead,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.db.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.domain.actors import ActorType
from app.services import actors as service

router = APIRouter(prefix="/actors", tags=["actors"])

# Параметры пагинации объявлены через Annotated, а не значением по умолчанию:
# так требует современный стиль FastAPI, и заодно вызов Query не оказывается
# в списке аргументов, где он вычисляется один раз на всё приложение.
LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size")]
CursorQuery = Annotated[
    str | None, Query(description="Cursor from `meta.next_cursor` of a previous page")
]


@router.get("", summary="List actors")
async def list_actors(
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
    actor_type: Annotated[
        ActorType | None, Query(alias="type", description="Filter by actor type")
    ] = None,
    is_active: Annotated[bool | None, Query(description="Filter by activity flag")] = None,
) -> CollectionResponse[ActorRead]:
    page = await service.list_actors(
        session,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
        actor_type=actor_type,
        is_active=is_active,
    )
    return CollectionResponse[ActorRead].of(
        [ActorRead.model_validate(actor) for actor in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an actor")
async def create_actor(
    payload: ActorCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ActorRead]:
    actor = await service.create_actor(
        session,
        initiator=current_actor,
        actor_type=payload.type,
        key=payload.key,
        display_name=payload.display_name,
    )
    return DataResponse[ActorRead](data=ActorRead.model_validate(actor))


# Маршрут `/me` объявлен раньше `/{actor_key}`: FastAPI разбирает маршруты в порядке
# объявления, и ниже `me` был бы съеден как значение ключа.
@router.get("/me", summary="Actor behind the current token")
async def read_current_actor(current_actor: CurrentActorDep) -> DataResponse[ActorRead]:
    return DataResponse[ActorRead](data=ActorRead.model_validate(current_actor))


@router.get("/{actor_key}", summary="Read an actor")
async def read_actor(
    actor_key: str,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ActorRead]:
    actor = await service.read_actor(session, actor_key, initiator=current_actor)
    return DataResponse[ActorRead](data=ActorRead.model_validate(actor))


@router.patch("/{actor_key}", summary="Update an actor")
async def update_actor(
    actor_key: str,
    payload: ActorUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ActorRead]:
    """Меняет только переданные поля: непереданное остаётся как было."""
    actor = await service.get_actor_by_key(session, actor_key)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    actor = await service.update_actor(session, actor, initiator=current_actor, **changes)
    return DataResponse[ActorRead](data=ActorRead.model_validate(actor))


@router.get("/{actor_key}/tokens", summary="List actor tokens")
async def list_tokens(
    actor_key: str,
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ApiTokenRead]:
    """Включая отозванные: у отозванного токена заполнено `revoked_at`."""
    actor = await service.get_actor_by_key(session, actor_key)
    page = await service.list_tokens(
        session, actor, initiator=current_actor, limit=limit, cursor=cursor
    )
    return CollectionResponse[ApiTokenRead].of(
        [ApiTokenRead.model_validate(token) for token in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/{actor_key}/tokens",
    status_code=status.HTTP_201_CREATED,
    summary="Issue an API token",
)
async def issue_token(
    actor_key: str,
    payload: ApiTokenCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ApiTokenIssued]:
    """Единственный ответ, содержащий секрет токена. Повторно его получить нельзя."""
    actor = await service.get_actor_by_key(session, actor_key)
    issued = await service.issue_token(session, actor, initiator=current_actor, name=payload.name)
    body = ApiTokenIssued(
        **ApiTokenRead.model_validate(issued.token).model_dump(),
        secret=issued.secret,
    )
    return DataResponse[ApiTokenIssued](data=body)


@router.delete(
    "/{actor_key}/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API token",
)
async def revoke_token(
    actor_key: str,
    token_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Отзыв идемпотентен: повторный запрос отвечает так же и ничего не меняет.

    Запись токена остаётся в базе с проставленным `revoked_at` — по ней видно, чем
    ходили раньше. Наружу это выглядит удалением, поэтому метод `DELETE` и `204`.
    """
    actor = await service.get_actor_by_key(session, actor_key)
    await service.revoke_token(session, actor, token_id, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
