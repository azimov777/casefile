"""Решения поперёк проектов и областей: список для вкладки «Решения» и для входящей.

Не новая сущность, а **представление** над делами проектов и областей (TRK-755): решение —
запись `decision`, статус и состояние проверки считаются при чтении. Роутер только
переводит HTTP в вызов сценария и обратно.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import PageMeta
from app.api.schemas.decisions import DecisionListRead, DecisionListResponse
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.decisions import DecisionStatus, ReviewState
from app.services import decisions as service
from app.services import projects as projects_service

router = APIRouter(prefix="/decisions", tags=["decisions"])

ProjectQuery = Annotated[
    str | None,
    Query(
        description=(
            "Project key; matching ignores case. With it the list holds the decisions of "
            "this project and of its active areas, even if the project is archived. "
            "Without it — the decisions of every project that is not archived and of their "
            "active areas"
        ),
        examples=["TRK"],
    ),
]
StatusQuery = Annotated[
    DecisionStatus | None,
    Query(description="Keep only decisions with this status"),
]
ReviewStateQuery = Annotated[
    ReviewState | None,
    Query(
        description=(
            "Keep only decisions with this review state; `unconfirmed` with `status=in_force` "
            "is the decisions that await a person"
        )
    ),
]


@router.get("", summary="List decisions")
async def list_decisions(
    session: SessionDep,
    actor: ActorDep,
    project: ProjectQuery = None,
    status: StatusQuery = None,
    review_state: ReviewStateQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> DecisionListResponse:
    """Решения проекта и его неархивных областей или всех неархивных проектов, старые первыми.

    Каждая строка — адрес решения, область (`null` у решения проекта), название, автор,
    время, `status`, `review_state` и `review_entry`, `supersedes` и `superseded_by`
    ссылками, `refs` самого решения и число задач, которые на него ссылаются. Тело
    решения — в записи дела (`GET /projects/{key}/entries/{no}`). Отборы `status` и
    `review_state` складываются по «и». `unconfirmed` в ответе — сколько действующих
    решений не проверено во всей области списка; отборы его не меняют. Страницы
    курсорные, как у других списков. Закрытый вызову проект в список не входит.
    """
    found = await projects_service.get_project(session, project) if project is not None else None
    listing = await service.list_decisions(
        session,
        actor=actor,
        project=found,
        status=status,
        review_state=review_state,
        limit=limit,
        cursor=cursor,
    )
    return DecisionListResponse(
        data=[
            DecisionListRead(
                ref=item.ref,
                area=item.area,
                title=item.title,
                author=AuthorRead.model_validate(item.author),
                created_at=item.created_at,
                status=item.status,
                review_state=item.review_state,
                review_entry=item.review_entry,
                supersedes=item.supersedes,
                superseded_by=item.superseded_by,
                refs=item.refs,
                tasks=item.tasks,
            )
            for item in listing.items
        ],
        meta=PageMeta(next_cursor=listing.next_cursor, has_more=listing.next_cursor is not None),
        unconfirmed=listing.unconfirmed,
    )
