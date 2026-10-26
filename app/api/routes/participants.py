"""Реестр участников.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет,
иначе те же операции из MCP пошли бы другим путём.
"""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.participants import (
    ParticipantCreate,
    ParticipantRead,
    ProjectAccessRead,
    ProjectAccessWrite,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import participants as service
from app.services import project_access as access_service

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
    once: OnceDep,
) -> DataResponse[ParticipantRead]:
    """Заводит человека или постоянного агента. Токен ему выпускается отдельным запросом.

    Имя уникально без учёта регистра и дальше неизменяемо: оно
    стоит подписью в записях дела, и переименование порвало бы эти подписи задним числом.
    Повтор с тем же `Idempotency-Key` отвечает первым участником, а не `409
    participant_name_taken`.
    """

    async def register() -> DataResponse[ParticipantRead]:
        participant = await service.register_participant(
            session,
            actor=actor,
            kind=payload.kind,
            name=payload.name,
            description=payload.description,
        )
        return DataResponse[ParticipantRead](data=ParticipantRead.model_validate(participant))

    return await once.run(DataResponse[ParticipantRead], request=payload, build=register)


def _access_response(view: access_service.AgentProjectAccess) -> DataResponse[ProjectAccessRead]:
    return DataResponse[ProjectAccessRead](
        data=ProjectAccessRead(mode=view.mode, projects=[project.key for project in view.projects])
    )


@router.get("/{participant_name}/projects", summary="Read the project access of an agent")
async def read_project_access(
    participant_name: ParticipantNamePath, session: SessionDep, actor: ActorDep
) -> DataResponse[ProjectAccessRead]:
    """Режим доступа агента к проектам и список проектов.

    Читает человек с учётной записью, которому доступен агент; агенту доступ закрыт
    (`account_required`). У человека ограничений нет: читается `all` и пустой список.
    """
    return _access_response(
        await access_service.read_project_access(session, participant_name, actor=actor)
    )


@router.put("/{participant_name}/projects", summary="Set the project access of an agent")
async def set_project_access(
    participant_name: ParticipantNamePath,
    payload: ProjectAccessWrite,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ProjectAccessRead]:
    """Заменяет режим и список проектов агента целиком.

    Режим `all` открывает все проекты, в том числе заведённые позже, и очищает список;
    `except` закрывает перечисленные; `only` открывает только перечисленные, а проект,
    созданный самим агентом, попадает в список сразу. Закрытый проект исчезает у агента из
    списков, поиска, ленты и входящей, а по прямому адресу отвечает `project_not_allowed`.
    Токен не меняется: доступ стоит на участнике. Настраивает человек с учётной записью,
    которому доступен агент: чужого агента - только администратор (`agent_owned_by_another`),
    агент себе доступ не меняет (`account_required`).
    """
    return _access_response(
        await access_service.set_project_access(
            session, participant_name, actor=actor, mode=payload.mode, project_keys=payload.projects
        )
    )
