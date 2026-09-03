"""Реестр участников.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет,
иначе те же операции из MCP пошли бы другим путём.
"""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.participants import ParticipantCreate, ParticipantRead, ParticipantUpdate
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import participants as service

router = APIRouter(prefix="/participants", tags=["participants"])

ParticipantNamePath = Annotated[
    str,
    Path(
        description="Participant name; matching ignores case",
        examples=["release_bot"],
    ),
]


@router.get("", summary="List participants")
async def list_participants(
    session: SessionDep,
    actor: ActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ParticipantRead]:
    """Все участники установки: люди и постоянные агенты.

    Один список без разделения по роду: адресовать вопрос можно и человеку, и агенту, и
    интерфейсу нужен общий выбор. Временных агентов здесь нет и быть не может — они не
    регистрируются, и адресовать их нельзя.
    """
    page = await service.list_participants(session, actor=actor, limit=limit, cursor=cursor)
    return CollectionResponse[ParticipantRead].of(
        [ParticipantRead.model_validate(participant) for participant in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Register a participant")
async def register_participant(
    payload: ParticipantCreate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ParticipantRead]:
    """Заводит человека или постоянного агента. Токен ему выпускается отдельным запросом.

    Требует набора `main`. Имя уникально без учёта регистра и дальше неизменяемо: оно
    стоит подписью в записях дела, и переименование порвало бы эти подписи задним числом.
    """
    participant = await service.register_participant(
        session,
        actor=actor,
        kind=payload.kind,
        name=payload.name,
        description=payload.description,
    )
    return DataResponse[ParticipantRead](data=ParticipantRead.model_validate(participant))


@router.get("/{participant_name}", summary="Read a participant")
async def read_participant(
    participant_name: ParticipantNamePath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ParticipantRead]:
    """Карточка участника по имени. Адресация мягкая: `Alice` находит `alice`."""
    participant = await service.read_participant(session, participant_name, actor=actor)
    return DataResponse[ParticipantRead](data=ParticipantRead.model_validate(participant))


@router.patch("/{participant_name}", summary="Update a participant")
async def update_participant(
    participant_name: ParticipantNamePath,
    payload: ParticipantUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ParticipantRead]:
    """Меняет описание участника; имя и род неизменяемы. Требует набора `main`."""
    participant = await service.get_participant(session, participant_name)
    # `exclude_unset` — единственный фильтр: явный `null` схема уже отвергла,
    # поэтому «не передано» здесь не может притвориться «передано как null».
    changes = payload.model_dump(exclude_unset=True)
    participant = await service.update_participant(session, participant, actor=actor, **changes)
    return DataResponse[ParticipantRead](data=ParticipantRead.model_validate(participant))
