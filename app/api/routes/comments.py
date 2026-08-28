"""Обсуждение задачи: лента, новая реплика, правка, мягкое удаление.

Роутер только переводит HTTP в вызов сценария: ключ задачи разрешается в объект,
результат сворачивается в схему ответа. Всё, что решает, законна ли операция, живёт в
`app/services/comments.py` — иначе те же действия из MCP пошли бы мимо разбора
упоминаний и мимо событий.

Комментарии адресуются через свою задачу (`/issues/{issue_key}/comments/{comment_id}`),
а не отдельным корневым ресурсом: реплика вне задачи не существует, а путь через задачу
даёт естественную проверку принадлежности при правке и удалении.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, IssueKeyPath, LimitQuery, SessionDep
from app.api.schemas.comments import CommentCreate, CommentRead, CommentUpdate
from app.api.schemas.common import CollectionResponse, DataResponse
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import comments as service
from app.services import issues as issues_service

router = APIRouter(prefix="/issues", tags=["comments"])

CommentIdPath = Annotated[uuid.UUID, Path(description="Comment UUID")]


@router.get("/{issue_key}/comments", summary="List issue comments")
async def list_issue_comments(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[CommentRead]:
    """Лента обсуждения, от старого к новому.

    Удалённые реплики остаются в ленте плашкой: `body` у них `null`, `is_deleted` —
    `true`. Прятать их значило бы делать дыры в обсуждении, а соседние реплики теряли
    бы контекст.

    Комментарии автоматики приезжают здесь же и той же формой: автор у них —
    системный актор, отдельной ленты для служебных сообщений в проекте нет.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    page = await service.list_comments(
        session,
        issue,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[CommentRead].of(
        [CommentRead.of(comment, issue_key=issue.key) for comment in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/{issue_key}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Comment on an issue",
)
async def create_issue_comment(
    issue_key: IssueKeyPath,
    payload: CommentCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[CommentRead]:
    """Пишет комментарий от имени актора, которому принадлежит токен.

    Упоминания `@ключ_актора` разбираются при сохранении и возвращаются отдельным
    полем: на них подпишутся уведомления. В поле попадают только существующие акторы —
    `@nobody` остаётся обычным текстом.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    comment = await service.add_comment(
        session,
        issue,
        initiator=current_actor,
        body=payload.body,
    )
    return DataResponse[CommentRead](data=CommentRead.of(comment, issue_key=issue.key))


@router.patch("/{issue_key}/comments/{comment_id}", summary="Edit a comment")
async def update_issue_comment(
    issue_key: IssueKeyPath,
    comment_id: CommentIdPath,
    payload: CommentUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[CommentRead]:
    """Заменяет текст комментария целиком и пересобирает упоминания.

    Правка удалённого комментария отвечает `409 comment_deleted`: вернуть удалённое
    высказывание в ленту задним числом нельзя. Правка тем же текстом ничего не меняет
    и пометку «изменён» не ставит.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    comment = await service.get_comment(session, issue, comment_id)
    updated = await service.update_comment(
        session,
        comment,
        issue=issue,
        initiator=current_actor,
        body=payload.body,
    )
    return DataResponse[CommentRead](data=CommentRead.of(updated, issue_key=issue.key))


@router.delete(
    "/{issue_key}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a comment",
)
async def delete_issue_comment(
    issue_key: IssueKeyPath,
    comment_id: CommentIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Мягко удаляет комментарий: текст стирается, плашка остаётся в ленте.

    Повторное удаление отвечает `409 comment_deleted`, а не `204`: в отличие от отзыва
    токена, здесь повтор означает, что клиент видит не то состояние, — реплика уже
    исчезла из обсуждения, и молчаливый успех это скрыл бы.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    comment = await service.get_comment(session, issue, comment_id)
    await service.delete_comment(session, comment, issue=issue, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
