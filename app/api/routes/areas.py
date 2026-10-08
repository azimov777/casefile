"""Области проекта: карточка, атрибуты, дело и архив (TRK#57).

Ресурс внутри проекта: `/projects/{project_key}/areas/{area_key}`. Адрес
области — `TRK/promotion` — собран из двух сегментов пути, а не одним: косая черта в
сегменте потребовала бы экранирования. Атрибуты, дело и архив — те же сценарии, что у
проекта (`app/services/attributes.py`, `app/services/case.py`), с областью владельцем.

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
from app.api.schemas.areas import (
    AreaArchiving,
    AreaCreate,
    AreaDetailRead,
    AreaRead,
    AreaUpdate,
    area_read,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.entries import AreaEntryCreate, EntryRead, entry_read
from app.api.schemas.projects import AttributeRead, AttributeRemoval, AttributeSet
from app.db.models.area import Area
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.areas import format_area_address
from app.domain.projects import normalize_project_key
from app.services import areas as service
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import decisions as decisions_service
from app.services import projects as projects_service
from app.services.auth import Actor

router = APIRouter(prefix="/projects/{project_key}/areas", tags=["areas"])

AreaKeyPath = Annotated[
    str,
    Path(
        description="Area key inside the project; matching ignores case",
        examples=["promotion"],
    ),
]

IncludeArchivedAreasQuery = Annotated[
    bool,
    Query(
        description=(
            "Also list archived areas. Without it they are hidden from the list; a "
            "area is still read by its address either way"
        )
    ),
]

AreaEntryNoPath = Annotated[
    int,
    Path(ge=1, description="Entry number inside the area, from 1", examples=[3]),
]


async def _area(session: AsyncSession, project_key: str, area_key: str) -> Area:
    """Область по двум сегментам пути — тем же поиском, что по адресу."""
    return await service.get_area(session, format_area_address(project_key, area_key))


@router.get("", summary="List the areas of a project")
async def list_areas(
    project_key: ProjectKeyPath,
    session: SessionDep,
    actor: ActorDep,
    include_archived: IncludeArchivedAreasQuery = False,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[AreaRead]:
    """Области проекта. Архивные — только с `include_archived=true`; по адресу
    архивная область читается и без него."""
    project = await projects_service.get_project(session, project_key)
    page = await service.list_areas_page(
        session,
        project,
        actor=actor,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[AreaRead].of(
        [area_read(item) for item in page.items], next_cursor=page.next_cursor
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an area")
async def create_area(
    project_key: ProjectKeyPath,
    payload: AreaCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[AreaRead]:
    """Заводит область в проекте; первая запись её дела — `created`.

    Ключ хранится в нижнем регистре и неизменяем; занятый в проекте (без учёта регистра)
    — `409 area_key_taken`, не по шаблону — `422 invalid_area_key`. В архивный
    проект область не заводится — `409 project_archived`. Повтор с тем же
    `Idempotency-Key` отвечает первой областью, а не `409`.
    """

    # Ответ без атрибутов: у новой области их нет, а форма ответа создающего вызова
    # живёт сутки в ключах идемпотентности, и расширять её нельзя (`TRK/mcp#11`).
    async def create() -> DataResponse[AreaRead]:
        area = await service.create_area(
            session,
            actor=actor,
            address=format_area_address(project_key, payload.key),
            title=payload.title,
            description=payload.description,
        )
        return DataResponse[AreaRead](data=area_read(area))

    return await once.run(
        DataResponse[AreaRead],
        request={"project": normalize_project_key(project_key), "area": payload},
        build=create,
    )


@router.get("/{area_key}", summary="Read an area")
async def read_area(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AreaDetailRead]:
    """Карточка области с нынешними значениями атрибутов. История атрибутов и всё
    остальное дело — `/projects/{key}/areas/{area}/entries`."""
    area = await _area(session, project_key, area_key)
    return await _detail(session, area, actor=actor)


@router.patch("/{area_key}", summary="Update an area")
async def update_area(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    payload: AreaUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AreaDetailRead]:
    """Меняет название и описание; проект и ключ неизменяемы, поле `key` в теле — `422`.

    Каждое изменённое поле подшивает `field_changed` в дело области. Архивная
    область — `409 area_archived`, архивный проект — `409 project_archived`.
    """
    area = await _area(session, project_key, area_key)
    changes = payload.model_dump(exclude_unset=True)
    area = await service.update_area(session, area, actor=actor, **changes)
    return await _detail(session, area, actor=actor)


@router.post("/{area_key}/archive", summary="Archive an area")
async def archive_area(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    payload: AreaArchiving,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AreaDetailRead]:
    """Архивирует область с причиной: карточка, атрибуты и дело замораживаются
    (`409 area_archived` на любое изменение, кроме восстановления). Причина — в записи
    `archived`; пустая — `422 area_reason_required`. Уже в архиве —
    `409 area_archived`, проект в архиве — `409 project_archived`.
    """
    area = await _area(session, project_key, area_key)
    await service.archive_area(session, area, actor=actor, reason=payload.reason)
    return await _detail(session, area, actor=actor)


@router.post("/{area_key}/restore", summary="Restore an archived area")
async def restore_area(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    payload: AreaArchiving,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AreaDetailRead]:
    """Восстанавливает область из архива с причиной (запись `restored`). Не в архиве —
    `409 area_not_archived`; проект в архиве — `409 project_archived`: сначала
    восстанавливают проект."""
    area = await _area(session, project_key, area_key)
    await service.restore_area(session, area, actor=actor, reason=payload.reason)
    return await _detail(session, area, actor=actor)


@router.put("/{area_key}/attributes/{attribute_name}", summary="Set an area attribute")
async def set_area_attribute(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    attribute_name: AttributeNamePath,
    payload: AttributeSet,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[AttributeRead]:
    """Заводит атрибут области или меняет его значение — правила атрибута проекта.

    Атрибута нет — `attribute_created`, причина необязательна; есть с другим значением —
    `attribute_changed`, без причины `422 attribute_reason_required`; то же значение —
    ничего не подшивается. Записи ложатся в дело области.
    """
    area = await _area(session, project_key, area_key)
    given = payload.model_dump()

    async def put() -> DataResponse[AttributeRead]:
        result = await attributes_service.set_attribute(
            session,
            area,
            actor=actor,
            name=attribute_name,
            value=given["value"],
            reason=given["reason"],
        )
        return DataResponse[AttributeRead](data=AttributeRead.model_validate(result.attribute))

    return await once.run(
        DataResponse[AttributeRead],
        request={
            "area": area.address,
            "name": attribute_name.lower(),
            "attribute": given,
        },
        build=put,
    )


@router.post(
    "/{area_key}/attributes/{attribute_name}/remove",
    summary="Remove an area attribute",
)
async def remove_area_attribute(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    attribute_name: AttributeNamePath,
    payload: AttributeRemoval,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Снимает атрибут области с причиной и отдаёт подшитую `attribute_removed`.

    Атрибута нет — `404 attribute_not_found`, пустая причина —
    `422 attribute_reason_required`. Повтор с тем же `Idempotency-Key` отвечает первой
    записью, а не `404`.
    """
    area = await _area(session, project_key, area_key)
    given = payload.model_dump()

    async def remove() -> DataResponse[EntryRead]:
        entry = await attributes_service.remove_attribute(
            session, area, actor=actor, name=attribute_name, reason=given["reason"]
        )
        return DataResponse[EntryRead](data=entry_read(entry, area=area.address))

    return await once.run(
        DataResponse[EntryRead],
        request={"area": area.address, "name": attribute_name.lower(), "removal": given},
        build=remove,
    )


@router.post(
    "/{area_key}/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Append an area case entry",
)
async def create_area_entry(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    entry: AreaEntryCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Подшивает запись в дело области: заметку, решение, находку или артефакт.

    Номер `no` считается внутри области, ссылка на запись — `TRK/promotion#3`.
    `supersedes` в теле нет: замену у дела области ведёт агент через MCP, а интерфейс
    записей не заменяет, и поле без вызова в REST не держат (решение TRK#53). Замечания к
    форме и ссылкам — разом в `422 entry_fields_invalid`. Архивная область — `409
    area_archived`.
    """
    area = await _area(session, project_key, area_key)
    given = entry.model_dump(mode="json")

    async def append() -> DataResponse[EntryRead]:
        appended = await case_service.append_project_entry(
            session,
            area,
            actor=actor,
            type=given["type"],
            title=given["title"],
            body=given["body"],
            refs=given["refs"],
        )
        return DataResponse[EntryRead](data=entry_read(appended, area=area.address))

    return await once.run(
        DataResponse[EntryRead],
        request={"area": area.address, "entry": given},
        build=append,
    )


@router.get("/{area_key}/entries", summary="Read area case entries")
async def list_area_entries(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
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
    """Записи дела области с телами и нагрузкой, в порядке `no` — те же фильтры, что у
    дела проекта, включая историю одного атрибута (`attribute`) и подстроку заголовка или
    тела (`text`).

    У решения и заметки — `status` и `superseded_by`, посчитанные при чтении, как в деле
    проекта (решение TRK#57, раздел 5). Отбора `in_force` здесь нет: интерфейс его не
    зовёт (решение TRK#53); у агента он есть в `read_project_entries`.
    """
    area = await _area(session, project_key, area_key)
    page = await case_service.list_project_entries(
        session,
        area,
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
        [
            entry_read(item, area=area.address, standing=page.standings.get(item.no))
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/{area_key}/entries/{entry_no}", summary="Read one area case entry")
async def read_area_entry(
    project_key: ProjectKeyPath,
    area_key: AreaKeyPath,
    entry_no: AreaEntryNoPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[EntryRead]:
    """Одна запись дела области по номеру — адрес из ссылки `TRK/promotion#3`; у решения
    и заметки — со статусом и преемником, как в списке.

    Номера, которого в деле нет, — `404 entry_not_found`.
    """
    area = await _area(session, project_key, area_key)
    entry = await case_service.read_project_entry(session, area, entry_no, actor=actor)
    standing = await decisions_service.standing_of(session, area, entry)
    return DataResponse[EntryRead](data=entry_read(entry, area=area.address, standing=standing))


async def _detail(
    session: AsyncSession, area: Area, *, actor: Actor
) -> DataResponse[AreaDetailRead]:
    """Область с атрибутами: тот же ответ у чтения, правки и архива."""
    attributes = await attributes_service.list_attributes(session, area, actor=actor)
    return DataResponse[AreaDetailRead](
        data=AreaDetailRead(
            **area_read(area).model_dump(),
            attributes=[AttributeRead.model_validate(item) for item in attributes],
        )
    )
