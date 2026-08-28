"""Связи задачи и дерево её подзадач.

Роутер только переводит HTTP в вызов сценария: ключи задач разрешаются в объекты,
результат сворачивается в схему ответа. Всё, что решает, законна ли связь, живёт в
`app/services/links.py` — иначе те же операции из MCP пошли бы мимо проверок циклов.

Связи адресуются через свою задачу (`/issues/{issue_key}/links/{link_id}`), а не
отдельным корневым ресурсом. Причина не в эстетике: у связи две стороны и нет
«главной», а вопрос «какие связи у этой задачи» — единственный, который к ней задают.
Путь через задачу заодно даёт естественную проверку принадлежности при удалении.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, IssueKeyPath, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.links import IssueLinkCreate, IssueLinkRead, IssueTreeNodeRead
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.links import DEFAULT_TREE_DEPTH, MAX_TREE_DEPTH
from app.services import issues as issues_service
from app.services import links as service

router = APIRouter(prefix="/issues", tags=["links"])

LinkIdPath = Annotated[uuid.UUID, Path(description="Link UUID")]

TreeDepthQuery = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_TREE_DEPTH,
        description=(
            "How many levels of subtasks to return. Nodes with children beyond the limit "
            "come back with `has_more_children` set, so a trimmed tree is never mistaken "
            "for a complete one"
        ),
    ),
]


@router.get("/{issue_key}/links", summary="List issue links")
async def list_issue_links(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueLinkRead]:
    """Связи задачи со всех сторон, в порядке появления.

    Каждая связь названа так, как её видит именно эта задача: строка, заведённая как
    «TRK-2 depends_on TRK-1», приезжает к TRK-1 типом `blocks`. Хранится она при этом
    один раз — второй записи, которая могла бы с ней разойтись, не существует.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    page = await service.list_issue_links(
        session,
        issue,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[IssueLinkRead].of(
        [IssueLinkRead.of(view) for view in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/{issue_key}/links",
    status_code=status.HTTP_201_CREATED,
    summary="Link two issues",
)
async def create_issue_link(
    issue_key: IssueKeyPath,
    payload: IssueLinkCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueLinkRead]:
    """Заводит связь `<задача из пути> <type> <issue>`.

    Повторная попытка отвечает `409 link_already_exists`, а не молча выполняется:
    связь — не набор, куда элемент можно добавить второй раз без последствий, и тихий
    успех скрыл бы от клиента, что он ошибся стороной или типом.

    Иерархические связи (`subtask_of`, `parent_of`) проверяются дополнительно: у задачи
    не больше одного родителя, у эпика родителя нет вовсе, и кольцо не замыкается ни на
    какой глубине.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    other = await issues_service.get_issue_by_key(session, payload.issue)
    link = await service.create_link(
        session,
        initiator=current_actor,
        source=issue,
        link_type=payload.type,
        target=other,
    )
    return DataResponse[IssueLinkRead](data=IssueLinkRead.of(service.link_view(link, issue)))


@router.get("/{issue_key}/tree", summary="Read the subtask tree")
async def read_issue_tree(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    depth: TreeDepthQuery = DEFAULT_TREE_DEPTH,
) -> DataResponse[IssueTreeNodeRead]:
    """Дерево подзадач от этой задачи вниз.

    Одиночный ресурс, а не коллекция: дерево не листается страницами — курсор посреди
    поддерева не имел бы смысла ни для клиента, ни для базы. Ограничивает выдачу
    глубина, и она обязательна: у эпика с сотнями подзадач запрос без предела вытащил
    бы половину базы.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    tree = await service.build_tree(session, issue, initiator=current_actor, depth=depth)
    return DataResponse[IssueTreeNodeRead](data=IssueTreeNodeRead.of(tree))


@router.delete(
    "/{issue_key}/links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a link",
)
async def delete_issue_link(
    issue_key: IssueKeyPath,
    link_id: LinkIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет связь. Обе задачи получают запись в историю, шина — одно событие.

    Связь, принадлежащая другой паре задач, отвечает `404`: для клиента «есть, но не
    твоя» — то же самое, что «нет», и по чужому идентификатору удалить связь нельзя.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    link = await service.get_issue_link(session, issue, link_id)
    await service.delete_link(session, link, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
