"""Задачи: создание, чтение, частичное обновление, исполнитель, наблюдатели.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет, иначе
те же операции из MCP пошли бы другим путём и мимо будущих событий. Разрешение ссылок
(`TRK` → очередь, `open` → статус, `alice` → актор) — тоже часть перевода: сценарий
принимает объекты, а не строки, и потому не зависит от того, кто его вызвал.

Задача адресуется ключом (`TRK-123`), а не числовым идентификатором, — так требуют
соглашения. Адресация мягкая: `trk-123` находит ту же задачу.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActorDep, CursorQuery, IssueKeyPath, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.events import ChangelogEntryRead
from app.api.schemas.issues import (
    IssueAssign,
    IssueCreate,
    IssueFollowerAdd,
    IssueRead,
    IssueUpdate,
)
from app.core.sentinels import UNSET
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.catalogs import CatalogKind
from app.services import actors as actors_service
from app.services import boards as boards_service
from app.services import events as events_service
from app.services import issues as service
from app.services import projects as projects_service
from app.services import queues as queues_service
from app.services.issues import IssueChanges

router = APIRouter(prefix="/issues", tags=["issues"])

QueueFilterQuery = Annotated[
    str | None,
    Query(description="Queue key: list issues of this queue only. Omit to list every issue"),
]


async def _actor(session: AsyncSession, key: str | None) -> Actor | None:
    return None if key is None else await actors_service.get_actor_by_key(session, key)


async def _project(session: AsyncSession, key: str | None) -> Any:
    return None if key is None else await projects_service.get_project_by_key(session, key)


async def _sprint(session: AsyncSession, sprint_id: uuid.UUID | None) -> Any:
    return None if sprint_id is None else await boards_service.get_sprint_by_id(session, sprint_id)


async def _catalog_entry(
    session: AsyncSession,
    kind: CatalogKind,
    ref: str | None,
    current_actor: Actor,
) -> Any:
    if ref is None:
        return None
    return await queues_service.resolve_catalog_ref(session, kind, ref, initiator=current_actor)


async def _changes(
    session: AsyncSession,
    payload: IssueUpdate,
    current_actor: Actor,
) -> IssueChanges:
    """Тело запроса в термины сценария: ссылки разрешаются в объекты.

    Разрешать умеет только HTTP-слой, потому что только он получил строки. Признак «не
    передано» при этом обязан дожить до сценария: у `resolution`, `assignee` и
    `deadline` есть осмысленный `null`, и склеить его с «не передано» здесь значило бы
    потерять разницу ровно в том месте, ради которого она заведена.
    """
    given = payload.model_dump(exclude_unset=True)

    async def catalog(name: str, kind: CatalogKind) -> Any:
        if name not in given:
            return UNSET
        ref = given[name]
        return None if ref is None else await _catalog_entry(session, kind, ref, current_actor)

    assignee: Any = UNSET
    if "assignee" in given:
        assignee = await _actor(session, given["assignee"])

    project: Any = UNSET
    if "project" in given:
        project = await _project(session, given["project"])

    sprint: Any = UNSET
    if "sprint" in given:
        sprint = await _sprint(session, given["sprint"])

    return IssueChanges(
        summary=given.get("summary", UNSET),
        description=given.get("description", UNSET),
        issue_type=await catalog("issue_type", CatalogKind.ISSUE_TYPE),
        status=await catalog("status", CatalogKind.STATUS),
        resolution=await catalog("resolution", CatalogKind.RESOLUTION),
        priority=given.get("priority", UNSET),
        assignee=assignee,
        deadline=given.get("deadline", UNSET),
        project=project,
        sprint=sprint,
        tags=given.get("tags", UNSET),
        values=given.get("values", UNSET),
    )


@router.get("", summary="List issues")
async def list_issues(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueRead]:
    """Страница задач в порядке создания.

    Простое перечисление: отбор по статусу, исполнителю и значениям полей, а также язык
    запросов появятся в задаче 12 отдельным эндпоинтом поиска.
    """
    page = await service.list_issues(
        session,
        initiator=current_actor,
        queue=await queues_service.resolve_scope(session, queue),
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[IssueRead].of(
        [IssueRead.of(issue) for issue in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an issue")
async def create_issue(
    payload: IssueCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Заводит задачу. Ключ выдаёт счётчик очереди, клиент его не выбирает."""
    queue = await queues_service.get_queue_by_key(session, payload.queue)
    issue_type: IssueType | None = await _catalog_entry(
        session, CatalogKind.ISSUE_TYPE, payload.issue_type, current_actor
    )
    issue_status: Status | None = await _catalog_entry(
        session, CatalogKind.STATUS, payload.status, current_actor
    )
    resolution: Resolution | None = await _catalog_entry(
        session, CatalogKind.RESOLUTION, payload.resolution, current_actor
    )
    followers = [await actors_service.get_actor_by_key(session, key) for key in payload.followers]
    issue = await service.create_issue(
        session,
        initiator=current_actor,
        queue=queue,
        summary=payload.summary,
        description=payload.description,
        issue_type=issue_type,
        status=issue_status,
        resolution=resolution,
        priority=payload.priority,
        author=await _actor(session, payload.author),
        assignee=await _actor(session, payload.assignee),
        followers=followers,
        deadline=payload.deadline,
        tags=payload.tags,
        project=await _project(session, payload.project),
        sprint=await _sprint(session, payload.sprint),
        values=payload.values,
    )
    return DataResponse[IssueRead](data=IssueRead.of(issue))


@router.get("/{issue_key}", summary="Read an issue")
async def read_issue(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    issue = await service.read_issue(session, issue_key, initiator=current_actor)
    return DataResponse[IssueRead](data=IssueRead.of(issue))


@router.get("/{issue_key}/changelog", summary="Read the issue changelog")
async def read_issue_changelog(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[ChangelogEntryRead]:
    """История изменений задачи: кто, когда и с какого значения на какое.

    Порядок хронологический, от старого к новому: так историю читают, и так работает
    единственная в проекте курсорная пагинация. Первая запись у любой задачи —
    `issue.created`, и список изменений у неё пуст: у создания нет «было».

    Значения в записи — ссылки на момент события (`open`, `TRK.open`, ключ актора), а
    не указатели на строки справочников. Поэтому переименованный или удалённый статус
    не портит историю задним числом.
    """
    issue = await service.get_issue_by_key(session, issue_key)
    page = await events_service.list_changelog(
        session,
        issue,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[ChangelogEntryRead].of(
        [ChangelogEntryRead.of(entry, issue_key=issue.key) for entry in page.items],
        next_cursor=page.next_cursor,
    )


@router.patch("/{issue_key}", summary="Update an issue")
async def update_issue(
    issue_key: IssueKeyPath,
    payload: IssueUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Меняет только переданные поля.

    Переданный `null` очищает поле там, где это осмысленно (`resolution`, `assignee`,
    `deadline`), отсутствующий ключ не трогает поле. `version` — не поле задачи, а
    условие: если задачу успели изменить, ответ будет `409 version_conflict`, а не
    молчаливая перезапись чужой работы.
    """
    issue = await service.get_issue_by_key(session, issue_key)
    mutation = await service.update_issue(
        session,
        issue,
        initiator=current_actor,
        changes=await _changes(session, payload, current_actor),
        expected_version=payload.version,
    )
    return DataResponse[IssueRead](data=IssueRead.of(mutation.issue))


@router.put("/{issue_key}/assignee", summary="Assign an issue")
async def assign_issue(
    issue_key: IssueKeyPath,
    payload: IssueAssign,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Назначает исполнителя или снимает его переданным `null`.

    То же самое умеет и частичное обновление. Отдельный маршрут существует потому, что
    назначение — самое частое действие агента и автоматики: у него своё действие в
    проверке прав и своё событие в задаче 06.
    """
    issue = await service.get_issue_by_key(session, issue_key)
    mutation = await service.assign_issue(
        session,
        issue,
        initiator=current_actor,
        assignee=await _actor(session, payload.assignee),
        expected_version=payload.version,
    )
    return DataResponse[IssueRead](data=IssueRead.of(mutation.issue))


@router.post("/{issue_key}/followers", summary="Add a follower")
async def add_issue_follower(
    issue_key: IssueKeyPath,
    payload: IssueFollowerAdd,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Подписывает актора на задачу. Повторный запрос отвечает так же и ничего не меняет."""
    issue = await service.get_issue_by_key(session, issue_key)
    mutation = await service.add_follower(
        session,
        issue,
        initiator=current_actor,
        actor=await actors_service.get_actor_by_key(session, payload.actor),
    )
    return DataResponse[IssueRead](data=IssueRead.of(mutation.issue))


@router.delete(
    "/{issue_key}/followers/{actor_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a follower",
)
async def remove_issue_follower(
    issue_key: IssueKeyPath,
    actor_key: Annotated[str, Path(description="Key of the actor to unsubscribe")],
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Отписывает актора. Идемпотентно: повторный запрос снова отвечает `204`.

    Версия задачи при удалении наблюдателя растёт, поэтому клиенту, который держит её
    для оптимистичной блокировки, задачу нужно перечитать.
    """
    issue = await service.get_issue_by_key(session, issue_key)
    await service.remove_follower(
        session,
        issue,
        initiator=current_actor,
        actor=await actors_service.get_actor_by_key(session, actor_key),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{issue_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an issue",
)
async def delete_issue(
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет задачу насовсем. Ключ при этом не освобождается и другой задаче не достанется."""
    issue = await service.get_issue_by_key(session, issue_key)
    await service.delete_issue(session, issue, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
