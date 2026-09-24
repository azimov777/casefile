"""Реестр проектов и дело проекта.

Маршрутов правки и удаления записей дела проекта нет и не будет: записи неизменяемы,
как и у задачи.
"""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import (
    ActorDep,
    AfterNoQuery,
    CursorQuery,
    EntryNosQuery,
    EntryTypesQuery,
    LimitQuery,
    SessionDep,
)
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.entries import EntryRead, ProjectEntryCreate, entry_read
from app.api.schemas.projects import ProjectCreate, ProjectRead, ProjectUpdate
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import case as case_service
from app.services import projects as service

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectKeyPath = Annotated[
    str,
    Path(description="Project key; matching ignores case", examples=["TRK"]),
]

ProjectEntryNoPath = Annotated[
    int,
    Path(ge=1, description="Entry number inside the project, from 1", examples=[7]),
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


@router.post(
    "/{project_key}/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Append a project case entry",
)
async def create_project_entry(
    project_key: ProjectKeyPath,
    entry: ProjectEntryCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Подшивает запись в дело проекта: заметку, решение, находку или артефакт.

    Набор `task`, как у записей дела задачи. Номер `no` считается внутри проекта, ссылка
    на запись — `TRK#7`. Типы задачи (`summary`, `question`, `verdict`, ...) в деле
    проекта не принимаются, служебные (`created`, `field_changed`) подшивает сам трекер.
    Замечания к форме и ссылкам приходят разом в `422 entry_fields_invalid`. Записи
    неизменяемы.

    Повтор с тем же `Idempotency-Key` отвечает первой записью, а не подшивает вторую.
    """
    project = await service.get_project(session, project_key)
    given = entry.model_dump(mode="json")

    async def append() -> DataResponse[EntryRead]:
        appended = await case_service.append_project_entry(
            session,
            project,
            actor=actor,
            type=given["type"],
            title=given["title"],
            body=given["body"],
            refs=given["refs"],
        )
        return DataResponse[EntryRead](data=entry_read(appended, project_key=project.key))

    return await once.run(
        DataResponse[EntryRead],
        request={"project": project.key, "entry": given},
        build=append,
    )


@router.get("/{project_key}/entries", summary="Read project case entries")
async def list_project_entries(
    project_key: ProjectKeyPath,
    session: SessionDep,
    actor: ActorDep,
    nos: EntryNosQuery = None,
    types: EntryTypesQuery = None,
    after_no: AfterNoQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[EntryRead]:
    """Записи дела проекта с телами и нагрузкой, в порядке `no`.

    Фильтры те же, что у дела задачи, и складываются по «и»: `types` сужает по типу,
    `after_no` — «что случилось после названной записи». `after_no` и `cursor` действуют
    оба, побеждает больший.
    """
    project = await service.get_project(session, project_key)
    page = await case_service.list_project_entries(
        session,
        project,
        actor=actor,
        nos=nos,
        types=types,
        after_no=after_no,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[EntryRead].of(
        [entry_read(entry, project_key=project.key) for entry in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{project_key}/entries/{entry_no}", summary="Read one project case entry")
async def read_project_entry(
    project_key: ProjectKeyPath,
    entry_no: ProjectEntryNoPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[EntryRead]:
    """Одна запись дела проекта по номеру — адрес из ссылки `TRK#7`.

    Номера, которого в деле проекта нет, — `404 entry_not_found`.
    """
    project = await service.get_project(session, project_key)
    entry = await case_service.read_project_entry(session, project, entry_no, actor=actor)
    return DataResponse[EntryRead](data=entry_read(entry, project_key=project.key))
