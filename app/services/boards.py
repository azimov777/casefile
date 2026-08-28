"""Сценарии досок, колонок, спринтов и ранжирования карточек.

Один модуль на четыре сущности — как проекты и портфели в `app/services/projects.py`:
доска не существует без колонок, спринт не существует без доски, а ранг не существует
без обоих. Разложить их по файлам значило бы получить кольцо импортов ради красоты
оглавления.

## Доска ничего не отбирает сама

Список задач колонки, бэклога и спринта — это **поиск с приклеенным условием**, ровно
как список задач проекта (`app/services/projects.py`, `list_project_issues`). Доска
добавляет к сохранённому фильтру условие по статусам колонки и по спринту, склеивает
всё по `and` и отдаёт в `app/services/search.py`. Поэтому клиент может сузить выдачу
своим запросом, но не может выйти за пределы доски, а язык запросов и выбор
возвращаемых полей работают здесь ровно так же, как в общем поиске.

Своего набора условий у доски нет и быть не должно: второй способ описать отбор
разошёлся бы с языком запросов на первом же краевом случае, и одна и та же доска
показывала бы разное во фронте и в автодействии.

## Порядок — единственное, что доска считает сама

Сортировки клиент здесь не задаёт: порядок на доске задаёт ранг, иначе перетаскивание
карточки перестало бы что-либо значить. Поэтому страницу собирает отдельный репозиторий
(`app/db/repositories/boards.py`), а не общий поиск, — но фильтр он получает от того же
`resolve_issue_filter`, а не разбирает сам.

## Перемещение карточки между колонками — это переход воркфлоу

`move_issue_to_column` не пишет статус, а собирает `IssueChanges` и зовёт
`apply_issue_changes` с действием `issue.transition`. Прямая запись статуса сделала бы
доску дырой в процессе: через неё можно было бы обойти любую проверку из задачи 07.
Отсюда же следует, что перемещение может отказать — например, потребовать резолюцию, —
и это не недоработка доски, а работающий процесс.

Перестановка карточки внутри колонки (`rank_issue`), наоборот, статуса не трогает
вовсе: она меняет только ранг, не поднимает версию задачи и в её историю не попадает.

Транзакцию сценарии не фиксируют: границу держит вход в приложение.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.board import Board, BoardColumn, BoardColumnStatus, Sprint
from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.models.saved_filter import SavedFilter
from app.db.pagination import Page
from app.db.repositories import BoardIssueRepository, BoardRepository, SprintRepository
from app.db.repositories.search import compile_filter
from app.domain.boards import (
    SprintState,
    UnfinishedPolicy,
    ensure_column_capacity,
    ensure_column_count,
    ensure_column_statuses,
    validate_board_description,
    validate_board_name,
    validate_column_name,
    validate_sprint_goal,
    validate_sprint_name,
    validate_sprint_period,
    validate_wip_limit,
)
from app.domain.errors import (
    BoardColumnNotFoundError,
    BoardHasSprintsError,
    BoardNotFoundError,
    BoardSprintActiveError,
    BoardStatusTakenError,
    InvalidBoardError,
    InvalidBoardMoveError,
    IssueNotOnBoardError,
    SprintNotEmptyError,
    SprintNotFoundError,
    SprintStateError,
)
from app.domain.issues import IssueChange
from app.domain.ranking import position_between
from app.domain.search import ResolvedFilter, SystemField
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import search as search_service
from app.services.catalogs import format_entry_ref
from app.services.permissions import ensure_allowed

#: Значение параметра «область спринта», означающее бэклог доски. Слово, а не пустая
#: строка: параметр принимает ещё идентификатор спринта и `current`, и «пусто» в этом
#: ряду читалось бы как «фильтра нет», то есть ровно наоборот.
SPRINT_SCOPE_BACKLOG = "backlog"


@dataclass(frozen=True, slots=True)
class BoardChanges:
    """Что меняем в доске. Не переданное поле остаётся `UNSET`.

    Колонок здесь нет: у них свои сценарии, потому что колонка — объект со своим
    идентификатором и своим порядком, а не значение поля доски. Замена набора колонок
    одним присваиванием потеряла бы их идентификаторы, а вместе с ними — ранги и
    ссылки, которые клиент держит открытыми.
    """

    name: str = UNSET
    description: str = UNSET
    saved_filter: SavedFilter = UNSET


@dataclass(frozen=True, slots=True)
class SprintChanges:
    """Что меняем в спринте. Состояние сюда не входит.

    Запуск и завершение — отдельные сценарии со своими проверками и своими событиями:
    «поменять поле `state` на `active`» и «запустить спринт» должны быть одной
    операцией, иначе спринт можно было бы завершить, не разобравшись с незакрытыми
    задачами.
    """

    name: str = UNSET
    goal: str = UNSET
    start_date: date | None = UNSET
    end_date: date | None = UNSET


@dataclass(frozen=True, slots=True)
class SprintCompletion:
    """Итог завершения спринта: сам спринт и то, куда уехали незакрытые задачи.

    Ключи задач возвращаются вызывающему, а не только уезжают в событие: клиент,
    закрывший спринт, обязан увидеть список переехавшего сразу — второй раз его собрать
    будет уже неоткуда, состав спринта нигде не хранится отдельно от самих задач.
    """

    sprint: Sprint
    moved: tuple[str, ...] = ()
    target: Sprint | None = None


# --- Чтение ------------------------------------------------------------------------


async def get_board_by_id(session: AsyncSession, board_id: uuid.UUID) -> Board:
    """Доска по идентификатору или `board_not_found`.

    Прав не проверяет — точка входа интерфейса `read_board`; так же устроены проекты.
    """
    board = await BoardRepository(session).get_by_id(board_id)
    if board is None:
        raise BoardNotFoundError(details={"id": str(board_id)})
    return board


async def read_board(session: AsyncSession, board_id: uuid.UUID, *, initiator: Actor) -> Board:
    ensure_allowed(initiator, "board.read")
    return await get_board_by_id(session, board_id)


async def list_boards(
    session: AsyncSession,
    *,
    initiator: Actor,
    saved_filter: SavedFilter | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Board]:
    """Страница досок в порядке создания."""
    ensure_allowed(initiator, "board.list")
    return await BoardRepository(session).list_page(
        saved_filter_id=None if saved_filter is None else saved_filter.id,
        limit=limit,
        cursor=cursor,
    )


def get_column(board: Board, column_id: uuid.UUID) -> BoardColumn:
    """Колонка этой доски или `board_column_not_found`.

    Ищется среди уже загруженных колонок, а не запросом: колонки приезжают с доской
    стратегией `selectin`, их число ограничено доменом, и запрос за одной из них был бы
    вторым походом в базу за тем, что уже в памяти.

    Принадлежность проверяется здесь, а не в роутере: колонка адресуется в пути своей
    доской, и чужая колонка для клиента то же самое, что несуществующая.
    """
    for column in board.columns:
        if column.id == column_id:
            return column
    raise BoardColumnNotFoundError(details={"column": str(column_id), "board": str(board.id)})


async def get_sprint_by_id(session: AsyncSession, sprint_id: uuid.UUID) -> Sprint:
    """Спринт по идентификатору или `sprint_not_found`.

    Зовётся ещё и поиском при разрешении `sprint: <uuid>`, поэтому прав не проверяет:
    точка входа интерфейса — `read_sprint`.
    """
    sprint = await SprintRepository(session).get_by_id(sprint_id)
    if sprint is None:
        raise SprintNotFoundError(details={"id": str(sprint_id)})
    return sprint


async def read_sprint(session: AsyncSession, sprint_id: uuid.UUID, *, initiator: Actor) -> Sprint:
    ensure_allowed(initiator, "sprint.read")
    return await get_sprint_by_id(session, sprint_id)


async def list_sprints(
    session: AsyncSession,
    *,
    initiator: Actor,
    board: Board | None = None,
    state: SprintState | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Sprint]:
    """Страница спринтов в порядке создания."""
    ensure_allowed(initiator, "sprint.list")
    return await SprintRepository(session).list_page(
        board_id=None if board is None else board.id,
        state=state,
        limit=limit,
        cursor=cursor,
    )


# --- Сборка доски ------------------------------------------------------------------


async def list_column_issues(
    session: AsyncSession,
    board: Board,
    column: BoardColumn,
    *,
    initiator: Actor,
    sprint: str | None = None,
    query: str | None = None,
    fields: Sequence[str] = (),
    limit: int | None = None,
    cursor: str | None = None,
) -> search_service.SearchOutcome:
    """Задачи одной колонки, в порядке ранга доски.

    Собирается покомпонентно, а не «вся доска одним ответом», и это требование задачи:
    доска — самый нагруженный запрос API, одна колонка может тянуть тысячи задач.
    Оболочка ответа при этом кладёт под `data` ровно одну коллекцию, и курсор указывает
    позицию в одном упорядоченном запросе — две колонки в одном ответе означали бы либо
    два курсора рядом с `data`, либо потерю записей на первой же границе.

    `fields` работает так же, как в поиске: полная задача на сто карточек съедает
    контекст агента целиком, а доске обычно хватает ключа, названия и исполнителя.
    """
    ensure_allowed(initiator, "board.read", target=board)
    resolved = await _board_filter(
        session,
        board,
        initiator=initiator,
        query=query,
        extra=[_column_term(column), *_sprint_terms(sprint)],
        fields=fields,
    )
    page = await BoardIssueRepository(session).page(
        board.id,
        compile_filter(resolved),
        limit=limit,
        cursor=cursor,
    )
    return search_service.SearchOutcome(page=page, resolved=resolved)


async def list_backlog(
    session: AsyncSession,
    board: Board,
    *,
    initiator: Actor,
    query: str | None = None,
    fields: Sequence[str] = (),
    limit: int | None = None,
    cursor: str | None = None,
) -> search_service.SearchOutcome:
    """Бэклог доски: задачи её фильтра, не взятые ни в один спринт, в порядке ранга.

    По колонкам бэклог не раскладывается намеренно: колонки описывают ход работы, а в
    бэклоге работа ещё не началась. Разложить его по статусам можно обычным запросом
    (`?query=status: open`) — своего параметра для этого доска не заводит.
    """
    ensure_allowed(initiator, "board.read", target=board)
    resolved = await _board_filter(
        session,
        board,
        initiator=initiator,
        query=query,
        extra=_sprint_terms(SPRINT_SCOPE_BACKLOG),
        fields=fields,
    )
    page = await BoardIssueRepository(session).page(
        board.id,
        compile_filter(resolved),
        limit=limit,
        cursor=cursor,
    )
    return search_service.SearchOutcome(page=page, resolved=resolved)


async def list_sprint_issues(
    session: AsyncSession,
    sprint: Sprint,
    *,
    initiator: Actor,
    query: str | None = None,
    structured: Sequence[search_service.StructuredTerm] = (),
    saved_filter_id: uuid.UUID | None = None,
    sort: Sequence[str] = (),
    fields: Sequence[str] = (),
    limit: int | None = None,
    cursor: str | None = None,
) -> search_service.SearchOutcome:
    """Задачи спринта — это поиск с приклеенным условием `sprint: <id>`.

    В отличие от колонки, здесь работает обычная сортировка поиска, а не ранг доски:
    список спринта отвечает на вопрос «что в него взято», а не «в каком порядке это
    лежит на доске». Порядок карточек живёт на доске, и там он ранговый.

    Фильтр доски сюда **не** приклеивается, и это осознанно: задача, взятая в спринт и
    переставшая подходить под фильтр доски, всё равно в спринте — иначе она молча
    исчезла бы из состава и не попала в перенос при завершении.
    """
    ensure_allowed(initiator, "sprint.read", target=sprint)
    scope = search_service.StructuredTerm(
        name=SystemField.SPRINT.value,
        values=[str(sprint.id)],
    )
    return await search_service.search_issues(
        session,
        initiator=initiator,
        query=query,
        structured=[scope, *structured],
        saved_filter_id=saved_filter_id,
        sort=sort,
        fields=fields,
        limit=limit,
        cursor=cursor,
    )


# --- Доска -------------------------------------------------------------------------


async def create_board(
    session: AsyncSession,
    *,
    initiator: Actor,
    name: str,
    saved_filter: SavedFilter,
    description: str = "",
    columns: Sequence[ColumnDraft] = (),
) -> Board:
    """Заводит доску вместе с её колонками.

    Колонки принимаются здесь, а не только отдельным сценарием, потому что доска без
    колонок бесполезна: она ничего не показывает. Два запроса вместо одного означали бы
    промежуточное состояние, в котором доска уже есть, а смотреть на ней нечего.
    """
    ensure_allowed(initiator, "board.create")
    board = Board(
        name=validate_board_name(name),
        description=validate_board_description(description),
        saved_filter=saved_filter,
    )
    # Колонки собираются списком и присваиваются разом. Создавать их со ссылкой на
    # доску нельзя: связь двусторонняя, и такой объект попадает в `board.columns` сам —
    # второй `append` дал бы ту же колонку дважды.
    board.columns = [
        _column_from_draft(draft, position=position) for position, draft in enumerate(columns)
    ]
    _ensure_columns_valid(board)

    await BoardRepository(session).add(board)
    await events_service.record_board_change(
        session,
        board,
        initiator=initiator,
        action="board.create",
    )
    return board


async def update_board(
    session: AsyncSession,
    board: Board,
    *,
    initiator: Actor,
    changes: BoardChanges,
) -> tuple[Board, tuple[IssueChange, ...]]:
    """Единая точка изменения доски: применяются только переданные поля.

    Возвращает **фактические** изменения — поле, переданное со значением, равным
    текущему, записи не даёт и события не порождает. То же правило, что у задачи и
    проекта, и по той же причине.

    Смена сохранённого фильтра меняет состав доски целиком, но ранги не трогает:
    задача, вернувшаяся в область доски позже, встанет туда, где стояла. Это осознанно —
    иначе смена фильтра стирала бы вручную собранный порядок.
    """
    ensure_allowed(initiator, "board.update", target=board)

    recorded: list[IssueChange] = []
    if is_set(changes.name):
        name = validate_board_name(changes.name)
        if name != board.name:
            recorded.append(IssueChange(field="name", before=board.name, after=name))
            board.name = name
    if is_set(changes.description):
        description = validate_board_description(changes.description)
        if description != board.description:
            recorded.append(
                IssueChange(field="description", before=board.description, after=description)
            )
            board.description = description
    if is_set(changes.saved_filter) and changes.saved_filter.id != board.saved_filter_id:
        recorded.append(
            IssueChange(
                field="saved_filter",
                before=str(board.saved_filter_id),
                after=str(changes.saved_filter.id),
            )
        )
        board.saved_filter = changes.saved_filter

    if not recorded:
        return board, ()

    await BoardRepository(session).flush()
    await events_service.record_board_change(
        session,
        board,
        initiator=initiator,
        action="board.update",
        changes=tuple(recorded),
    )
    return board, tuple(recorded)


async def delete_board(session: AsyncSession, board: Board, *, initiator: Actor) -> None:
    """Удаляет доску вместе с колонками и рангами.

    Ранги уезжают каскадом, и это правильно: они — способ смотреть, а не данные о
    работе. Спринты каскадом уносить нельзя — они хранят принадлежность задач, поэтому
    доска со спринтами удаление отклоняет.
    """
    ensure_allowed(initiator, "board.delete", target=board)
    sprints = await BoardRepository(session).count_sprints(board.id)
    if sprints:
        raise BoardHasSprintsError(
            details={
                "board": str(board.id),
                "sprints": sprints,
                "hint": "delete the sprints first",
            },
        )
    # Событие собирается **до** удаления: после него снимок строить уже не из чего.
    await events_service.record_board_change(
        session,
        board,
        initiator=initiator,
        action="board.delete",
    )
    await BoardRepository(session).delete(board)


# --- Колонки -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnDraft:
    """Описание колонки на входе: название, статусы и лимит.

    Статусы приходят объектами, а не ссылками: разрешение ссылки — работа интерфейса, и
    сценарий, принимающий строки, зависел бы от того, кто его позвал.
    """

    name: str
    statuses: Sequence[Status]
    wip_limit: int | None = None


async def add_column(
    session: AsyncSession,
    board: Board,
    *,
    initiator: Actor,
    draft: ColumnDraft,
    after: BoardColumn | None = UNSET,
) -> BoardColumn:
    """Добавляет колонку. Без `after` — в конец, `after=None` — в начало.

    Место задаётся соседом, а не номером: номер разошёлся бы с состоянием доски,
    которую тем временем изменил кто-то ещё. То же правило, что у чеклиста.
    """
    ensure_allowed(initiator, "board.column_add", target=board)
    ensure_column_capacity(len(board.columns))

    column = _column_from_draft(draft, position=len(board.columns))
    ordered = list(board.columns)
    ordered.insert(_insert_index(ordered, after), column)
    board.columns = ordered
    _renumber(board)
    _ensure_columns_valid(board)

    await BoardRepository(session).flush()
    await events_service.record_board_change(
        session,
        board,
        initiator=initiator,
        action="board.column_add",
        changes=(IssueChange(field="columns", before=None, after=column.name),),
    )
    return column


async def update_column(
    session: AsyncSession,
    board: Board,
    column: BoardColumn,
    *,
    initiator: Actor,
    name: str = UNSET,
    statuses: Sequence[Status] = UNSET,
    wip_limit: int | None = UNSET,
    after: BoardColumn | None = UNSET,
) -> BoardColumn:
    """Меняет колонку: название, набор статусов, лимит и место среди соседей.

    Набор статусов заменяется целиком, а не дополняется: точечное добавление на списке,
    который тем временем поменял кто-то ещё, дало бы гонку — и разложило бы статус
    дважды либо потеряло бы его.
    """
    ensure_allowed(initiator, "board.column_update", target=board)

    changed = False
    if is_set(name):
        stored = validate_column_name(name)
        if stored != column.name:
            column.name = stored
            changed = True
    if is_set(wip_limit):
        limit = validate_wip_limit(wip_limit)
        if limit != column.wip_limit:
            column.wip_limit = limit
            changed = True
    if is_set(statuses):
        before = sorted(link.status.id for link in column.status_links)
        after_ids = sorted({status.id for status in statuses})
        if before != after_ids:
            column.status_links = _status_links(statuses)
            changed = True
    if is_set(after):
        ordered = [item for item in board.columns if item.id != column.id]
        index = _insert_index(ordered, after)
        if [item.id for item in board.columns].index(column.id) != index:
            ordered.insert(index, column)
            board.columns = ordered
            _renumber(board)
            changed = True

    if not changed:
        return column

    _ensure_columns_valid(board)
    await BoardRepository(session).flush()
    await events_service.record_board_change(
        session,
        board,
        initiator=initiator,
        action="board.column_update",
        changes=(IssueChange(field="columns", before=column.name, after=column.name),),
    )
    return column


async def remove_column(
    session: AsyncSession,
    board: Board,
    column: BoardColumn,
    *,
    initiator: Actor,
) -> None:
    """Убирает колонку с доски.

    Задачи при этом не трогаются: колонка — способ смотреть на статусы, а не место
    хранения. Статусы удалённой колонки просто перестают показываться на доске, пока их
    не разложат заново.
    """
    ensure_allowed(initiator, "board.column_remove", target=board)
    board.columns = [item for item in board.columns if item.id != column.id]
    _renumber(board)

    await BoardRepository(session).flush()
    await events_service.record_board_change(
        session,
        board,
        initiator=initiator,
        action="board.column_remove",
        changes=(IssueChange(field="columns", before=column.name, after=None),),
    )


# --- Перемещение карточки ----------------------------------------------------------


async def move_issue_to_column(
    session: AsyncSession,
    board: Board,
    issue: Issue,
    column: BoardColumn,
    *,
    initiator: Actor,
    status: Status | None = None,
    resolution: Any = UNSET,
    values: Any = UNSET,
    expected_version: int | None = None,
) -> issues_service.IssueMutation:
    """Переносит карточку в колонку **переходом воркфлоу**, а не записью статуса.

    Прямая запись статуса сделала бы доску дырой в процессе: через неё обходились бы
    все проверки задачи 07. Поэтому изменение собирается в `IssueChanges` и уходит в
    единую точку с действием `issue.transition` — со всеми её проверками, версией,
    записью в историю и событием `issue.status_changed`.

    Целевой статус выбирает вызывающий, если в колонке их несколько: угадывать «первый
    попавшийся» значило бы переводить задачу в статус, которого никто не просил.
    Колонка с одним статусом выбора не требует — там угадывать нечего.

    Резолюция и значения полей принимаются здесь же: переход в колонку «Готово»
    требует резолюции, и без неё перетаскивание карточки означало бы два запроса, из
    которых первый оставлял бы задачу в противоречивом состоянии.
    """
    ensure_allowed(initiator, "board.read", target=board)
    resolved = await _board_filter(session, board, initiator=initiator)
    if not await BoardIssueRepository(session).contains(compile_filter(resolved), issue.id):
        raise IssueNotOnBoardError(details={"board": str(board.id), "issue": issue.key})

    target = _column_target_status(column, status)
    if status is None and any(link.status_id == issue.status_id for link in column.status_links):
        # Задача уже в этой колонке, и конкретного статуса не просили — двигать нечего.
        # Молчаливый переход «на всякий случай» поднял бы версию задачи и записал бы в
        # историю смену статуса, которой не было.
        return issues_service.IssueMutation(issue=issue)

    changes = issues_service.IssueChanges(status=target)
    if is_set(resolution):
        changes = _with(changes, resolution=resolution)
    if is_set(values):
        changes = _with(changes, values=values)

    return await issues_service.apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=changes,
        action="issue.transition",
        expected_version=expected_version,
    )


async def rank_issue(
    session: AsyncSession,
    board: Board,
    issue: Issue,
    *,
    initiator: Actor,
    after: Issue | None = UNSET,
    before: Issue | None = UNSET,
) -> int:
    """Ставит карточку до или после указанной задачи и возвращает её новую позицию.

    Место задаётся соседом, а не индексом и не самой позицией. Индекс разошёлся бы с
    состоянием доски, которую тем временем изменил кто-то ещё, а позиция — внутреннее
    число разреженной шкалы, и отдав его наружу, мы позвали бы клиента считать её
    самому: две вставки в одно место дали бы одинаковые числа.

    Границы списка выражены `None`: `after=None` — в начало, `before=None` — в конец.
    Ровно одно из двух должно быть передано; оба сразу — противоречие, ни одного —
    отсутствие места.

    Обычный случай меняет одну строку. Если зазор между соседями исчерпан — а это
    бывает у задач, созданных одной транзакцией и потому получивших одинаковую
    виртуальную позицию, — доска перенумеровывается целиком, и попытка повторяется.
    Перенумерация видна в событии тем, что позиции соседей в нём отличаются от прежних:
    полагаться на конкретные числа клиенту нельзя, только на порядок.
    """
    ensure_allowed(initiator, "board.rank", target=board)
    _ensure_single_anchor(after, before)

    repository = BoardIssueRepository(session)
    resolved = await _board_filter(session, board, initiator=initiator)
    scope = compile_filter(resolved)

    if not await repository.contains(scope, issue.id):
        raise IssueNotOnBoardError(details={"board": str(board.id), "issue": issue.key})
    anchor = after if is_set(after) else before
    if anchor is not None:
        if anchor.id == issue.id:
            raise InvalidBoardMoveError(
                details={"issue": issue.key, "reason": "anchor_is_the_issue_itself"},
            )
        if not await repository.contains(scope, anchor.id):
            raise IssueNotOnBoardError(details={"board": str(board.id), "issue": anchor.key})

    lower, upper = await _neighbour_positions(repository, board, issue, scope, after, before)
    position = position_between(lower, upper)
    if position is None:
        # Зазор исчерпан. Это и есть плата за разреженную шкалу — редкая, но настоящая:
        # доска перенумеровывается целиком, порядок при этом сохраняется, и после
        # перенумерации место между соседями заведомо есть.
        await repository.rebalance(board.id, scope)
        lower, upper = await _neighbour_positions(repository, board, issue, scope, after, before)
        position = position_between(lower, upper)
    if position is None:
        # Недостижимо: после перенумерации соседи стоят с полным шагом. Явная ошибка
        # вместо тихого «поставим рядом» — два ранга на одной позиции дали бы
        # произвольный порядок между ними.
        raise InvalidBoardError(
            details={"field": "rank", "reason": "no_room_after_rebalance", "board": str(board.id)},
        )

    current = await repository.position_of(board.id, issue.id)
    await repository.set_position(board.id, issue.id, position)
    if current != position:
        await events_service.record_issue_ranked(
            session,
            board,
            issue,
            initiator=initiator,
            position=position,
        )
    return position


# --- Спринты -----------------------------------------------------------------------


async def create_sprint(
    session: AsyncSession,
    *,
    initiator: Actor,
    board: Board,
    name: str,
    goal: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
) -> Sprint:
    """Заводит спринт доски в состоянии «планируется».

    Сразу активным спринт не заводится: запуск — отдельное решение команды, и у доски
    активный спринт не более одного. Слить создание с запуском значило бы получать
    отказ «уже есть активный» на попытку **запланировать** следующий.
    """
    ensure_allowed(initiator, "sprint.create", target=board)
    validate_sprint_period(start_date, end_date)
    sprint = Sprint(
        board=board,
        name=validate_sprint_name(name),
        goal=validate_sprint_goal(goal),
        start_date=start_date,
        end_date=end_date,
        state=SprintState.PLANNED,
    )
    await SprintRepository(session).add(sprint)
    await events_service.record_sprint_change(
        session,
        sprint,
        initiator=initiator,
        action="sprint.create",
    )
    return sprint


async def update_sprint(
    session: AsyncSession,
    sprint: Sprint,
    *,
    initiator: Actor,
    changes: SprintChanges,
) -> tuple[Sprint, tuple[IssueChange, ...]]:
    """Единая точка изменения спринта: применяются только переданные поля.

    Править можно и активный, и завершённый спринт: это исправление записи, а не
    продолжение работы в нём. Так же ведёт себя архивный проект.
    """
    ensure_allowed(initiator, "sprint.update", target=sprint)

    recorded: list[IssueChange] = []
    if is_set(changes.name):
        name = validate_sprint_name(changes.name)
        if name != sprint.name:
            recorded.append(IssueChange(field="name", before=sprint.name, after=name))
            sprint.name = name
    if is_set(changes.goal):
        goal = validate_sprint_goal(changes.goal)
        if goal != sprint.goal:
            recorded.append(IssueChange(field="goal", before=sprint.goal, after=goal))
            sprint.goal = goal

    # Период проверяется целиком, а не по одной границе: клиент вправе прислать только
    # `end_date`, и сравнивать её надо с той датой начала, которая останется после
    # правки, а не с той, что была до неё.
    start = changes.start_date if is_set(changes.start_date) else sprint.start_date
    end = changes.end_date if is_set(changes.end_date) else sprint.end_date
    validate_sprint_period(start, end)
    if is_set(changes.start_date) and changes.start_date != sprint.start_date:
        recorded.append(
            IssueChange(
                field="start_date",
                before=_day(sprint.start_date),
                after=_day(changes.start_date),
            )
        )
        sprint.start_date = changes.start_date
    if is_set(changes.end_date) and changes.end_date != sprint.end_date:
        recorded.append(
            IssueChange(
                field="end_date",
                before=_day(sprint.end_date),
                after=_day(changes.end_date),
            )
        )
        sprint.end_date = changes.end_date

    if not recorded:
        return sprint, ()

    await SprintRepository(session).flush()
    await events_service.record_sprint_change(
        session,
        sprint,
        initiator=initiator,
        action="sprint.update",
        changes=tuple(recorded),
    )
    return sprint, tuple(recorded)


async def start_sprint(session: AsyncSession, sprint: Sprint, *, initiator: Actor) -> Sprint:
    """Запускает запланированный спринт.

    Не идемпотентно, в отличие от архивации проекта: повторный запуск означает, что
    клиент видит не то состояние, а тихий успех скрыл бы от него уже идущий спринт —
    возможно, чужой. Запустить завершённый нельзя вовсе: возврата из `completed` нет,
    незакрытые задачи уже уехали, и восстанавливать их состав неоткуда.
    """
    ensure_allowed(initiator, "sprint.start", target=sprint)
    _ensure_state(sprint, SprintState.PLANNED, reason="cannot_start")

    active = await SprintRepository(session).active_of_board(sprint.board_id)
    if active is not None:
        raise BoardSprintActiveError(
            details={
                "board": str(sprint.board_id),
                "active_sprint": str(active.id),
                "reason": "complete_it_first",
            },
        )

    before = sprint.state.value
    sprint.state = SprintState.ACTIVE
    sprint.started_at = datetime.now(UTC)
    await SprintRepository(session).flush()
    await events_service.record_sprint_change(
        session,
        sprint,
        initiator=initiator,
        action="sprint.start",
        changes=(IssueChange(field="state", before=before, after=sprint.state.value),),
    )
    return sprint


async def complete_sprint(
    session: AsyncSession,
    sprint: Sprint,
    *,
    initiator: Actor,
    unfinished: UnfinishedPolicy,
    target: Sprint | None = None,
) -> SprintCompletion:
    """Завершает активный спринт, уводя незакрытые задачи туда, куда сказал вызывающий.

    Выбор принимает вызывающий, а не система: «перенести в следующий спринт» и «вернуть
    в бэклог» — разные способы работать, и молчаливое умолчание однажды растащило бы
    чужой спринт. Значения по умолчанию у `unfinished` поэтому нет.

    Закрытые задачи остаются в спринте: он и есть запись о том, что команда успела.

    Каждая незакрытая задача проходит через единую точку изменения — с записью в
    историю, ростом версии и событием. Цена названа прямо: спринт на двести незакрытых
    задач даст двести записей истории и двести событий. Массовый `UPDATE` был бы
    дешевле и оставил бы дыру в истории ровно там, где потом спросят «куда делась моя
    задача».
    """
    ensure_allowed(initiator, "sprint.complete", target=sprint)
    _ensure_state(sprint, SprintState.ACTIVE, reason="cannot_complete")
    destination = _completion_target(sprint, unfinished, target)

    moved: list[str] = []
    for issue in await SprintRepository(session).unfinished_issues(sprint.id):
        mutation = await issues_service.apply_issue_changes(
            session,
            issue,
            initiator=initiator,
            changes=issues_service.IssueChanges(sprint=destination),
            action="issue.set_sprint",
        )
        if mutation.changed:
            moved.append(issue.key)

    before = sprint.state.value
    sprint.state = SprintState.COMPLETED
    sprint.completed_at = datetime.now(UTC)
    await SprintRepository(session).flush()
    await events_service.record_sprint_change(
        session,
        sprint,
        initiator=initiator,
        action="sprint.complete",
        changes=(
            IssueChange(field="state", before=before, after=sprint.state.value),
            IssueChange(
                field="unfinished",
                before=None,
                after=None if destination is None else str(destination.id),
            ),
        ),
        issues=moved,
    )
    return SprintCompletion(sprint=sprint, moved=tuple(moved), target=destination)


async def delete_sprint(session: AsyncSession, sprint: Sprint, *, initiator: Actor) -> None:
    """Удаляет пустой спринт.

    Существует ради опечатки при планировании, а не ради уборки истории: спринт с
    задачами удаление отклоняет, потому что унесло бы их принадлежность молча, а
    активный — потому что это отмена идущей работы, а не исправление записи.
    """
    ensure_allowed(initiator, "sprint.delete", target=sprint)
    if sprint.state is SprintState.ACTIVE:
        raise SprintStateError(
            details={
                "sprint": str(sprint.id),
                "state": sprint.state.value,
                "expected": [SprintState.PLANNED.value, SprintState.COMPLETED.value],
                "reason": "cannot_delete",
            },
        )
    issues = await SprintRepository(session).count_issues(sprint.id)
    if issues:
        raise SprintNotEmptyError(
            details={
                "sprint": str(sprint.id),
                "issues": issues,
                "hint": "take the issues out of the sprint first",
            },
        )
    # Событие собирается **до** удаления: после него снимок строить уже не из чего.
    await events_service.record_sprint_change(
        session,
        sprint,
        initiator=initiator,
        action="sprint.delete",
    )
    await SprintRepository(session).delete(sprint)


async def add_sprint_issues(
    session: AsyncSession,
    sprint: Sprint,
    *,
    initiator: Actor,
    issues: Sequence[Issue],
) -> list[issues_service.IssueMutation]:
    """Берёт задачи в спринт. Задача, уже взятая в него, изменения не даёт.

    Каждая задача проходит через единую точку изменения, поэтому у каждой растёт версия
    и появляется запись в истории. Клиент, державший версию для оптимистичной
    блокировки, обязан задачу перечитать.

    Задача из **другого** спринта переезжает молча — как и при смене проекта: отказ
    означал бы обязательный двухшаговый ритуал «сначала вынь, потом положи», а переезд
    виден в истории задачи как обычное изменение поля.
    """
    return [
        await issues_service.apply_issue_changes(
            session,
            issue,
            initiator=initiator,
            changes=issues_service.IssueChanges(sprint=sprint),
            action="issue.set_sprint",
        )
        for issue in issues
    ]


async def remove_sprint_issue(
    session: AsyncSession,
    sprint: Sprint,
    *,
    initiator: Actor,
    issue: Issue,
) -> issues_service.IssueMutation:
    """Возвращает задачу из спринта в бэклог.

    Задача, взятая в **другой** спринт, не трогается: убрать её отсюда нельзя, потому
    что здесь её нет. Отказ честнее молчания — иначе клиент, перепутавший спринт,
    получил бы `204` и уверенность, что задача вынута.
    """
    if issue.sprint_id != sprint.id:
        raise SprintNotFoundError(
            details={
                "id": str(sprint.id),
                "issue": issue.key,
                "reason": "issue_not_in_sprint",
            },
        )
    return await issues_service.apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=issues_service.IssueChanges(sprint=None),
        action="issue.set_sprint",
    )


# --- Внутреннее --------------------------------------------------------------------


async def _board_filter(
    session: AsyncSession,
    board: Board,
    *,
    initiator: Actor,
    query: str | None = None,
    extra: Sequence[search_service.StructuredTerm] = (),
    fields: Sequence[str] = (),
) -> ResolvedFilter:
    """Фильтр доски: её сохранённый фильтр плюс приклеенные условия.

    Разрешается тем же кодом, что и любой поиск, — иначе доска понимала бы `me()` и
    относительные даты иначе, чем `GET /search/issues`, и расхождение было бы
    молчаливым. Условия доски идут **первыми** и склеиваются по `and`, поэтому запрос
    клиента может сузить выдачу, но не может вывести её за пределы доски.
    """
    return await search_service.resolve_issue_filter(
        session,
        initiator=initiator,
        query=query,
        structured=list(extra),
        saved_filter_id=board.saved_filter_id,
        fields=fields,
    )


def _column_term(column: BoardColumn) -> search_service.StructuredTerm:
    """Условие «статус задачи попадает в эту колонку».

    Ссылками справочника, а не идентификаторами: условие идёт тем же путём, что и
    `status: open, TRK.in_review` из строки запроса, и второй способ выразить то же
    самое разошёлся бы с первым.
    """
    return search_service.StructuredTerm(
        name=SystemField.STATUS.value,
        values=[format_entry_ref(link.status) for link in column.status_links],
    )


def _sprint_terms(scope: str | None) -> list[search_service.StructuredTerm]:
    """Условие по спринту из параметра области.

    Словарь значений маленький и закрытый: `backlog` — задачи вне спринтов, `current` —
    активный спринт доски, идентификатор — конкретный спринт, ничего — все задачи
    фильтра. `backlog` превращается в `sprint: empty()`, потому что «значения нет» в
    проекте выражается ровно так и вторым способом не выражается.
    """
    if scope is None:
        return []
    if scope.strip().lower() == SPRINT_SCOPE_BACKLOG:
        return [search_service.StructuredTerm(name=SystemField.SPRINT.value, values=[None])]
    return [search_service.StructuredTerm(name=SystemField.SPRINT.value, values=[scope])]


async def _neighbour_positions(
    repository: BoardIssueRepository,
    board: Board,
    issue: Issue,
    scope: ColumnElement[bool] | None,
    after: Issue | None,
    before: Issue | None,
) -> tuple[int | None, int | None]:
    """Позиции соседей будущего места карточки: «над» и «под».

    Отдельной функцией, потому что вызывается дважды: второй раз — после перенумерации
    доски, когда позиции соседей уже другие. Пересчитать их обязательно; повторное
    использование старых чисел поставило бы карточку по прежней шкале, то есть в конец
    заново пронумерованной доски.
    """
    if is_set(after):
        if after is None:
            first = await repository.adjacent_position(
                board.id, scope, anchor=None, forward=True, exclude_issue_id=issue.id
            )
            return None, first
        lower = await repository.position_of(board.id, after.id)
        assert lower is not None
        upper = await repository.adjacent_position(
            board.id,
            scope,
            anchor=(lower, after.id),
            forward=True,
            exclude_issue_id=issue.id,
        )
        return lower, upper

    if before is None:
        last = await repository.adjacent_position(
            board.id, scope, anchor=None, forward=False, exclude_issue_id=issue.id
        )
        return last, None
    upper = await repository.position_of(board.id, before.id)
    assert upper is not None
    lower = await repository.adjacent_position(
        board.id,
        scope,
        anchor=(upper, before.id),
        forward=False,
        exclude_issue_id=issue.id,
    )
    return lower, upper


def _ensure_single_anchor(after: Issue | None, before: Issue | None) -> None:
    """Место задаёт ровно один сосед: и оба сразу, и ни одного — не место."""
    if is_set(after) and is_set(before):
        raise InvalidBoardMoveError(details={"reason": "anchor_ambiguous"})
    if not is_set(after) and not is_set(before):
        raise InvalidBoardMoveError(details={"reason": "anchor_required"})


def _column_target_status(column: BoardColumn, status: Status | None) -> Status:
    """Статус, в который переводит перенос в колонку."""
    statuses = [link.status for link in column.status_links]
    if status is None:
        if len(statuses) != 1:
            raise InvalidBoardMoveError(
                details={
                    "column": str(column.id),
                    "reason": "status_required",
                    "statuses": sorted(format_entry_ref(item) for item in statuses),
                },
            )
        return statuses[0]
    if all(item.id != status.id for item in statuses):
        raise InvalidBoardMoveError(
            details={
                "column": str(column.id),
                "reason": "status_not_in_column",
                "status": format_entry_ref(status),
                "statuses": sorted(format_entry_ref(item) for item in statuses),
            },
        )
    return status


def _column_from_draft(draft: ColumnDraft, *, position: int) -> BoardColumn:
    """Колонка без доски: её проставит присваивание `board.columns`.

    Передать доску сюда нельзя: связь двусторонняя, и колонка со ссылкой на доску
    попадает в её список сама — вызывающий, добавляющий её ещё раз, получил бы дубль.
    """
    column = BoardColumn(
        name=validate_column_name(draft.name),
        position=position,
        wip_limit=validate_wip_limit(draft.wip_limit),
    )
    column.status_links = _status_links(draft.statuses)
    return column


def _status_links(statuses: Sequence[Status]) -> list[BoardColumnStatus]:
    """Строки связи «статус в колонке», без повторов и с сохранением порядка.

    Повтор — не ошибка запроса, а небрежность клиента, поэтому отбрасывается молча:
    ровно так же поступает список участников проекта.
    """
    seen: set[uuid.UUID] = set()
    links: list[BoardColumnStatus] = []
    for status in statuses:
        if status.id in seen:
            continue
        seen.add(status.id)
        # `board_id` и `column_id` проставит связь: они обе входят в составной внешний
        # ключ на колонку, и синхронизирует их SQLAlchemy. Присваивать их руками значило
        # бы завести второй источник для одного и того же значения.
        links.append(BoardColumnStatus(status=status))
    ensure_column_statuses(len(links))
    return links


def _ensure_columns_valid(board: Board) -> None:
    """Один статус — не более чем в одной колонке доски, и колонок не больше потолка.

    Уникальность держит и база, но без этой проверки клиент получал бы голый
    `409 conflict` с именем ограничения вместо внятного «статус уже в другой колонке».
    """
    ensure_column_count(len(board.columns))
    placed: dict[uuid.UUID, BoardColumn] = {}
    for column in board.columns:
        ensure_column_statuses(len(column.status_links))
        for link in column.status_links:
            # Идентификатор берётся у самой записи справочника, а не у строки связи:
            # у только что созданной связи `status_id` пуст до flush, и проверка по нему
            # сочла бы все новые колонки претендующими на один и тот же статус `None`.
            owner = placed.get(link.status.id)
            if owner is not None and owner is not column:
                raise BoardStatusTakenError(
                    details={
                        "board": str(board.id),
                        "status": format_entry_ref(link.status),
                        "column": owner.name,
                    },
                )
            placed[link.status.id] = column

    names = [column.name for column in board.columns]
    if len(set(names)) != len(names):
        raise InvalidBoardError(details={"field": "columns", "reason": "duplicate_names"})


def _insert_index(ordered: Sequence[BoardColumn], after: BoardColumn | None) -> int:
    """Место вставки: сразу за указанной колонкой, `None` — в начало, `UNSET` — в конец."""
    if not is_set(after):
        return len(ordered)
    if after is None:
        return 0
    for index, column in enumerate(ordered):
        if column.id == after.id:
            return index + 1
    return len(ordered)


def _renumber(board: Board) -> None:
    """Сплошная нумерация колонок: их немного, и разреженная шкала здесь ни к чему.

    Колонок у доски не больше двух десятков, и перестановка одной из них переписывает
    весь список — двадцать UPDATE на редкую операцию настройки. У карточек это было бы
    недопустимо (их тысячи и двигают их постоянно), поэтому там шкала разреженная.
    """
    for position, column in enumerate(board.columns):
        column.position = position


def _completion_target(
    sprint: Sprint,
    unfinished: UnfinishedPolicy,
    target: Sprint | None,
) -> Sprint | None:
    """Куда уводить незакрытые задачи, с проверкой самого целевого спринта."""
    if unfinished is UnfinishedPolicy.BACKLOG:
        return None
    if target is None:
        raise InvalidBoardError(
            details={"field": "sprint", "reason": "required", "policy": unfinished.value},
        )
    if target.id == sprint.id:
        raise InvalidBoardError(
            details={"field": "sprint", "reason": "same_sprint", "sprint": str(sprint.id)},
        )
    if target.board_id != sprint.board_id:
        raise InvalidBoardError(
            details={
                "field": "sprint",
                "reason": "other_board",
                "board": str(sprint.board_id),
                "sprint": str(target.id),
            },
        )
    if target.state is SprintState.COMPLETED:
        raise SprintStateError(
            details={
                "sprint": str(target.id),
                "state": target.state.value,
                "expected": [SprintState.PLANNED.value, SprintState.ACTIVE.value],
                "reason": "cannot_accept_issues",
            },
        )
    return target


def _ensure_state(sprint: Sprint, expected: SprintState, *, reason: str) -> None:
    if sprint.state is not expected:
        raise SprintStateError(
            details={
                "sprint": str(sprint.id),
                "state": sprint.state.value,
                "expected": [expected.value],
                "reason": reason,
            },
        )


def _with(changes: issues_service.IssueChanges, **fields: Any) -> issues_service.IssueChanges:
    """Дописывает поля в набор изменений задачи, не собирая его заново."""
    return replace(changes, **fields)


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()
