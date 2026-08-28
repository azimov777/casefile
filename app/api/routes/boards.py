"""Доски: настройки, колонки, сборка по колонкам и перемещение карточек.

Роутер только переводит HTTP в вызов сценария и обратно. Разрешение ссылок (`open` →
статус, `TRK-1` → задача, идентификатор → доска) — тоже часть перевода: сценарий
принимает объекты, а не строки, и потому не зависит от того, кто его вызвал.

## Доска собирается покомпонентно

Одним ответом доска не отдаётся, и это требование задачи: одна доска может тянуть тысячи
задач. Карточка доски (`GET /boards/{id}`) отдаёт настройки и колонки, задачи каждой
колонки — свой маршрут со своей курсорной пагинацией и своим `fields`. Иначе под `data`
пришлось бы класть несколько коллекций и несколько курсоров, а оболочка ответа проекта
этого не допускает.

## Два разных движения карточки — два разных маршрута

`PUT .../rank` меняет только порядок: статуса не касается, версию задачи не поднимает, в
её историю не попадает. `POST .../column` меняет статус и потому идёт **переходом
воркфлоу** со всеми его проверками. Слить их в один маршрут значило бы либо провести
смену статуса мимо процесса, либо требовать перехода на перестановку внутри колонки.
"""

import uuid
from collections.abc import Sequence
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
    SessionDep,
)
from app.api.schemas.boards import (
    BoardColumnCreate,
    BoardColumnInput,
    BoardColumnUpdate,
    BoardCreate,
    BoardIssueMove,
    BoardRead,
    BoardUpdate,
    IssueRankSet,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.issues import IssueRead
from app.api.schemas.search import IssueSearchRead, search_page
from app.core.sentinels import UNSET
from app.db.models.actor import Actor
from app.db.models.board import Board, BoardColumn
from app.db.models.catalog import Status
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.catalogs import CatalogKind
from app.services import boards as service
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services import saved_filters as saved_filters_service
from app.services.boards import BoardChanges, ColumnDraft

router = APIRouter(prefix="/boards", tags=["boards"])

BoardIdPath = Annotated[uuid.UUID, Path(description="Board UUID")]
ColumnIdPath = Annotated[uuid.UUID, Path(description="Board column UUID")]
SavedFilterQuery = Annotated[
    uuid.UUID | None,
    Query(description="Saved filter UUID: list boards built on it"),
]


async def _status(session: AsyncSession, ref: str, *, initiator: Actor) -> Status:
    """Ссылка справочника в запись статуса.

    Разрешение ссылки — работа интерфейса: сценарий принимает объекты и потому не
    зависит от того, кто его позвал. Проверку прав на чтение справочника делает сам
    `resolve_catalog_ref`.
    """
    entry = await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.STATUS,
        ref,
        initiator=initiator,
    )
    assert isinstance(entry, Status)
    return entry


async def _drafts(
    session: AsyncSession,
    columns: Sequence[BoardColumnInput],
    *,
    initiator: Actor,
) -> list[ColumnDraft]:
    """Описания колонок из тела запроса: ссылки статусов разрешаются в записи."""
    return [
        ColumnDraft(
            name=column.name,
            statuses=[await _status(session, ref, initiator=initiator) for ref in column.statuses],
            wip_limit=column.wip_limit,
        )
        for column in columns
    ]


def _column(board: Board, column_id: uuid.UUID | None) -> BoardColumn | None:
    return None if column_id is None else service.get_column(board, column_id)


@router.get("", summary="List boards")
async def list_boards(
    session: SessionDep,
    current_actor: CurrentActorDep,
    saved_filter: SavedFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[BoardRead]:
    """Страница досок в порядке создания, с колонками каждой.

    Колонки входят в список, а не только в карточку: их число ограничено доменом, они
    и есть то, чем одна доска отличается от другой, и второй запрос за ними на каждую
    строку списка был бы дороже, чем они сами.
    """
    page = await service.list_boards(
        session,
        initiator=current_actor,
        saved_filter=(
            None
            if saved_filter is None
            else await saved_filters_service.get_saved_filter(session, saved_filter)
        ),
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[BoardRead].of(
        [BoardRead.of(board) for board in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a board")
async def create_board(
    payload: BoardCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[BoardRead]:
    """Заводит доску вместе с колонками в порядке, в котором они перечислены."""
    board = await service.create_board(
        session,
        initiator=current_actor,
        name=payload.name,
        description=payload.description,
        saved_filter=await saved_filters_service.get_saved_filter(session, payload.saved_filter),
        columns=await _drafts(session, payload.columns, initiator=current_actor),
    )
    return DataResponse[BoardRead](data=BoardRead.of(board))


@router.get("/{board_id}", summary="Read a board")
async def read_board(
    board_id: BoardIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[BoardRead]:
    """Настройки доски и её колонки. Задачи отдают отдельные маршруты."""
    board = await service.read_board(session, board_id, initiator=current_actor)
    return DataResponse[BoardRead](data=BoardRead.of(board))


@router.patch("/{board_id}", summary="Update a board")
async def update_board(
    board_id: BoardIdPath,
    payload: BoardUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[BoardRead]:
    """Меняет только переданные поля. Колонки правятся своими маршрутами."""
    board = await service.read_board(session, board_id, initiator=current_actor)
    given = payload.model_dump(exclude_unset=True)
    saved_filter: object = UNSET
    if "saved_filter" in given:
        saved_filter = await saved_filters_service.get_saved_filter(session, given["saved_filter"])
    updated, _ = await service.update_board(
        session,
        board,
        initiator=current_actor,
        changes=BoardChanges(
            name=given.get("name", UNSET),
            description=given.get("description", UNSET),
            saved_filter=saved_filter,
        ),
    )
    return DataResponse[BoardRead](data=BoardRead.of(updated))


@router.delete(
    "/{board_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a board",
)
async def delete_board(
    board_id: BoardIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Удаляет доску с колонками и рангами. Задачи при этом не трогаются.

    Доска отбирает задачи сохранённым фильтром и владеть ими не может: после удаления
    доски задачи остаются на месте, теряется только порядок карточек.
    """
    board = await service.read_board(session, board_id, initiator=current_actor)
    await service.delete_board(session, board, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{board_id}/columns",
    status_code=status.HTTP_201_CREATED,
    summary="Add a column to a board",
)
async def add_board_column(
    board_id: BoardIdPath,
    payload: BoardColumnCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[BoardRead]:
    """Добавляет колонку. Место задаётся соседом: без `after` — в конец, `null` — в начало.

    В ответе вся доска, а не одна колонка: добавление меняет порядок остальных, и
    отдать только новую значило бы заставить клиента перечитать доску следующим запросом.
    """
    board = await service.read_board(session, board_id, initiator=current_actor)
    given = payload.model_dump(exclude_unset=True)
    after: object = UNSET
    if "after" in given:
        after = _column(board, given["after"])
    drafts = await _drafts(session, [payload], initiator=current_actor)
    await service.add_column(
        session,
        board,
        initiator=current_actor,
        draft=drafts[0],
        after=after,
    )
    return DataResponse[BoardRead](data=BoardRead.of(board))


@router.patch("/{board_id}/columns/{column_id}", summary="Update a board column")
async def update_board_column(
    board_id: BoardIdPath,
    column_id: ColumnIdPath,
    payload: BoardColumnUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[BoardRead]:
    """Меняет колонку: название, статусы, лимит и место среди соседей."""
    board = await service.read_board(session, board_id, initiator=current_actor)
    column = service.get_column(board, column_id)
    given = payload.model_dump(exclude_unset=True)

    statuses: object = UNSET
    if "statuses" in given:
        statuses = [
            await _status(session, ref, initiator=current_actor) for ref in payload.statuses
        ]
    after: object = UNSET
    if "after" in given:
        after = _column(board, given["after"])

    await service.update_column(
        session,
        board,
        column,
        initiator=current_actor,
        name=given.get("name", UNSET),
        statuses=statuses,
        wip_limit=given.get("wip_limit", UNSET),
        after=after,
    )
    return DataResponse[BoardRead](data=BoardRead.of(board))


@router.delete(
    "/{board_id}/columns/{column_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a column from a board",
)
async def remove_board_column(
    board_id: BoardIdPath,
    column_id: ColumnIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> Response:
    """Убирает колонку. Задачи не трогаются — их статусы просто перестают показываться."""
    board = await service.read_board(session, board_id, initiator=current_actor)
    column = service.get_column(board, column_id)
    await service.remove_column(session, board, column, initiator=current_actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{board_id}/columns/{column_id}/issues",
    summary="List issues of a board column",
    response_model_exclude_unset=True,
)
async def list_board_column_issues(
    board_id: BoardIdPath,
    column_id: ColumnIdPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    query: QueryParam = None,
    fields: FieldsParam = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[IssueSearchRead]:
    """Карточки одной колонки, в порядке ранга доски.

    Отбор — это фильтр доски плюс статусы колонки, склеенные по `and`. Поэтому `query`
    может сузить выдачу языком запросов, но не может вывести её за пределы колонки.

    Параметра сортировки здесь нет намеренно: порядок задаёт ранг доски, и возможность
    его переопределить сделала бы перетаскивание карточки бессмысленным.
    """
    board = await service.read_board(session, board_id, initiator=current_actor)
    column = service.get_column(board, column_id)
    outcome = await service.list_column_issues(
        session,
        board,
        column,
        initiator=current_actor,
        query=query,
        fields=fields or (),
        limit=limit,
        cursor=cursor,
    )
    return search_page(outcome)


@router.put("/{board_id}/issues/{issue_key}/rank", summary="Rank an issue on a board")
async def rank_board_issue(
    board_id: BoardIdPath,
    issue_key: IssueKeyPath,
    payload: IssueRankSet,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Ставит карточку до или после указанной задачи.

    Только порядок: статус задачи не меняется, версия не растёт, в историю ничего не
    попадает. Перестановка видна событием `board.issue_ranked` — оно принадлежит доске,
    а не задаче, потому что ранг у каждой доски свой.

    Позиция наружу не отдаётся: место задаётся соседом, и знать внутреннее число шкалы
    клиенту незачем — при перенумерации доски все они меняются, сохраняя порядок.
    """
    board = await service.read_board(session, board_id, initiator=current_actor)
    issue = await issues_service.read_issue(session, issue_key, initiator=current_actor)
    given = payload.model_dump(exclude_unset=True)

    after: object = UNSET
    if "after" in given:
        after = (
            None
            if given["after"] is None
            else await issues_service.get_issue_by_key(session, given["after"])
        )
    before: object = UNSET
    if "before" in given:
        before = (
            None
            if given["before"] is None
            else await issues_service.get_issue_by_key(session, given["before"])
        )

    await service.rank_issue(
        session,
        board,
        issue,
        initiator=current_actor,
        after=after,
        before=before,
    )
    return DataResponse[IssueRead](data=IssueRead.of(issue))


@router.post("/{board_id}/issues/{issue_key}/column", summary="Move a card to another column")
async def move_board_issue(
    board_id: BoardIdPath,
    issue_key: IssueKeyPath,
    payload: BoardIssueMove,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[IssueRead]:
    """Переносит карточку в колонку **переходом воркфлоу**, а не записью статуса.

    Поэтому маршрут может отказать так же, как обычная смена статуса: переходом, которого
    нет в процессе (`transition_not_allowed`), незаполненным обязательным полем
    (`transition_requirements_not_met`) или отсутствующей резолюцией
    (`issue_resolution_required`). Это не недоработка доски, а работающий процесс: если
    бы доска писала статус напрямую, через неё обходились бы все проверки задачи 07.

    Целевой статус обязателен, когда в колонке их несколько: выбирать за клиента —
    значит переводить задачу в статус, которого никто не просил.
    """
    board = await service.read_board(session, board_id, initiator=current_actor)
    column = service.get_column(board, payload.column)
    issue = await issues_service.read_issue(session, issue_key, initiator=current_actor)
    given = payload.model_dump(exclude_unset=True)

    target: Status | None = None
    if payload.status is not None:
        target = await _status(session, payload.status, initiator=current_actor)

    resolution: object = UNSET
    if "resolution" in given:
        resolution = (
            None
            if given["resolution"] is None
            else await queues_service.resolve_catalog_ref(
                session,
                CatalogKind.RESOLUTION,
                given["resolution"],
                initiator=current_actor,
            )
        )

    mutation = await service.move_issue_to_column(
        session,
        board,
        issue,
        column,
        initiator=current_actor,
        status=target,
        resolution=resolution,
        expected_version=payload.version,
    )
    return DataResponse[IssueRead](data=IssueRead.of(mutation.issue))
