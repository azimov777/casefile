"""Реестр полей: описание кастомных атрибутов задачи.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет, иначе
те же операции из MCP пошли бы другим путём и мимо будущих событий.

Адресация как у справочников: глобальное поле — голым ключом (`/fields/severity`),
локальное — с префиксом очереди (`/fields/TRK.severity`).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.fields import FieldCreate, FieldRead, FieldUpdate
from app.db.models.catalog import IssueType
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.catalogs import CatalogKind
from app.domain.fields import FieldOption
from app.services import fields as service
from app.services import queues as queues_service

router = APIRouter(prefix="/fields", tags=["fields"])

# Без `pattern`: параметр адресует существующее поле, а адресация в проекте мягкая —
# регистр приводит домен, а невнятную ссылку отвергает `parse_field_ref` кодом
# `invalid_field_ref` с ожидаемым форматом в `details`, чего шаблон дать не может.
FieldRefPath = Annotated[
    str,
    Path(
        description="Field reference: `key` for a global field, `QUEUE.key` for a local one",
        examples=["severity", "TRK.severity"],
    ),
]

QueueFilterQuery = Annotated[
    str | None,
    Query(
        description=(
            "Queue key: return fields usable in this queue — global ones plus its own. "
            "Omit to list global fields only."
        ),
    ),
]
IssueTypeFilterQuery = Annotated[
    str | None,
    Query(
        description=(
            "Issue type reference: narrow the list down to the fields applicable to it. "
            "A field without restrictions applies to every issue type."
        ),
    ),
]
HiddenFilterQuery = Annotated[
    bool | None,
    Query(description="Filter by the hidden flag; omit to get both hidden and visible fields"),
]


async def _issue_type(
    session: AsyncSession,
    ref: str | None,
    current_actor: CurrentActorDep,
) -> IssueType | None:
    """Тип задачи по ссылке: `None` — без сужения по типу."""
    if ref is None:
        return None
    return await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, ref, initiator=current_actor
    )


async def _issue_types(
    session: AsyncSession,
    refs: list[str] | None,
    current_actor: CurrentActorDep,
) -> list[IssueType] | None:
    """Ограничения применимости: `None` — не передавали, `[]` — снять ограничения."""
    if refs is None:
        return None
    return [
        await queues_service.resolve_catalog_ref(
            session, CatalogKind.ISSUE_TYPE, ref, initiator=current_actor
        )
        for ref in refs
    ]


@router.get("", summary="List fields")
async def list_fields(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueFilterQuery = None,
    issue_type: IssueTypeFilterQuery = None,
    is_hidden: HiddenFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[FieldRead]:
    """Реестр полей области.

    С обоими фильтрами (`queue` и `issue_type`) это и есть ответ на вопрос «какие поля
    у задачи такого типа в этой очереди». Порядок — курсорный, по времени создания:
    порядок показа (`display_order`) применяется там, где набор отдаётся целиком, — в
    конфигурации очереди.
    """
    page = await service.list_fields(
        session,
        initiator=current_actor,
        queue=await queues_service.resolve_scope(session, queue),
        issue_type=await _issue_type(session, issue_type, current_actor),
        is_hidden=is_hidden,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[FieldRead].of(
        [FieldRead.of(field) for field in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a field")
async def create_field(
    payload: FieldCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[FieldRead]:
    """Заводит поле. Добавление атрибута задаче не требует миграции — в этом весь смысл."""
    field = await service.create_field(
        session,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        value_type=payload.value_type,
        queue=await queues_service.resolve_scope(session, payload.queue),
        is_multiple=payload.is_multiple,
        is_required=payload.is_required,
        options=[FieldOption(key=item.key, name=item.name) for item in payload.options],
        default_value=payload.default_value,
        display_order=payload.display_order,
        issue_types=await _issue_types(session, payload.issue_types, current_actor),
    )
    return DataResponse[FieldRead](data=FieldRead.of(field))


@router.get("/{field_ref}", summary="Read a field")
async def read_field(
    field_ref: FieldRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[FieldRead]:
    """Описание поля: тип значения, множественность, варианты перечисления.

    По нему интерфейс строит редактор значения, а агент понимает, что можно положить в
    `values` задачи. Ссылка мягкая: `severity` — глобальное поле, `TRK.severity` —
    локальное для очереди.
    """
    field = await queues_service.resolve_field_ref(session, field_ref, initiator=current_actor)
    return DataResponse[FieldRead](data=FieldRead.of(field))


@router.patch("/{field_ref}", summary="Update a field")
async def update_field(
    field_ref: FieldRefPath,
    payload: FieldUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[FieldRead]:
    """Меняет описание поля. Ключ неизменяем, тип — только пока у поля нет значений.

    Скрытие (`is_hidden: true`) — единственный способ убрать поле, которым уже
    пользовались: значения и история изменений остаются на месте.
    """
    field = await queues_service.resolve_field_ref(session, field_ref, initiator=current_actor)
    changes = payload.changes()
    issue_types = await _issue_types(session, changes.pop("issue_types", None), current_actor)
    field = await service.update_field(
        session, field, initiator=current_actor, issue_types=issue_types, **changes
    )
    return DataResponse[FieldRead](data=FieldRead.of(field))


@router.delete(
    "/{field_ref}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a field",
)
async def delete_field(
    field_ref: FieldRefPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Отклоняется, если у поля есть значения: тогда его можно только скрыть.

    Жёсткое удаление оставило бы в задачах данные без описания, а в истории
    изменений — записи о поле, которого нет.
    """
    field = await queues_service.resolve_field_ref(session, field_ref, initiator=current_actor)
    await service.delete_field(session, field, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
