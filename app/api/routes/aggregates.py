"""Агрегирующие эндпоинты: экраны фронтенда, собранные одним запросом.

Три маршрута под три реальных экрана — карточка задачи, первый экран приложения и
сводка по проекту. Существуют они ровно затем, чтобы страница не начиналась с пяти
обращений подряд: на медленной сети это пять задержек, и последний ответ приезжает,
когда пользователь уже проскроллил.

## Своей логики здесь нет и быть не должно

Каждый агрегат зовёт **те же сценарии**, что и отдельные эндпоинты, и складывает их
ответы в одну схему. Ни отбора, ни правил, ни проверок сверх тех, что делают сценарии,
он не добавляет. Иначе появился бы второй слой логики, который расходится с первым: у
задачи стало бы два набора доступных переходов, у проекта — два прогресса, и
расхождение вылезло бы не здесь, а в интерфейсе.

По той же причине агрегаты собраны в одном файле, а не разложены по своим роутерам:
правило «только сборка» проверяется чтением одного модуля, а не поиском по репозиторию.

## Коллекции внутри агрегата не листаются агрегатом

Под каждую коллекцию отдаётся первая страница и курсор **её собственного** эндпоинта.
Своей пагинации агрегат не заводит: второй способ листать одно и то же неизбежно
разойдётся с первым, а оболочка ответа проекта и не позволила бы положить рядом с
`data` несколько курсоров.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import (
    CurrentActorDep,
    FieldsParam,
    IssueKeyPath,
    LimitQuery,
    QueryParam,
    SessionDep,
    SortParam,
)
from app.api.schemas.actors import ActorRead
from app.api.schemas.aggregates import BootstrapRead, IssueCardRead, ProjectSummaryRead
from app.api.schemas.catalogs import IssueTypeRead, ResolutionRead, StatusRead
from app.api.schemas.checklists import ChecklistItemRead
from app.api.schemas.comments import CommentRead
from app.api.schemas.common import DataResponse
from app.api.schemas.fields import FieldRead
from app.api.schemas.issues import IssueRead
from app.api.schemas.links import IssueLinkRead
from app.api.schemas.projects import ProjectRead
from app.api.schemas.queues import QueueRead
from app.api.schemas.search import IssueSearchRead
from app.api.schemas.workflows import IssueTransitionRead
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.catalogs import CatalogKind
from app.domain.projects import Progress
from app.services import catalogs as catalogs_service
from app.services import checklists as checklists_service
from app.services import comments as comments_service
from app.services import fields as fields_service
from app.services import issues as issues_service
from app.services import links as links_service
from app.services import notifications as notifications_service
from app.services import projects as projects_service
from app.services import queues as queues_service
from app.services import workflow as workflow_service

router = APIRouter(tags=["aggregates"])

ProjectKeyPath = Annotated[
    str,
    Path(description="Project key, immutable", examples=["alpha"]),
]

# Размер вложенной страницы объявлен параметром, а не константой: экран задачи с
# сотней комментариев и экран задачи с тремя — разные запросы, и решать, сколько
# реплик показать сразу, должен тот, кто рисует экран.
CardPageSize = Annotated[
    int,
    Query(
        ge=1,
        le=100,
        description=(
            "How many comments and links to include. The rest is fetched from their own "
            "endpoints with the cursor this response carries"
        ),
    ),
]


@router.get("/bootstrap", summary="Everything the interface needs to draw its first screen")
async def read_bootstrap(
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[BootstrapRead]:
    """Стартовые данные: текущий актор, очереди, глобальные справочники, непрочитанное.

    Отдаются только **глобальные** записи справочников и полей. Локальные принадлежат
    своей очереди, и вывалить их все в стартовый ответ значило бы прислать интерфейсу
    ключи, которые он не имеет права показать вне этой очереди; конфигурацию очереди
    целиком отдаёт `GET /queues/{queue_key}/config`.

    Очереди — только неархивные: архив в навигации не нужен, а полный список отдаёт
    `GET /queues?is_archived=true`.

    Списки не листаются: это справочники установки, а не данные. Если их когда-нибудь
    станет столько, что страница понадобится, чинить надо будет не этот маршрут — он
    честно упрётся в потолок размера страницы и это будет видно.
    """
    queues = await queues_service.list_queues(
        session,
        initiator=current_actor,
        is_archived=False,
        limit=DEFAULT_PAGE_SIZE,
    )
    statuses = await catalogs_service.list_entries(
        session, CatalogKind.STATUS, initiator=current_actor, is_active=True
    )
    issue_types = await catalogs_service.list_entries(
        session, CatalogKind.ISSUE_TYPE, initiator=current_actor, is_active=True
    )
    resolutions = await catalogs_service.list_entries(
        session, CatalogKind.RESOLUTION, initiator=current_actor, is_active=True
    )
    registry = await fields_service.list_fields(session, initiator=current_actor, is_hidden=False)
    unread = await notifications_service.count_unread(session, initiator=current_actor)
    return DataResponse[BootstrapRead](
        data=BootstrapRead(
            actor=ActorRead.model_validate(current_actor),
            queues=[QueueRead.of(queue) for queue in queues.items],
            statuses=[StatusRead.of(entry) for entry in statuses.items],
            issue_types=[IssueTypeRead.of(entry) for entry in issue_types.items],
            resolutions=[ResolutionRead.of(entry) for entry in resolutions.items],
            fields=[FieldRead.of(field) for field in registry.items],
            unread_notifications=unread,
        )
    )


@router.get("/issues/{issue_key}/card", summary="Read an issue with everything on its screen")
async def read_issue_card(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: CardPageSize = DEFAULT_PAGE_SIZE,
) -> DataResponse[IssueCardRead]:
    """Карточка задачи целиком: задача, переходы, связи, обсуждение, чеклист.

    Пять запросов в одном. Каждая часть приходит ровно той же формой, что и от своего
    эндпоинта, — карточка их не пересобирает.

    Переходы считаются от текущего статуса и с учётом заполненности полей, поэтому
    недоступный переход приезжает вместе с тем, чего ему не хватает: интерфейс может
    объяснить отказ до того, как пользователь нажмёт кнопку.
    """
    issue = await issues_service.get_issue_by_key(session, issue_key)
    transitions = await workflow_service.available_transitions(
        session,
        issue,
        initiator=current_actor,
        filled_fields=issues_service.filled_fields_for(issue),
    )
    links = await links_service.list_issue_links(
        session, issue, initiator=current_actor, limit=limit
    )
    comments = await comments_service.list_comments(
        session, issue, initiator=current_actor, limit=limit
    )
    checklist = await checklists_service.list_items(session, issue, initiator=current_actor)
    return DataResponse[IssueCardRead](
        data=IssueCardRead(
            issue=IssueRead.of(issue),
            transitions=[IssueTransitionRead.of(item) for item in transitions],
            links=[IssueLinkRead.of(view) for view in links.items],
            links_next_cursor=links.next_cursor,
            comments=[CommentRead.of(comment, issue_key=issue.key) for comment in comments.items],
            comments_next_cursor=comments.next_cursor,
            checklist=[ChecklistItemRead.of(item, issue_key=issue.key) for item in checklist],
        )
    )


@router.get(
    "/projects/{project_key}/summary",
    summary="Read a project with its progress and issues",
    response_model_exclude_unset=True,
)
async def read_project_summary(
    project_key: ProjectKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    query: QueryParam = None,
    sort: SortParam = None,
    fields: FieldsParam = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
) -> DataResponse[ProjectSummaryRead]:
    """Сводка проекта: карточка с прогрессом и первая страница задач.

    Задачи отбираются тем же сценарием, что и `GET /projects/{project_key}/issues`, —
    то есть обычным поиском с приклеенным условием проекта. Поэтому `query`, `sort` и
    `fields` здесь работают ровно так же и сузить выдачу могут, а вывести её за
    пределы проекта — нет.
    """
    project = await projects_service.get_project_by_key(session, project_key)
    progress = await projects_service.project_progress(session, [project])
    outcome = await projects_service.list_project_issues(
        session,
        project,
        initiator=current_actor,
        query=query,
        sort=sort or (),
        fields=fields or (),
        limit=limit,
    )
    return DataResponse[ProjectSummaryRead](
        data=ProjectSummaryRead(
            project=ProjectRead.of(project, progress=progress.get(project.id, Progress())),
            issues=[
                IssueSearchRead.of(
                    issue,
                    fields=outcome.resolved.fields,
                    value_refs=outcome.resolved.value_refs,
                )
                for issue in outcome.page.items
            ],
            issues_next_cursor=outcome.page.next_cursor,
        )
    )
