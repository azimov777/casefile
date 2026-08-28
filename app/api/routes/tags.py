"""Теги: словарь заведённых меток и точечные операции над тегами задачи.

Два разных ресурса в одном роутере, и это осознанно: `/tags` — словарь всей установки,
`/issues/{key}/tags` — метки конкретной задачи. Разносить их по файлам значило бы
развести правила нормализации, которые обязаны быть одними и теми же.

Полная замена набора живёт в частичном обновлении задачи (`PATCH /issues/{key}` с
`tags`). Здесь — добавление и снятие, которым не нужно присылать весь набор: клиенту,
ставящему одну метку, иначе пришлось бы затирать чужую, поставленную параллельно.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentActorDep, CursorQuery, IssueKeyPath, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.issues import IssueRead
from app.api.schemas.tags import IssueTagsAdd, TagUsageRead
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.issues import MAX_TAG_LENGTH
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services import tags as service

router = APIRouter(tags=["tags"])

TagQuery = Annotated[
    str | None,
    Query(
        max_length=MAX_TAG_LENGTH,
        description=(
            "Substring to look for, case-insensitive. Omit it to walk the whole dictionary "
            "alphabetically"
        ),
        examples=["rel"],
    ),
]
QueueFilterQuery = Annotated[
    str | None,
    Query(description="Queue key: count tags of this queue only. Omit to cover every queue"),
]
TagPath = Annotated[
    str,
    Path(
        description="Tag to remove, matched case-insensitively",
        examples=["release"],
    ),
]


@router.get("/tags", summary="List existing tags")
async def list_tags(
    session: SessionDep,
    current_actor: CurrentActorDep,
    query: TagQuery = None,
    queue: QueueFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[TagUsageRead]:
    """Словарь тегов по алфавиту: сам тег и число задач с ним.

    Справочника тегов в проекте нет — тег существует, пока есть задача с ним. Поэтому
    словарь собирается по задачам, а число задач показывает, какое из похожих
    написаний прижилось.

    Порядок алфавитный, а не по частоте: частота меняется от каждой правки любой
    задачи, и страница, упорядоченная по ней, теряла бы и дублировала теги между
    запросами.
    """
    page = await service.list_tags(
        session,
        initiator=current_actor,
        queue=await queues_service.resolve_scope(session, queue),
        query=query,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[TagUsageRead].of(
        [TagUsageRead.of(usage) for usage in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("/issues/{issue_key}/tags", summary="Add tags to an issue")
async def add_issue_tags(
    issue_key: IssueKeyPath,
    payload: IssueTagsAdd,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Добавляет теги, не трогая уже поставленные.

    Отвечает задачей целиком: теги — её поле, и клиент, поставивший метку, должен
    увидеть новую версию задачи, а не только список меток. Повторное добавление того
    же тега ничего не меняет и версию не поднимает.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    mutation = await service.add_tags(
        session,
        issue,
        initiator=current_actor,
        tags=payload.tags,
        expected_version=payload.version,
    )
    return DataResponse[IssueRead](data=IssueRead.of(mutation.issue))


@router.delete(
    "/issues/{issue_key}/tags/{tag}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a tag from an issue",
)
async def remove_issue_tag(
    issue_key: IssueKeyPath,
    tag: TagPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Снимает тег с задачи. Идемпотентно: снятие отсутствующего тега тоже `204`.

    Сравнение без учёта регистра — как и везде, где теги сравниваются: клиент,
    приславший `Release` вместо `release`, снимает ту же метку, а не промахивается
    мимо неё молча.

    Версия задачи при фактическом снятии растёт, поэтому клиенту, который держит её
    для оптимистичной блокировки, задачу нужно перечитать.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    await service.remove_tags(session, issue, initiator=current_actor, tags=[tag])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
