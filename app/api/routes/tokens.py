"""Токены доступа.

Ресурс верхнего уровня, а не подресурс участника: у общего агентского токена участника
нет вовсе, и путь `/participants/{name}/tokens` было бы нечем заполнить.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.tokens import TokenCreate, TokenIssued, TokenRead
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import participants as participants_service
from app.services import tokens as service

router = APIRouter(prefix="/tokens", tags=["tokens"])

TokenIdPath = Annotated[uuid.UUID, Path(description="Identifier of the token to revoke")]
MineQuery = Annotated[
    bool,
    Query(
        description=(
            "Only own tokens: those that speak for the caller or were issued by the caller. "
            "Changes nothing for a non-administrator, who sees only own tokens anyway"
        ),
    ),
]


@router.get("", summary="List tokens")
async def list_tokens(
    session: SessionDep,
    actor: ActorDep,
    mine: MineQuery = False,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[TokenRead]:
    """Токены, включая отозванные: у отозванного заполнено `revoked_at`.

    Администратор видит все токены установки, остальные — свои: те, что говорят от их
    имени (`participant`), и те, что они выпустили (`created_by`). `mine=true` сужает до
    своих и администратора.

    Секрета в списке нет — в базе лежит только хеш, и восстановить значение неоткуда.
    """
    page = await service.list_tokens(session, actor=actor, mine=mine, limit=limit, cursor=cursor)
    return CollectionResponse[TokenRead].of(
        [TokenRead.model_validate(token) for token in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Issue a token")
async def issue_token(
    payload: TokenCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[TokenIssued]:
    """Единственный ответ, содержащий секрет токена: второго способа узнать его нет.

    Требует набора `main` и учётной записи у выпускающего: выпускает человек, а не агент
    (`403 permission_denied`, `details.reason: account_required`). Ключ от имени другого
    человека выпускает только администратор (`details.reason: foreign_human`); себе,
    агенту-участнику и общий — любой вошедший. Выпущенный токен — свой у выпустившего: он
    видит его в списке и отзывает. Без `participant` выпускается общий агентский токен:
    запрос с ним обязан нести заголовок `X-Actor-Label`, иначе действие некому приписать.

    Единственное исключение — повтор с тем же `Idempotency-Key`: он отвечает **тем же**
    секретом, потому что ответ первого выпуска сохранён целиком. Иначе повтор запроса,
    оборвавшегося по сети, оставлял бы действующий токен, которого никто не видел.
    Сутки спустя ключ забыт вместе с ответом, и секрета не остаётся нигде.
    """
    participant = (
        None
        if payload.participant is None
        else await participants_service.get_participant(session, payload.participant)
    )

    async def issue() -> DataResponse[TokenIssued]:
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

    return await once.run(
        DataResponse[TokenIssued],
        request={
            "participant": None if participant is None else participant.name,
            "scope": payload.scope,
            "name": payload.name,
        },
        build=issue,
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a token")
async def revoke_token(
    token_id: TokenIdPath,
    session: SessionDep,
    actor: ActorDep,
) -> Response:
    """Отзыв идемпотентен: повторный запрос отвечает так же и ничего не меняет.

    Требует набора `main`. Свой токен отзывает любой, чужой — только администратор
    (`403 permission_denied`, `details.reason: not_own_token`). Запись токена остаётся в
    базе с проставленным `revoked_at` — по ней видно, чем ходили раньше. Наружу это
    выглядит удалением, поэтому `DELETE` и `204`.
    """
    await service.revoke_token(session, token_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
