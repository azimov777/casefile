"""Чеклист задачи: список, добавление, правка, отметка, перестановка, удаление.

Роутер только переводит HTTP в вызов сценария. Позиции пунктов наружу не выходят:
место при перемещении задаётся соседом, а разреженная шкала остаётся внутренним делом
домена (`app/domain/checklists.py`).

Отметка о выполнении вынесена отдельным маршрутом, а не полем частичного обновления:
у неё своё событие (`checklist.item_checked`), на которое подписывается автоматика.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActorDep, IssueKeyPath, SessionDep
from app.api.schemas.checklists import (
    ChecklistItemCheck,
    ChecklistItemCreate,
    ChecklistItemMove,
    ChecklistItemRead,
    ChecklistItemUpdate,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.core.sentinels import UNSET
from app.db.models.actor import Actor
from app.services import actors as actors_service
from app.services import checklists as service
from app.services import issues as issues_service

router = APIRouter(prefix="/issues", tags=["checklists"])

ItemIdPath = Annotated[uuid.UUID, Path(description="Checklist item UUID")]


@router.get("/{issue_key}/checklist", summary="Read the issue checklist")
async def list_checklist_items(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[ChecklistItemRead]:
    """Пункты чеклиста по порядку, целиком.

    Курсора у этой коллекции нет, и это не пропуск: число пунктов ограничено доменом,
    поэтому список всегда помещается в один ответ. `meta` при этом та же, что у любой
    коллекции проекта — клиент разбирает ответ одним и тем же кодом.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    items = await service.list_items(session, issue, initiator=current_actor)
    return CollectionResponse[ChecklistItemRead].of(
        [ChecklistItemRead.of(item, issue_key=issue.key) for item in items]
    )


@router.post(
    "/{issue_key}/checklist",
    status_code=status.HTTP_201_CREATED,
    summary="Add a checklist item",
)
async def add_checklist_item(
    issue_key: IssueKeyPath,
    payload: ChecklistItemCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ChecklistItemRead]:
    """Добавляет пункт в конец чеклиста. Место выбирают перемещением, а не вставкой."""
    issue = await issues_service.get_issue_by_key(session, issue_key)
    item = await service.add_item(
        session,
        issue,
        initiator=current_actor,
        text=payload.text,
        assignee=await _actor(session, payload.assignee),
        deadline=payload.deadline,
    )
    return DataResponse[ChecklistItemRead](data=ChecklistItemRead.of(item, issue_key=issue.key))


@router.patch("/{issue_key}/checklist/{item_id}", summary="Update a checklist item")
async def update_checklist_item(
    issue_key: IssueKeyPath,
    item_id: ItemIdPath,
    payload: ChecklistItemUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ChecklistItemRead]:
    """Меняет текст, исполнителя и дедлайн пункта.

    Переданный `null` очищает поле (`assignee`, `deadline`), отсутствующий ключ не
    трогает его. Отметка о выполнении меняется своим маршрутом.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    item = await service.get_item(session, issue, item_id)
    given = payload.model_dump(exclude_unset=True)

    assignee: Any = UNSET
    if "assignee" in given:
        assignee = await _actor(session, given["assignee"])

    updated = await service.update_item(
        session,
        item,
        issue=issue,
        initiator=current_actor,
        text=given.get("text", UNSET),
        assignee=assignee,
        deadline=given.get("deadline", UNSET),
    )
    return DataResponse[ChecklistItemRead](data=ChecklistItemRead.of(updated, issue_key=issue.key))


@router.put("/{issue_key}/checklist/{item_id}/done", summary="Check a checklist item")
async def check_checklist_item(
    issue_key: IssueKeyPath,
    item_id: ItemIdPath,
    payload: ChecklistItemCheck,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ChecklistItemRead]:
    """Ставит или снимает отметку о выполнении.

    Кто и когда отметил, проставляется вместе с самой отметкой и снимается вместе с
    ней. Повторный запрос с тем же значением отвечает так же и ничего не меняет:
    события на изменение, которого не было, проект не порождает.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    item = await service.get_item(session, issue, item_id)
    updated = await service.set_item_done(
        session,
        item,
        issue=issue,
        initiator=current_actor,
        is_done=payload.is_done,
    )
    return DataResponse[ChecklistItemRead](data=ChecklistItemRead.of(updated, issue_key=issue.key))


@router.put("/{issue_key}/checklist/{item_id}/position", summary="Move a checklist item")
async def move_checklist_item(
    issue_key: IssueKeyPath,
    item_id: ItemIdPath,
    payload: ChecklistItemMove,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[ChecklistItemRead]:
    """Ставит пункт после указанного; `after: null` переносит его в начало списка.

    Отвечает всем чеклистом, а не одним пунктом: клиент попросил изменить **порядок**,
    и проверить результат по одному пункту нельзя — позиции наружу не отдаются. Список
    целиком снимает вопрос и заодно показывает результат редкой перенумерации.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    item = await service.get_item(session, issue, item_id)
    after = None if payload.after is None else await service.get_item(session, issue, payload.after)
    await service.move_item(session, item, issue=issue, initiator=current_actor, after=after)
    items = await service.list_items(session, issue, initiator=current_actor)
    return CollectionResponse[ChecklistItemRead].of(
        [ChecklistItemRead.of(existing, issue_key=issue.key) for existing in items]
    )


@router.delete(
    "/{issue_key}/checklist/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a checklist item",
)
async def delete_checklist_item(
    issue_key: IssueKeyPath,
    item_id: ItemIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет пункт насовсем.

    В отличие от комментария, удаление жёсткое: у пункта нет ни адресата, ни ушедшего
    уведомления, ради которых стоило бы держать плашку. Факт удаления остаётся в
    истории задачи и в событии `checklist.item_removed`.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    item = await service.get_item(session, issue, item_id)
    await service.delete_item(session, item, issue=issue, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _actor(session: AsyncSession, key: str | None) -> Actor | None:
    return None if key is None else await actors_service.get_actor_by_key(session, key)
