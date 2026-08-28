"""Сценарии досок, колонок и ранжирования карточек.

Один модуль на три сущности — как проекты и портфели в `app/services/projects.py`:
доска не существует без колонок, а ранг не существует без обоих. Разложить их по файлам
значило бы получить кольцо импортов ради красоты оглавления.

## Доска ничего не отбирает сама

Список задач колонки — это **поиск с приклеенным условием**, ровно как список задач
проекта (`app/services/projects.py`, `list_project_issues`). Доска добавляет к
сохранённому фильтру условие по статусам колонки, склеивает всё по `and` и отдаёт в
`app/services/search.py`. Поэтому клиент может сузить выдачу своим запросом, но не
может выйти за пределы доски, а язык запросов и выбор возвращаемых полей работают здесь
ровно так же, как в общем поиске.

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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.board import Board, BoardColumn, BoardColumnStatus
from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.models.saved_filter import SavedFilter
from app.db.pagination import Page
from app.db.repositories import BoardIssueRepository, BoardRepository
from app.db.repositories.search import compile_filter
from app.domain.boards import (
    ensure_column_capacity,
    ensure_column_count,
    ensure_column_statuses,
    validate_board_description,
    validate_board_name,
    validate_column_name,
    validate_wip_limit,
)
from app.domain.errors import (
    BoardColumnNotFoundError,
    BoardNotFoundError,
    BoardStatusTakenError,
    InvalidBoardError,
    InvalidBoardMoveError,
    IssueNotOnBoardError,
)
from app.domain.issues import IssueChange
from app.domain.ranking import position_between
from app.domain.search import ResolvedFilter, SystemField
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import search as search_service
from app.services.catalogs import format_entry_ref
from app.services.permissions import ensure_allowed


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


# --- Сборка доски ------------------------------------------------------------------


async def list_column_issues(
    session: AsyncSession,
    board: Board,
    column: BoardColumn,
    *,
    initiator: Actor,
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
        extra=[_column_term(column)],
        fields=fields,
    )
    page = await BoardIssueRepository(session).page(
        board.id,
        compile_filter(resolved),
        limit=limit,
        cursor=cursor,
    )
    return search_service.SearchOutcome(page=page, resolved=resolved)


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

    Задачи не трогаются вовсе: доска отбирает их фильтром и владеть ими не может.
    Каскадом уезжают только колонки и ранги, и это правильно — они способ смотреть, а не
    данные о работе.
    """
    ensure_allowed(initiator, "board.delete", target=board)
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


def _with(changes: issues_service.IssueChanges, **fields: Any) -> issues_service.IssueChanges:
    """Дописывает поля в набор изменений задачи, не собирая его заново."""
    return replace(changes, **fields)
