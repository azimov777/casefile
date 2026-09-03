"""Реестр очередей."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.queues import QueueCreate, QueueRead, QueueUpdate
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import queues as service

router = APIRouter(prefix="/queues", tags=["queues"])

QueueKeyPath = Annotated[
    str,
    Path(description="Queue key; matching ignores case", examples=["TRK"]),
]


@router.get("", summary="List queues")
async def list_queues(
    session: SessionDep,
    actor: ActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[QueueRead]:
    """Все очереди установки. Единственный уровень группировки: над ними ничего нет."""
    page = await service.list_queues(session, actor=actor, limit=limit, cursor=cursor)
    return CollectionResponse[QueueRead].of(
        [QueueRead.model_validate(queue) for queue in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a queue")
async def create_queue(
    payload: QueueCreate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[QueueRead]:
    """Заводит очередь. Требует набора `main`.

    Ключ уникален без учёта регистра, хранится в верхнем и дальше неизменяем: он идёт
    в ключ каждой задачи очереди.
    """
    queue = await service.create_queue(
        session,
        actor=actor,
        key=payload.key,
        title=payload.title,
        description=payload.description,
    )
    return DataResponse[QueueRead](data=QueueRead.model_validate(queue))


@router.get("/{queue_key}", summary="Read a queue")
async def read_queue(
    queue_key: QueueKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[QueueRead]:
    """Карточка очереди вместе с описанием — общим контекстом всех её задач.

    Агент запрашивает её отдельно: в карточке задачи лежат только ключ и название, а
    описание бывает длинным, и таскать его в каждом ответе значило бы тратить контекст.
    """
    queue = await service.read_queue(session, queue_key, actor=actor)
    return DataResponse[QueueRead](data=QueueRead.model_validate(queue))


@router.patch("/{queue_key}", summary="Update a queue")
async def update_queue(
    queue_key: QueueKeyPath,
    payload: QueueUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[QueueRead]:
    """Меняет название и описание; ключ неизменяем. Требует набора `main`.

    Поле `key` в теле — ошибка `422`, а не молчаливый пропуск: клиент должен узнать,
    что переименования не произошло, из ответа, а не из следующего чтения.
    """
    queue = await service.get_queue(session, queue_key)
    # `exclude_unset` — единственный фильтр: явный `null` схема уже отвергла,
    # поэтому «не передано» здесь не может притвориться «передано как null».
    changes = payload.model_dump(exclude_unset=True)
    queue = await service.update_queue(session, queue, actor=actor, **changes)
    return DataResponse[QueueRead](data=QueueRead.model_validate(queue))
