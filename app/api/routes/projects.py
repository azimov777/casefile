"""Проекты: карточка, состав, прогресс, перенос между портфелями.

Роутер только переводит HTTP в вызов сценария и обратно. Разрешение ссылок (`alice` →
актор, `platform` → портфель, `TRK-1` → задача) — тоже часть перевода: сценарий принимает
объекты, а не строки, и потому не зависит от того, кто его вызвал.

Проект адресуется ключом (`alpha`), а не идентификатором: тем же ключом он назван в
фильтре поиска (`project: alpha`), и два способа сослаться на один объект расходятся
первыми. Адресация мягкая: `/projects/Alpha` находит `alpha`.

Список задач проекта живёт под `/projects/{key}/issues` и внутри целиком повторяет
поиск: те же язык запросов, сортировка, выбор полей и курсор. Своего набора фильтров у
проекта нет намеренно — он разошёлся бы с поиском на первом же краевом случае.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentActorDep,
    CursorQuery,
    FieldsParam,
    IssueKeyPath,
    LimitQuery,
    QueryParam,
    SavedFilterParam,
    SessionDep,
    SortParam,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.projects import (
    PortfolioSet,
    ProjectCreate,
    ProjectIssuesAdd,
    ProjectRead,
    ProjectUpdate,
)
from app.api.schemas.search import IssueSearchRead, search_page
from app.core.sentinels import UNSET
from app.db.models.actor import Actor
from app.db.models.project import Portfolio, Project
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.projects import Progress, ProjectStatus
from app.services import actors as actors_service
from app.services import issues as issues_service
from app.services import projects as service
from app.services.projects import PlanningChanges

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectKeyPath = Annotated[
    str,
    Path(description="Project key, immutable", examples=["alpha"]),
]
PortfolioFilterQuery = Annotated[
    str | None,
    Query(description="Portfolio key: list projects lying directly in it"),
]
# Псевдоним с `alias`, а не голое имя параметра: `status` в модуле уже занято
# импортом кодов FastAPI, а наружу параметр обязан называться именно `status`.
StatusFilterQuery = Annotated[
    ProjectStatus | None,
    Query(alias="status", description="Filter by planning status"),
]
ArchivedFilterQuery = Annotated[
    bool | None,
    Query(description="Filter by the archived flag; omit to get both"),
]
LeadFilterQuery = Annotated[str | None, Query(description="Filter by the lead actor key")]


async def _portfolio(session: AsyncSession, key: str | None) -> Portfolio | None:
    return None if key is None else await service.get_portfolio_by_key(session, key)


async def _actor(session: AsyncSession, key: str | None) -> Actor | None:
    return None if key is None else await actors_service.get_actor_by_key(session, key)


async def _read(session: AsyncSession, project: Project) -> DataResponse[ProjectRead]:
    """Карточка проекта с посчитанным прогрессом.

    Прогресс считается здесь, а не хранится в колонке: задачу закрывают из REST, из MCP
    и массовым переносом статуса, и хранимая доля разошлась бы с реальностью в первую же
    неделю.
    """
    progress = await service.project_progress(session, [project])
    return DataResponse[ProjectRead](
        data=ProjectRead.of(project, progress=progress.get(project.id, Progress()))
    )


async def _changes(session: AsyncSession, payload: ProjectUpdate) -> PlanningChanges:
    """Тело запроса в термины сценария: ссылки разрешаются в объекты.

    Признак «не передано» обязан дожить до сценария: у `portfolio`, `start_date` и
    `end_date` есть осмысленный `null`, и склеить его с «не передано» здесь значило бы
    потерять разницу ровно там, ради чего она заведена.
    """
    given = payload.model_dump(exclude_unset=True)

    members: object = UNSET
    if "members" in given:
        members = [await actors_service.get_actor_by_key(session, key) for key in payload.members]

    lead: object = UNSET
    if "lead" in given:
        lead = await actors_service.get_actor_by_key(session, given["lead"])

    portfolio: object = UNSET
    if "portfolio" in given:
        portfolio = await _portfolio(session, given["portfolio"])

    return PlanningChanges(
        name=given.get("name", UNSET),
        description=given.get("description", UNSET),
        status=given.get("status", UNSET),
        lead=lead,
        members=members,
        start_date=given.get("start_date", UNSET),
        end_date=given.get("end_date", UNSET),
        tags=given.get("tags", UNSET),
        portfolio=portfolio,
    )


@router.get("", summary="List projects")
async def list_projects(
    session: SessionDep,
    current_actor: CurrentActorDep,
    portfolio: PortfolioFilterQuery = None,
    project_status: StatusFilterQuery = None,
    is_archived: ArchivedFilterQuery = None,
    lead: LeadFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ProjectRead]:
    """Страница проектов в порядке создания, с прогрессом каждого.

    Прогресс всей страницы считается одним запросом, а не по проекту: иначе список стал
    бы самым дорогим эндпоинтом в API.
    """
    page = await service.list_projects(
        session,
        initiator=current_actor,
        portfolio=await _portfolio(session, portfolio),
        status=project_status,
        is_archived=is_archived,
        lead=await _actor(session, lead),
        limit=limit,
        cursor=cursor,
    )
    progress = await service.project_progress(session, page.items)
    return CollectionResponse[ProjectRead].of(
        [
            ProjectRead.of(project, progress=progress.get(project.id, Progress()))
            for project in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a project")
async def create_project(
    payload: ProjectCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Заводит проект. Ответственный по умолчанию — актор, стоящий за токеном."""
    project = await service.create_project(
        session,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        lead=await _actor(session, payload.lead),
        members=[await actors_service.get_actor_by_key(session, key) for key in payload.members],
        start_date=payload.start_date,
        end_date=payload.end_date,
        tags=payload.tags,
        portfolio=await _portfolio(session, payload.portfolio),
    )
    return await _read(session, project)


@router.get("/{project_key}", summary="Read a project")
async def read_project(
    project_key: ProjectKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Карточка проекта с прогрессом. Задачи отдаёт отдельный маршрут."""
    project = await service.read_project(session, project_key, initiator=current_actor)
    return await _read(session, project)


@router.patch("/{project_key}", summary="Update a project")
async def update_project(
    project_key: ProjectKeyPath,
    payload: ProjectUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Меняет только переданные поля. Ключ проекта неизменяем и в теле не принимается."""
    project = await service.read_project(session, project_key, initiator=current_actor)
    updated, _ = await service.update_project(
        session,
        project,
        initiator=current_actor,
        changes=await _changes(session, payload),
    )
    return await _read(session, updated)


@router.put("/{project_key}/portfolio", summary="Move a project to another portfolio")
async def move_project(
    project_key: ProjectKeyPath,
    payload: PortfolioSet,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Переносит проект в другой портфель; `null` вынимает его наверх.

    То же самое умеет и частичное обновление. Отдельный маршрут существует потому, что
    перенос — самостоятельная операция планирования: когда появятся роли, разрешать
    «двигать проекты по портфелям» придётся отдельно от «править описание».
    """
    project = await service.read_project(session, project_key, initiator=current_actor)
    moved = await service.move_project(
        session,
        project,
        initiator=current_actor,
        portfolio=await _portfolio(session, payload.portfolio),
    )
    return await _read(session, moved)


@router.post("/{project_key}/archive", summary="Archive a project")
async def archive_project(
    project_key: ProjectKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Убирает проект в архив: новых задач он не принимает, всё остальное остаётся.

    Идемпотентно — повторный запрос отвечает так же и ничего не меняет. Задачи из
    проекта не вынимаются, прогресс продолжает считаться: архив прячет проект из
    рабочих списков, а не стирает его результат.
    """
    project = await service.read_project(session, project_key, initiator=current_actor)
    archived = await service.archive_project(session, project, initiator=current_actor)
    return await _read(session, archived)


@router.post("/{project_key}/unarchive", summary="Restore a project from the archive")
async def unarchive_project(
    project_key: ProjectKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Возвращает проект из архива. Тоже идемпотентно."""
    project = await service.read_project(session, project_key, initiator=current_actor)
    restored = await service.restore_project(session, project, initiator=current_actor)
    return await _read(session, restored)


@router.get(
    "/{project_key}/issues",
    summary="List issues of a project",
    response_model_exclude_unset=True,
)
async def list_project_issues(
    project_key: ProjectKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    query: QueryParam = None,
    saved_filter: SavedFilterParam = None,
    sort: SortParam = None,
    fields: FieldsParam = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueSearchRead]:
    """Задачи проекта — это поиск с приклеенным условием `project: <ключ>`.

    Поэтому здесь работают язык запросов, сортировка, выбор возвращаемых полей и
    курсорная пагинация ровно так же, как в `GET /api/v1/search/issues`. Условие проекта
    склеивается по `and`, поэтому сузить выдачу клиент может, а выйти за пределы проекта
    — нет.

    В проекте бывают тысячи задач из разных очередей, поэтому `fields` здесь особенно
    полезен: полная задача на сто позиций съедает контекст агента целиком.
    """
    project = await service.read_project(session, project_key, initiator=current_actor)
    outcome = await service.list_project_issues(
        session,
        project,
        initiator=current_actor,
        query=query,
        saved_filter_id=saved_filter,
        sort=sort or (),
        fields=fields or (),
        limit=limit,
        cursor=cursor,
    )
    return search_page(outcome)


@router.post("/{project_key}/issues", summary="Add issues to a project")
async def add_project_issues(
    project_key: ProjectKeyPath,
    payload: ProjectIssuesAdd,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[ProjectRead]:
    """Добавляет задачи в проект, в том числе из разных очередей.

    Задача, уже входящая в проект, изменения не даёт и ошибкой не считается. Задача из
    другого проекта переезжает — это видно в её истории как обычное изменение поля.

    Версия каждой добавленной задачи растёт: изменение идёт через единую точку правки
    задачи и попадает в историю и в шину событий. Клиент, державший версию для
    оптимистичной блокировки, обязан задачу перечитать.
    """
    project = await service.read_project(session, project_key, initiator=current_actor)
    issues = [await issues_service.get_issue_by_key(session, key) for key in payload.issues]
    await service.add_issues(session, project, initiator=current_actor, issues=issues)
    return await _read(session, project)


@router.delete(
    "/{project_key}/issues/{issue_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an issue from a project",
)
async def remove_project_issue(
    project_key: ProjectKeyPath,
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Убирает задачу из проекта; сама задача остаётся жить в своей очереди.

    Задача, входящая в другой проект, отвечает `project_not_found` с причиной
    `issue_not_in_project`: молчаливый `204` оставил бы клиента, перепутавшего проект, с
    уверенностью, что задача вынута.
    """
    project = await service.read_project(session, project_key, initiator=current_actor)
    issue = await issues_service.get_issue_by_key(session, issue_key)
    await service.remove_issue(session, project, initiator=current_actor, issue=issue)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
