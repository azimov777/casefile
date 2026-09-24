"""Реестр проектов."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.projects import ProjectCreate, ProjectRead, ProjectUpdate
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import projects as service

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectKeyPath = Annotated[
    str,
    Path(description="Project key; matching ignores case", examples=["TRK"]),
]


@router.get("", summary="List projects")
async def list_projects(
    session: SessionDep,
    actor: ActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ProjectRead]:
    """Все проекты установки. Единственный уровень группировки: над ними ничего нет."""
    page = await service.list_projects(session, actor=actor, limit=limit, cursor=cursor)
    return CollectionResponse[ProjectRead].of(
        [ProjectRead.model_validate(project) for project in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a project")
async def create_project(
    payload: ProjectCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[ProjectRead]:
    """Заводит проект. Требует набора `main`.

    Ключ уникален без учёта регистра, хранится в верхнем и дальше неизменяем: он идёт
    в ключ каждой задачи проекта. Повтор с тем же `Idempotency-Key` отвечает первым
    проектом, а не `409 project_key_taken`.
    """

    async def create() -> DataResponse[ProjectRead]:
        project = await service.create_project(
            session,
            actor=actor,
            key=payload.key,
            title=payload.title,
            description=payload.description,
        )
        return DataResponse[ProjectRead](data=ProjectRead.model_validate(project))

    return await once.run(DataResponse[ProjectRead], request=payload, build=create)


@router.get("/{project_key}", summary="Read a project")
async def read_project(
    project_key: ProjectKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ProjectRead]:
    """Карточка проекта вместе с описанием — общим контекстом всех его задач.

    Агент запрашивает её отдельно: в карточке задачи лежат только ключ и название, а
    описание бывает длинным, и таскать его в каждом ответе значило бы тратить контекст.
    """
    project = await service.read_project(session, project_key, actor=actor)
    return DataResponse[ProjectRead](data=ProjectRead.model_validate(project))


@router.patch("/{project_key}", summary="Update a project")
async def update_project(
    project_key: ProjectKeyPath,
    payload: ProjectUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ProjectRead]:
    """Меняет название и описание; ключ неизменяем. Требует набора `main`.

    Поле `key` в теле — ошибка `422`, а не молчаливый пропуск: клиент должен узнать,
    что переименования не произошло, из ответа, а не из следующего чтения.
    """
    project = await service.get_project(session, project_key)
    # `exclude_unset` — единственный фильтр: явный `null` схема уже отвергла,
    # поэтому «не передано» здесь не может притвориться «передано как null».
    changes = payload.model_dump(exclude_unset=True)
    project = await service.update_project(session, project, actor=actor, **changes)
    return DataResponse[ProjectRead](data=ProjectRead.model_validate(project))
