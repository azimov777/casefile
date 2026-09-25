"""Реестр проектов и дело проекта.

Маршрутов правки и удаления записей дела проекта нет и не будет: записи неизменяемы,
как и у задачи.
"""

from typing import Annotated

from fastapi import APIRouter, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ActorDep,
    AfterNoQuery,
    CursorQuery,
    EntryNosQuery,
    EntryTypesQuery,
    IncludeArchivedQuery,
    LimitQuery,
    SessionDep,
)
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.entries import EntryRead, ProjectEntryCreate, entry_read
from app.api.schemas.projects import (
    AttributeRead,
    AttributeRemoval,
    AttributeSet,
    ProjectArchiving,
    ProjectCreate,
    ProjectDetailRead,
    ProjectRead,
    ProjectUpdate,
)
from app.db.models.project import Project
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import projects as service
from app.services.auth import Actor

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectKeyPath = Annotated[
    str,
    Path(description="Project key; matching ignores case", examples=["TRK"]),
]

AttributeNamePath = Annotated[
    str,
    Path(
        description=(
            "Attribute name: Latin letters, digits, `_` and `-`, at most 64 characters; "
            "matching ignores case"
        ),
        examples=["repo"],
    ),
]

ProjectEntryNoPath = Annotated[
    int,
    Path(ge=1, description="Entry number inside the project, from 1", examples=[7]),
]


@router.get("", summary="List projects")
async def list_projects(
    session: SessionDep,
    actor: ActorDep,
    include_archived: IncludeArchivedQuery = False,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ProjectRead]:
    """Проекты установки. Единственный уровень группировки: над ними ничего нет.

    Архивные — только с `include_archived=true`; по ключу архивный проект читается и без
    него (`GET /api/v1/projects/{key}`).
    """
    page = await service.list_projects(
        session, actor=actor, include_archived=include_archived, limit=limit, cursor=cursor
    )
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

    # Ответ без атрибутов: у нового проекта их нет, а форма ответа создающего вызова
    # живёт сутки в ключах идемпотентности, и расширять её нельзя (`docs/notes/mcp.md`).
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
) -> DataResponse[ProjectDetailRead]:
    """Карточка проекта вместе с описанием и нынешними значениями атрибутов.

    Описание едет и в карточке задачи; атрибуты — только здесь: их число не ограничено, и
    таскать их в каждой задаче значило бы тратить контекст. История атрибутов — записи
    дела проекта (`/projects/{key}/entries`).
    """
    project = await service.read_project(session, project_key, actor=actor)
    return await _detail(session, project, actor=actor)


@router.patch("/{project_key}", summary="Update a project")
async def update_project(
    project_key: ProjectKeyPath,
    payload: ProjectUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ProjectDetailRead]:
    """Меняет название и описание; ключ неизменяем. Требует набора `main`.

    Поле `key` в теле — ошибка `422`, а не молчаливый пропуск: клиент должен узнать,
    что переименования не произошло, из ответа, а не из следующего чтения.
    """
    project = await service.get_project(session, project_key)
    # `exclude_unset` — единственный фильтр: явный `null` схема уже отвергла,
    # поэтому «не передано» здесь не может притвориться «передано как null».
    changes = payload.model_dump(exclude_unset=True)
    project = await service.update_project(session, project, actor=actor, **changes)
    return await _detail(session, project, actor=actor)


@router.post("/{project_key}/archive", summary="Archive a project")
async def archive_project(
    project_key: ProjectKeyPath,
    payload: ProjectArchiving,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ProjectDetailRead]:
    """Архивирует проект с причиной. Требует набора `main`.

    Проект и его задачи замораживаются как есть: закрывать задачи не нужно, статусы не
    меняются. Дальше любое изменение в проекте и его задачах — новая задача, запись в
    дело, переход, правка, атрибут, новая связь — отвечает `409 project_archived`;
    снять связь с его задачей можно. Чтение работает как раньше. Причина уезжает в
    запись `archived` дела проекта; пустая — `422 project_reason_required`. Проект уже в
    архиве — `409 project_archived`.
    """
    project = await service.get_project(session, project_key)
    await service.archive_project(session, project, actor=actor, reason=payload.reason)
    return await _detail(session, project, actor=actor)


@router.post("/{project_key}/restore", summary="Restore an archived project")
async def restore_project(
    project_key: ProjectKeyPath,
    payload: ProjectArchiving,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[ProjectDetailRead]:
    """Восстанавливает проект из архива с причиной. Требует набора `main`.

    Задачи продолжаются с того места, где их застал архив. Причина уезжает в запись
    `restored` дела проекта; пустая — `422 project_reason_required`. Проект не в архиве —
    `409 project_not_archived`.
    """
    project = await service.get_project(session, project_key)
    await service.restore_project(session, project, actor=actor, reason=payload.reason)
    return await _detail(session, project, actor=actor)


@router.put("/{project_key}/attributes/{attribute_name}", summary="Set a project attribute")
async def set_project_attribute(
    project_key: ProjectKeyPath,
    attribute_name: AttributeNamePath,
    payload: AttributeSet,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[AttributeRead]:
    """Заводит атрибут проекта или меняет его значение. Набор `task`.

    Одно действие на оба случая, запись выбирает трекер: атрибута с таким именем (без
    учёта регистра) нет — `attribute_created`, причина необязательна; есть с другим
    значением — `attribute_changed`, без причины `422 attribute_reason_required`; есть с
    тем же значением — ничего не подшивается. Имя хранится так, как его завели, и другое
    написание его не меняет. Имя не по шаблону — `422 invalid_attribute_name`, значение
    длиннее предела — `422 attribute_value_too_long`.

    Повтор с тем же `Idempotency-Key` отвечает первым результатом и не применяет
    значение второй раз поверх чужой правки.
    """
    project = await service.get_project(session, project_key)
    given = payload.model_dump()

    async def put() -> DataResponse[AttributeRead]:
        result = await attributes_service.set_attribute(
            session,
            project,
            actor=actor,
            name=attribute_name,
            value=given["value"],
            reason=given["reason"],
        )
        return DataResponse[AttributeRead](data=AttributeRead.model_validate(result.attribute))

    return await once.run(
        DataResponse[AttributeRead],
        request={"project": project.key, "name": attribute_name.lower(), "attribute": given},
        build=put,
    )


@router.post(
    "/{project_key}/attributes/{attribute_name}/remove",
    summary="Remove a project attribute",
)
async def remove_project_attribute(
    project_key: ProjectKeyPath,
    attribute_name: AttributeNamePath,
    payload: AttributeRemoval,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Снимает атрибут проекта с причиной и отдаёт подшитую запись `attribute_removed`.

    Набор `task`. Действие, а не `DELETE`: причина обязательна, а тело у `DELETE` клиенты
    и посредники теряют. Атрибута с таким именем (без учёта регистра) нет — `404
    attribute_not_found`, пустая причина — `422 attribute_reason_required`. Запись хранит
    последнее значение: снятый атрибут восстанавливается из дела, а не из корзины.

    Повтор с тем же `Idempotency-Key` отвечает первой записью, а не `404`.
    """
    project = await service.get_project(session, project_key)
    given = payload.model_dump()

    async def remove() -> DataResponse[EntryRead]:
        entry = await attributes_service.remove_attribute(
            session, project, actor=actor, name=attribute_name, reason=given["reason"]
        )
        return DataResponse[EntryRead](data=entry_read(entry, project_key=project.key))

    return await once.run(
        DataResponse[EntryRead],
        request={"project": project.key, "name": attribute_name.lower(), "removal": given},
        build=remove,
    )


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


async def _detail(
    session: AsyncSession, project: Project, *, actor: Actor
) -> DataResponse[ProjectDetailRead]:
    """Проект с атрибутами: тот же ответ у чтения, заведения и правки карточки."""
    attributes = await attributes_service.list_attributes(session, project, actor=actor)
    return DataResponse[ProjectDetailRead](
        data=ProjectDetailRead.model_validate(
            {
                **ProjectRead.model_validate(project).model_dump(),
                "attributes": [AttributeRead.model_validate(item) for item in attributes],
            }
        )
    )
