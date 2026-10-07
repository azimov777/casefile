"""Направления проекта: карточка, атрибуты, дело и архив (`CONCEPT.md`, 3.7).

Ресурс внутри проекта: `/projects/{project_key}/directions/{direction_key}`. Адрес
направления — `TRK/promotion` — собран из двух сегментов пути, а не одним: косая черта в
сегменте потребовала бы экранирования. Атрибуты, дело и архив — те же сценарии, что у
проекта (`app/services/attributes.py`, `app/services/case.py`), с направлением владельцем.

Маршрутов правки и удаления записей дела нет и не будет: записи неизменяемы.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ActorDep,
    AfterNoQuery,
    AttributeNamePath,
    AttributeQuery,
    CursorQuery,
    EntryNosQuery,
    EntryTextQuery,
    EntryTypesQuery,
    LimitQuery,
    ProjectKeyPath,
    SessionDep,
)
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.directions import (
    DirectionArchiving,
    DirectionCreate,
    DirectionDetailRead,
    DirectionRead,
    DirectionUpdate,
    direction_read,
)
from app.api.schemas.entries import DirectionEntryCreate, EntryRead, entry_read
from app.api.schemas.projects import AttributeRead, AttributeRemoval, AttributeSet
from app.db.models.direction import Direction
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.directions import format_direction_address
from app.domain.projects import normalize_project_key
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import directions as service
from app.services import projects as projects_service
from app.services.auth import Actor

router = APIRouter(prefix="/projects/{project_key}/directions", tags=["directions"])

DirectionKeyPath = Annotated[
    str,
    Path(
        description="Direction key inside the project; matching ignores case",
        examples=["promotion"],
    ),
]

IncludeArchivedDirectionsQuery = Annotated[
    bool,
    Query(
        description=(
            "Also list archived directions. Without it they are hidden from the list; a "
            "direction is still read by its address either way"
        )
    ),
]

DirectionEntryNoPath = Annotated[
    int,
    Path(ge=1, description="Entry number inside the direction, from 1", examples=[3]),
]


async def _direction(session: AsyncSession, project_key: str, direction_key: str) -> Direction:
    """Направление по двум сегментам пути — тем же поиском, что по адресу."""
    return await service.get_direction(
        session, format_direction_address(project_key, direction_key)
    )


@router.get("", summary="List the directions of a project")
async def list_directions(
    project_key: ProjectKeyPath,
    session: SessionDep,
    actor: ActorDep,
    include_archived: IncludeArchivedDirectionsQuery = False,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[DirectionRead]:
    """Направления проекта. Архивные — только с `include_archived=true`; по адресу
    архивное направление читается и без него."""
    project = await projects_service.get_project(session, project_key)
    page = await service.list_directions_page(
        session,
        project,
        actor=actor,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[DirectionRead].of(
        [direction_read(item) for item in page.items], next_cursor=page.next_cursor
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a direction")
async def create_direction(
    project_key: ProjectKeyPath,
    payload: DirectionCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[DirectionRead]:
    """Заводит направление в проекте; первая запись его дела — `created`.

    Ключ хранится в нижнем регистре и неизменяем; занятый в проекте (без учёта регистра)
    — `409 direction_key_taken`, не по шаблону — `422 invalid_direction_key`. В архивный
    проект направление не заводится — `409 project_archived`. Повтор с тем же
    `Idempotency-Key` отвечает первым направлением, а не `409`.
    """

    # Ответ без атрибутов: у нового направления их нет, а форма ответа создающего вызова
    # живёт сутки в ключах идемпотентности, и расширять её нельзя (`docs/notes/mcp.md`).
    async def create() -> DataResponse[DirectionRead]:
        direction = await service.create_direction(
            session,
            actor=actor,
            address=format_direction_address(project_key, payload.key),
            title=payload.title,
            description=payload.description,
        )
        return DataResponse[DirectionRead](data=direction_read(direction))

    return await once.run(
        DataResponse[DirectionRead],
        request={"project": normalize_project_key(project_key), "direction": payload},
        build=create,
    )


@router.get("/{direction_key}", summary="Read a direction")
async def read_direction(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[DirectionDetailRead]:
    """Карточка направления с нынешними значениями атрибутов. История атрибутов и всё
    остальное дело — `/projects/{key}/directions/{direction}/entries`."""
    direction = await _direction(session, project_key, direction_key)
    return await _detail(session, direction, actor=actor)


@router.patch("/{direction_key}", summary="Update a direction")
async def update_direction(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    payload: DirectionUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[DirectionDetailRead]:
    """Меняет название и описание; проект и ключ неизменяемы, поле `key` в теле — `422`.

    Каждое изменённое поле подшивает `field_changed` в дело направления. Архивное
    направление — `409 direction_archived`, архивный проект — `409 project_archived`.
    """
    direction = await _direction(session, project_key, direction_key)
    changes = payload.model_dump(exclude_unset=True)
    direction = await service.update_direction(session, direction, actor=actor, **changes)
    return await _detail(session, direction, actor=actor)


@router.post("/{direction_key}/archive", summary="Archive a direction")
async def archive_direction(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    payload: DirectionArchiving,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[DirectionDetailRead]:
    """Архивирует направление с причиной: карточка, атрибуты и дело замораживаются
    (`409 direction_archived` на любое изменение, кроме восстановления). Причина — в записи
    `archived`; пустая — `422 direction_reason_required`. Уже в архиве —
    `409 direction_archived`, проект в архиве — `409 project_archived`.
    """
    direction = await _direction(session, project_key, direction_key)
    await service.archive_direction(session, direction, actor=actor, reason=payload.reason)
    return await _detail(session, direction, actor=actor)


@router.post("/{direction_key}/restore", summary="Restore an archived direction")
async def restore_direction(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    payload: DirectionArchiving,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[DirectionDetailRead]:
    """Восстанавливает направление из архива с причиной (запись `restored`). Не в архиве —
    `409 direction_not_archived`; проект в архиве — `409 project_archived`: сначала
    восстанавливают проект."""
    direction = await _direction(session, project_key, direction_key)
    await service.restore_direction(session, direction, actor=actor, reason=payload.reason)
    return await _detail(session, direction, actor=actor)


@router.put("/{direction_key}/attributes/{attribute_name}", summary="Set a direction attribute")
async def set_direction_attribute(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    attribute_name: AttributeNamePath,
    payload: AttributeSet,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[AttributeRead]:
    """Заводит атрибут направления или меняет его значение — правила атрибута проекта.

    Атрибута нет — `attribute_created`, причина необязательна; есть с другим значением —
    `attribute_changed`, без причины `422 attribute_reason_required`; то же значение —
    ничего не подшивается. Записи ложатся в дело направления.
    """
    direction = await _direction(session, project_key, direction_key)
    given = payload.model_dump()

    async def put() -> DataResponse[AttributeRead]:
        result = await attributes_service.set_attribute(
            session,
            direction,
            actor=actor,
            name=attribute_name,
            value=given["value"],
            reason=given["reason"],
        )
        return DataResponse[AttributeRead](data=AttributeRead.model_validate(result.attribute))

    return await once.run(
        DataResponse[AttributeRead],
        request={
            "direction": direction.address,
            "name": attribute_name.lower(),
            "attribute": given,
        },
        build=put,
    )


@router.post(
    "/{direction_key}/attributes/{attribute_name}/remove",
    summary="Remove a direction attribute",
)
async def remove_direction_attribute(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    attribute_name: AttributeNamePath,
    payload: AttributeRemoval,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Снимает атрибут направления с причиной и отдаёт подшитую `attribute_removed`.

    Атрибута нет — `404 attribute_not_found`, пустая причина —
    `422 attribute_reason_required`. Повтор с тем же `Idempotency-Key` отвечает первой
    записью, а не `404`.
    """
    direction = await _direction(session, project_key, direction_key)
    given = payload.model_dump()

    async def remove() -> DataResponse[EntryRead]:
        entry = await attributes_service.remove_attribute(
            session, direction, actor=actor, name=attribute_name, reason=given["reason"]
        )
        return DataResponse[EntryRead](data=entry_read(entry, direction=direction.address))

    return await once.run(
        DataResponse[EntryRead],
        request={"direction": direction.address, "name": attribute_name.lower(), "removal": given},
        build=remove,
    )


@router.post(
    "/{direction_key}/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Append a direction case entry",
)
async def create_direction_entry(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    entry: DirectionEntryCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Подшивает запись в дело направления: заметку, решение, находку или артефакт.

    Номер `no` считается внутри направления, ссылка на запись — `TRK/promotion#3`.
    `supersedes` здесь нет: механика решений проекта на дело направления не
    распространяется. Замечания к форме и ссылкам — разом в `422 entry_fields_invalid`.
    Архивное направление — `409 direction_archived`.
    """
    direction = await _direction(session, project_key, direction_key)
    given = entry.model_dump(mode="json")

    async def append() -> DataResponse[EntryRead]:
        appended = await case_service.append_project_entry(
            session,
            direction,
            actor=actor,
            type=given["type"],
            title=given["title"],
            body=given["body"],
            refs=given["refs"],
        )
        return DataResponse[EntryRead](data=entry_read(appended, direction=direction.address))

    return await once.run(
        DataResponse[EntryRead],
        request={"direction": direction.address, "entry": given},
        build=append,
    )


@router.get("/{direction_key}/entries", summary="Read direction case entries")
async def list_direction_entries(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    session: SessionDep,
    actor: ActorDep,
    nos: EntryNosQuery = None,
    types: EntryTypesQuery = None,
    attribute: AttributeQuery = None,
    text: EntryTextQuery = None,
    after_no: AfterNoQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[EntryRead]:
    """Записи дела направления с телами и нагрузкой, в порядке `no` — те же фильтры, что у
    дела проекта, включая историю одного атрибута (`attribute`) и подстроку заголовка или
    тела (`text`)."""
    direction = await _direction(session, project_key, direction_key)
    page = await case_service.list_project_entries(
        session,
        direction,
        actor=actor,
        nos=nos,
        types=types,
        attribute=attribute,
        text=text,
        after_no=after_no,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[EntryRead].of(
        [entry_read(item, direction=direction.address) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{direction_key}/entries/{entry_no}", summary="Read one direction case entry")
async def read_direction_entry(
    project_key: ProjectKeyPath,
    direction_key: DirectionKeyPath,
    entry_no: DirectionEntryNoPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[EntryRead]:
    """Одна запись дела направления по номеру — адрес из ссылки `TRK/promotion#3`.

    Номера, которого в деле нет, — `404 entry_not_found`.
    """
    direction = await _direction(session, project_key, direction_key)
    entry = await case_service.read_project_entry(session, direction, entry_no, actor=actor)
    return DataResponse[EntryRead](data=entry_read(entry, direction=direction.address))


async def _detail(
    session: AsyncSession, direction: Direction, *, actor: Actor
) -> DataResponse[DirectionDetailRead]:
    """Направление с атрибутами: тот же ответ у чтения, правки и архива."""
    attributes = await attributes_service.list_attributes(session, direction, actor=actor)
    return DataResponse[DirectionDetailRead](
        data=DirectionDetailRead(
            **direction_read(direction).model_dump(),
            attributes=[AttributeRead.model_validate(item) for item in attributes],
        )
    )
