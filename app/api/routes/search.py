"""Поиск задач: строкой запроса и структурным фильтром.

Два маршрута на один сценарий, и это не дубль. `GET` принимает строку на языке
запросов — это главный путь агента и самый короткий путь фронта: один параметр, который
можно сохранить, передать и положить в правило автоматики. `POST` принимает структурный
фильтр целиком: у него десятки параметров и значения кастомных полей, а такое тело в
строке URL не выражается типизированно.

Оба маршрута зовут одну функцию сценария и сводят вход к одному внутреннему
представлению. Другого способа выполнить требование «одинаковые по смыслу фильтр и
строка дают идентичный результат» нет: две реализации разошлись бы на первом же краевом
случае.

Живут маршруты под `/search`, а не под `/issues`: `/issues/search` попал бы под
`/issues/{issue_key}` и разбирался бы как ключ задачи — тихо и только в рантайме.
"""

from fastapi import APIRouter

from app.api.deps import (
    CurrentActorDep,
    CursorQuery,
    FieldsParam,
    LimitQuery,
    QueryParam,
    SavedFilterParam,
    SessionDep,
    SortParam,
)
from app.api.schemas.common import CollectionResponse
from app.api.schemas.search import IssueSearchRead, IssueSearchRequest, search_page
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import search as service

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "/issues",
    summary="Search issues with a query string",
    response_model_exclude_unset=True,
)
async def search_issues(
    session: SessionDep,
    current_actor: CurrentActorDep,
    query: QueryParam = None,
    saved_filter: SavedFilterParam = None,
    sort: SortParam = None,
    fields: FieldsParam = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueSearchRead]:
    """Задачи по строке запроса.

    Пустой запрос — законный: он означает «все задачи» в порядке создания, и отдельного
    способа сказать то же самое заводить незачем.

    Ошибка разбора приходит с позицией символа и причиной в `details`: по ним запрос
    исправляется за одну попытку, а не подбором.
    """
    outcome = await service.search_issues(
        session,
        initiator=current_actor,
        query=query,
        saved_filter_id=saved_filter,
        sort=sort or (),
        fields=fields or (),
        limit=limit,
        cursor=cursor,
    )
    return search_page(outcome)


@router.post(
    "/issues",
    summary="Search issues with a structured filter",
    response_model_exclude_unset=True,
)
async def search_issues_by_filter(
    payload: IssueSearchRequest,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> CollectionResponse[IssueSearchRead]:
    """Задачи по структурному фильтру, строке запроса и сохранённому фильтру разом.

    Источники складываются по `and`, поэтому «сохранённый фильтр плюс ещё одно условие»
    — не особый режим, а обычный запрос. Значения структурного фильтра разбираются теми
    же правилами, что и значения языка: `{"assignee": ["me()"]}` и `assignee: me()` —
    один и тот же путь исполнения.
    """
    outcome = await service.search_issues(
        session,
        initiator=current_actor,
        query=payload.query,
        structured=payload.filter.to_terms() if payload.filter is not None else (),
        saved_filter_id=payload.saved_filter,
        sort=payload.sort,
        fields=payload.fields,
        limit=payload.limit,
        cursor=payload.cursor,
    )
    return search_page(outcome)
