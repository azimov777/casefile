"""Спринты: планирование, запуск, завершение и состав.

Спринт принадлежит доске, но живёт под своим префиксом, а не под `/boards/{id}/sprints`.
Причина в адресации: спринт адресуется идентификатором, и путь через доску добавил бы к
нему вторую изменяемую часть — при переносе спринта на другую доску (а такое бывает при
пересборке досок) ссылка на него сломалась бы. Доска задаётся параметром `board` в
списке и полем в теле создания.

Запуск и завершение — отдельные маршруты, а не поле `state` в частичном обновлении.
Завершение уводит незакрытые задачи, и «поменять поле» здесь означало бы операцию с
последствиями, о которых из тела запроса не догадаться.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

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
from app.api.schemas.boards import (
    SprintCompleteRequest,
    SprintCompletionRead,
    SprintCreate,
    SprintIssuesAdd,
    SprintRead,
    SprintUpdate,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.search import IssueSearchRead, search_page
from app.core.sentinels import UNSET
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.boards import SprintState
from app.services import boards as service
from app.services import issues as issues_service
from app.services.boards import SprintChanges

router = APIRouter(prefix="/sprints", tags=["sprints"])

SprintIdPath = Annotated[uuid.UUID, Path(description="Sprint UUID")]
BoardQuery = Annotated[uuid.UUID | None, Query(description="Board UUID: list its sprints only")]
# Псевдоним с `alias`, а не голое имя параметра: `status` в модуле занято импортом кодов
# FastAPI, а наружу параметр обязан называться именно `state`.
StateQuery = Annotated[
    SprintState | None,
    Query(alias="state", description="Filter by sprint state"),
]


@router.get("", summary="List sprints")
async def list_sprints(
    session: SessionDep,
    current_actor: CurrentActorDep,
    board: BoardQuery = None,
    sprint_state: StateQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[SprintRead]:
    """Страница спринтов в порядке создания."""
    page = await service.list_sprints(
        session,
        initiator=current_actor,
        board=(
            None
            if board is None
            else await service.read_board(session, board, initiator=current_actor)
        ),
        state=sprint_state,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[SprintRead].of(
        [SprintRead.of(sprint) for sprint in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Plan a sprint")
async def create_sprint(
    payload: SprintCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SprintRead]:
    """Заводит спринт в состоянии «планируется».

    Сразу активным он не заводится: у доски активный спринт не более одного, и слияние
    создания с запуском давало бы отказ «уже есть активный» на попытку **запланировать**
    следующий.
    """
    board = await service.read_board(session, payload.board, initiator=current_actor)
    sprint = await service.create_sprint(
        session,
        initiator=current_actor,
        board=board,
        name=payload.name,
        goal=payload.goal,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return DataResponse[SprintRead](data=SprintRead.of(sprint))


@router.get("/{sprint_id}", summary="Read a sprint")
async def read_sprint(
    sprint_id: SprintIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SprintRead]:
    """Карточка спринта. Задачи отдаёт отдельный маршрут."""
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    return DataResponse[SprintRead](data=SprintRead.of(sprint))


@router.patch("/{sprint_id}", summary="Update a sprint")
async def update_sprint(
    sprint_id: SprintIdPath,
    payload: SprintUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SprintRead]:
    """Меняет только переданные поля. Состояние правят `start` и `complete`."""
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    given = payload.model_dump(exclude_unset=True)
    updated, _ = await service.update_sprint(
        session,
        sprint,
        initiator=current_actor,
        changes=SprintChanges(
            name=given.get("name", UNSET),
            goal=given.get("goal", UNSET),
            start_date=given.get("start_date", UNSET),
            end_date=given.get("end_date", UNSET),
        ),
    )
    return DataResponse[SprintRead](data=SprintRead.of(updated))


@router.delete(
    "/{sprint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a sprint",
)
async def delete_sprint(
    sprint_id: SprintIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет пустой спринт: маршрут существует ради опечатки при планировании.

    Спринт с задачами отвечает `sprint_not_empty` — удаление унесло бы их
    принадлежность молча; активный отвечает `sprint_state_invalid` — отмена идущей
    работы не бывает исправлением записи.
    """
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    await service.delete_sprint(session, sprint, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{sprint_id}/start", summary="Start a sprint")
async def start_sprint(
    sprint_id: SprintIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SprintRead]:
    """Запускает запланированный спринт.

    Не идемпотентно, в отличие от архивации проекта: повторный запуск означает, что
    клиент видит не то состояние, а тихий успех скрыл бы от него уже идущий спринт.
    У доски активный спринт не более одного — второй отвечает `board_sprint_active`.
    """
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    started = await service.start_sprint(session, sprint, initiator=current_actor)
    return DataResponse[SprintRead](data=SprintRead.of(started))


@router.post("/{sprint_id}/complete", summary="Complete a sprint")
async def complete_sprint(
    sprint_id: SprintIdPath,
    payload: SprintCompleteRequest,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SprintCompletionRead]:
    """Завершает активный спринт, уводя незакрытые задачи туда, куда сказал клиент.

    Выбор обязателен: «перенести в следующий спринт» и «вернуть в бэклог» — разные
    способы работать, и значения по умолчанию у него нет намеренно. Закрытые задачи
    остаются в спринте: он и есть запись о том, что команда успела.

    В ответе — ключи переехавших задач. Собрать их второй раз будет неоткуда: состав
    спринта нигде не хранится отдельно от самих задач.
    """
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    target = (
        None
        if payload.sprint is None
        else await service.read_sprint(session, payload.sprint, initiator=current_actor)
    )
    completion = await service.complete_sprint(
        session,
        sprint,
        initiator=current_actor,
        unfinished=payload.unfinished,
        target=target,
    )
    return DataResponse[SprintCompletionRead](data=SprintCompletionRead.of(completion))


@router.get(
    "/{sprint_id}/issues",
    summary="List issues of a sprint",
    response_model_exclude_unset=True,
)
async def list_sprint_issues(
    sprint_id: SprintIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    query: QueryParam = None,
    saved_filter: SavedFilterParam = None,
    sort: SortParam = None,
    fields: FieldsParam = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueSearchRead]:
    """Задачи спринта — это поиск с приклеенным условием `sprint: <id>`.

    Поэтому здесь работают язык запросов, сортировка, выбор возвращаемых полей и
    курсорная пагинация ровно так же, как в `GET /api/v1/search/issues`. Условие
    спринта склеивается по `and`, поэтому сузить выдачу клиент может, а выйти за
    пределы спринта — нет.

    Порядок здесь обычный, а не ранговый: список отвечает на вопрос «что взято в
    спринт», а не «в каком порядке это лежит на доске». Порядок карточек живёт на доске.
    """
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    outcome = await service.list_sprint_issues(
        session,
        sprint,
        initiator=current_actor,
        query=query,
        saved_filter_id=saved_filter,
        sort=sort or (),
        fields=fields or (),
        limit=limit,
        cursor=cursor,
    )
    return search_page(outcome)


@router.post("/{sprint_id}/issues", summary="Take issues into a sprint")
async def add_sprint_issues(
    sprint_id: SprintIdPath,
    payload: SprintIssuesAdd,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[SprintRead]:
    """Берёт задачи в спринт, в том числе из разных очередей.

    Задача, уже взятая в него, изменения не даёт и ошибкой не считается. Задача из
    другого спринта переезжает — это видно в её истории как обычное изменение поля.

    Версия каждой задачи растёт: изменение идёт через единую точку правки задачи и
    попадает в историю и в шину событий. Клиент, державший версию для оптимистичной
    блокировки, обязан задачу перечитать.
    """
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    issues = [await issues_service.get_issue_by_key(session, key) for key in payload.issues]
    await service.add_sprint_issues(session, sprint, initiator=current_actor, issues=issues)
    return DataResponse[SprintRead](data=SprintRead.of(sprint))


@router.delete(
    "/{sprint_id}/issues/{issue_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Take an issue out of a sprint",
)
async def remove_sprint_issue(
    sprint_id: SprintIdPath,
    issue_key: IssueKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Возвращает задачу из спринта в бэклог; сама задача остаётся в своей очереди.

    Задача, взятая в другой спринт, отвечает `sprint_not_found` с причиной
    `issue_not_in_sprint`: молчаливый `204` оставил бы клиента, перепутавшего спринт, с
    уверенностью, что задача вынута.
    """
    sprint = await service.read_sprint(session, sprint_id, initiator=current_actor)
    issue = await issues_service.get_issue_by_key(session, issue_key)
    await service.remove_sprint_issue(session, sprint, initiator=current_actor, issue=issue)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
