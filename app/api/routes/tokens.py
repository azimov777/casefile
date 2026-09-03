"""Токены доступа.

Ресурс верхнего уровня, а не подресурс участника: у общего агентского токена участника
нет вовсе, и путь `/participants/{name}/tokens` было бы нечем заполнить.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.tokens import TokenCreate, TokenIssued, TokenRead
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import participants as participants_service
from app.services import tokens as service

router = APIRouter(prefix="/tokens", tags=["tokens"])

TokenIdPath = Annotated[uuid.UUID, Path(description="Identifier of the token to revoke")]


@router.get("", summary="List tokens")
async def list_tokens(
    session: SessionDep,
    actor: ActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[TokenRead]:
    """Все токены установки, включая отозванные: у отозванного заполнено `revoked_at`.

    Секрета в списке нет — в базе лежит только хеш, и восстановить значение неоткуда.
    """
    page = await service.list_tokens(session, actor=actor, limit=limit, cursor=cursor)
    return CollectionResponse[TokenRead].of(
        [TokenRead.model_validate(token) for token in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Issue a token")
async def issue_token(
    payload: TokenCreate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TokenIssued]:
    """Единственный ответ, содержащий секрет токена. Повторно его получить нельзя.

    Требует набора `main`. Без `participant` выпускается общий агентский токен: запрос с
    ним обязан нести заголовок `X-Actor-Label`, иначе действие некому приписать.
    """
    participant = (
        None
        if payload.participant is None
        else await participants_service.get_participant(session, payload.participant)
    )
    issued = await service.issue_token(
        session,
        actor=actor,
        participant=participant,
        scope=payload.scope,
        name=payload.name,
    )
    body = TokenIssued(
        **TokenRead.model_validate(issued.token).model_dump(),
        secret=issued.secret,
    )
    return DataResponse[TokenIssued](data=body)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a token")
async def revoke_token(
    token_id: TokenIdPath,
    session: SessionDep,
    actor: ActorDep,
) -> Response:
    """Отзыв идемпотентен: повторный запрос отвечает так же и ничего не меняет.

    Требует набора `main`. Запись токена остаётся в базе с проставленным `revoked_at` —
    по ней видно, чем ходили раньше. Наружу это выглядит удалением, поэтому `DELETE`
    и `204`.
    """
    await service.revoke_token(session, token_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
