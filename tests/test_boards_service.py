"""Сценарии досок: состав колонок, сборка, ранжирование и перемещение карточек.

Проверяется то, что нельзя увидеть по схеме: доска отбирает задачи своим фильтром и не
даёт выйти за него, порядок держится на разреженной шкале и переживает исчерпание
зазора, а перемещение карточки идёт переходом воркфлоу — то есть может отказать.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.board import Board, IssueRank
from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.models.saved_filter import SavedFilter
from app.db.repositories.boards import BoardIssueRepository
from app.domain.boards import virtual_position
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.errors import (
    BoardHasSprintsError,
    BoardStatusTakenError,
    InvalidBoardError,
    InvalidBoardMoveError,
    IssueNotOnBoardError,
    StatusInUseError,
    TransitionNotAllowedError,
)
from app.domain.issues import IssuePriority
from app.domain.ranking import POSITION_STEP
from app.services import boards as service
from app.services import catalogs as catalogs_service
from app.services.boards import BoardChanges, ColumnDraft

MakeBoard = Callable[..., Awaitable[Board]]
MakeIssue = Callable[..., Awaitable[Issue]]
MakeFilter = Callable[..., Awaitable[SavedFilter]]
ResolveStatus = Callable[[str], Awaitable[Status]]


async def _column_keys(
    session: AsyncSession,
    board: Board,
    column_index: int,
    *,
    owner: Actor,
    **kwargs: Any,
) -> list[str]:
    outcome = await service.list_column_issues(
        session,
        board,
        board.columns[column_index],
        initiator=owner,
        **kwargs,
    )
    return [issue.key for issue in outcome.page.items]


async def _backlog_keys(session: AsyncSession, board: Board, *, owner: Actor) -> list[str]:
    outcome = await service.list_backlog(session, board, initiator=owner)
    return [issue.key for issue in outcome.page.items]


async def _pin(session: AsyncSession, board: Board, owner: Actor, issues: list[Issue]) -> None:
    """Задаёт доске явный порядок карточек, чтобы дальше проверять именно перемещение.

    Без этого шага порядок неранжированных задач в тесте произволен: весь тест живёт в
    одной транзакции, `now()` у всех задач одинаков, и порядок задаёт тайбрейкер по
    случайному `id` (`docs/notes/testing.md`). Проверять на таком фоне «встала после
    соседа» было бы гаданием.
    """
    previous: Issue | None = None
    for issue in issues:
        if previous is None:
            await service.rank_issue(session, board, issue, initiator=owner, after=None)
        else:
            await service.rank_issue(session, board, issue, initiator=owner, after=previous)
        previous = issue


# --- Состав доски ------------------------------------------------------------------


async def test_a_board_is_created_with_its_columns(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[
            ColumnDraft(name="Бэклог", statuses=[await resolve_status("open")]),
            ColumnDraft(
                name="Готово",
                statuses=[await resolve_status("closed")],
                wip_limit=3,
            ),
        ],
    )

    assert [column.name for column in board.columns] == ["Бэклог", "Готово"]
    assert [column.position for column in board.columns] == [0, 1]
    assert board.columns[1].wip_limit == 3


async def test_a_status_cannot_be_placed_into_two_columns(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    resolve_status: ResolveStatus,
) -> None:
    """Иначе карточка показалась бы дважды, а «в какой она колонке» потеряло бы ответ."""
    open_status = await resolve_status("open")

    with pytest.raises(BoardStatusTakenError):
        await make_board(
            columns=[
                ColumnDraft(name="Слева", statuses=[open_status]),
                ColumnDraft(name="Справа", statuses=[open_status]),
            ],
        )


async def test_two_columns_cannot_share_a_name(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    resolve_status: ResolveStatus,
) -> None:
    with pytest.raises(InvalidBoardError) as error:
        await make_board(
            columns=[
                ColumnDraft(name="Работа", statuses=[await resolve_status("open")]),
                ColumnDraft(name="Работа", statuses=[await resolve_status("closed")]),
            ],
        )

    assert error.value.details["reason"] == "duplicate_names"


async def test_a_column_is_moved_by_its_neighbour(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    resolve_status: ResolveStatus,
) -> None:
    """Место задаётся соседом: номер разошёлся бы с доской, изменённой кем-то ещё."""
    board = await make_board(
        columns=[
            ColumnDraft(name="Открыт", statuses=[await resolve_status("open")]),
            ColumnDraft(name="Закрыт", statuses=[await resolve_status("closed")]),
        ],
    )

    await service.update_column(
        db_session,
        board,
        board.columns[1],
        initiator=owner,
        after=None,
    )

    assert [column.name for column in board.columns] == ["Закрыт", "Открыт"]
    assert [column.position for column in board.columns] == [0, 1]


async def test_a_status_used_by_a_board_column_cannot_be_deleted(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    resolve_status: ResolveStatus,
) -> None:
    """Каскад унёс бы строку молча и мог оставить колонку без единого статуса.

    Такая колонка показывает все задачи доски, поэтому осмысленный случай отклоняет
    сценарий, а каскад остаётся страховкой для удаления очереди.
    """
    local = await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="on_hold",
        name="Отложен",
        queue=queue,
        category=StatusCategory.NEW,
    )
    await make_board(columns=[ColumnDraft(name="Пауза", statuses=[local])])

    with pytest.raises(StatusInUseError) as error:
        await catalogs_service.delete_entry(db_session, local, CatalogKind.STATUS, initiator=owner)

    assert error.value.details["reason"] == "board_columns_exist"


async def test_a_board_with_sprints_is_not_deleted(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_sprint: Callable[..., Awaitable[Any]],
    resolve_status: ResolveStatus,
) -> None:
    """Спринт хранит принадлежность задач, и каскад унёс бы её молча."""
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    await make_sprint(board)

    with pytest.raises(BoardHasSprintsError):
        await service.delete_board(db_session, board, initiator=owner)


# --- Сборка доски ------------------------------------------------------------------


async def test_a_column_shows_only_the_issues_of_its_statuses(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[
            ColumnDraft(name="Открыт", statuses=[await resolve_status("open")]),
            ColumnDraft(name="Закрыт", statuses=[await resolve_status("closed")]),
        ],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")

    # Сравнение множествами: порядок неранжированных задач одной транзакции задаёт
    # тайбрейкер по случайному `id`, и проверять его здесь нечем — колонка про состав.
    assert set(await _column_keys(db_session, board, 0, owner=owner)) == {first.key, second.key}
    assert await _column_keys(db_session, board, 1, owner=owner) == []


async def test_the_column_list_cannot_be_widened_beyond_the_board(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    make_saved_filter: MakeFilter,
    resolve_status: ResolveStatus,
) -> None:
    """Условия доски приклеиваются первыми и склеиваются по `and`.

    Поэтому запрос клиента может только сузить выдачу. Попытка расширить её другим
    приоритетом не выводит за пределы фильтра доски и колонки.
    """
    narrow = await make_saved_filter(name="Только блокеры", query="priority: blocker")
    board = await make_board(
        saved_filter=narrow,
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    blocker = await make_issue(summary="Горит", priority=IssuePriority.BLOCKER)
    await make_issue(summary="Обычная")

    assert await _column_keys(db_session, board, 0, owner=owner) == [blocker.key]
    assert await _column_keys(db_session, board, 0, owner=owner, query="priority: normal") == []


async def test_the_backlog_holds_the_issues_outside_any_sprint(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    make_sprint: Callable[..., Awaitable[Any]],
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    sprint = await make_sprint(board)
    taken = await make_issue(summary="Взята в спринт")
    left = await make_issue(summary="Осталась в бэклоге")
    await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[taken])

    assert await _backlog_keys(db_session, board, owner=owner) == [left.key]


async def test_the_column_can_be_narrowed_to_the_current_sprint(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    make_sprint: Callable[..., Awaitable[Any]],
    resolve_status: ResolveStatus,
) -> None:
    """`sprint: current` — самый частый вопрос доски, и сервер знает ответ сам."""
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    sprint = await make_sprint(board)
    taken = await make_issue(summary="Взята в спринт")
    await make_issue(summary="Осталась в бэклоге")
    await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[taken])
    await service.start_sprint(db_session, sprint, initiator=owner)

    assert await _column_keys(db_session, board, 0, owner=owner, sprint="current") == [taken.key]
    assert await _column_keys(db_session, board, 0, owner=owner, sprint="backlog") != [taken.key]


# --- Ранжирование ------------------------------------------------------------------


async def test_an_unranked_issue_stands_where_it_was_created(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Строки ранга нет, а порядок есть: позиция вычисляется из времени создания.

    Время создания разводится руками: весь тест живёт в одной транзакции, и `now()`
    ставит всем задачам одну отметку. Без этого шага проверялся бы не порядок по
    времени, а тайбрейкер по случайному `id`.
    """
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    later = await make_issue(summary="Поздняя")
    earlier = await make_issue(summary="Ранняя")
    await db_session.execute(
        update(Issue)
        .where(Issue.id == earlier.id)
        .values(created_at=earlier.created_at - timedelta(seconds=1))
    )

    assert await _backlog_keys(db_session, board, owner=owner) == [earlier.key, later.key]
    assert (await db_session.scalars(select(IssueRank))).all() == []


async def test_a_card_moved_to_the_top_stays_there(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    third = await make_issue(summary="Третья")
    await _pin(db_session, board, owner, [first, second, third])

    await service.rank_issue(db_session, board, third, initiator=owner, after=None)

    assert await _backlog_keys(db_session, board, owner=owner) == [
        third.key,
        first.key,
        second.key,
    ]


async def test_a_card_moved_to_the_bottom_stays_there(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Конец списка достижим — ради этого шкала и совмещена с виртуальной."""
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")

    await service.rank_issue(db_session, board, first, initiator=owner, before=None)

    assert await _backlog_keys(db_session, board, owner=owner) == [second.key, first.key]


async def test_a_card_stands_right_after_its_anchor(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    third = await make_issue(summary="Третья")
    await _pin(db_session, board, owner, [first, second, third])

    await service.rank_issue(db_session, board, third, initiator=owner, after=first)

    assert await _backlog_keys(db_session, board, owner=owner) == [
        first.key,
        third.key,
        second.key,
    ]


async def test_a_card_stands_right_before_its_anchor(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    third = await make_issue(summary="Третья")
    await _pin(db_session, board, owner, [first, second, third])

    await service.rank_issue(db_session, board, third, initiator=owner, before=second)

    assert await _backlog_keys(db_session, board, owner=owner) == [
        first.key,
        third.key,
        second.key,
    ]


async def test_ranking_touches_one_row_and_leaves_the_issue_alone(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Перестановка — не изменение задачи: версия не растёт, статус не трогается.

    Это и есть разница между «переставить карточку» и «перетащить её в другую колонку».
    """
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    version_before = second.version

    await service.rank_issue(db_session, board, second, initiator=owner, after=None)

    assert second.version == version_before
    assert second.status_id == first.status_id
    assert len((await db_session.scalars(select(IssueRank))).all()) == 1


async def test_the_gap_running_out_renumbers_the_board(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Задачи одной транзакции стоят на одной виртуальной позиции — зазора между ними нет.

    В тесте это состояние получается само: весь тест живёт в одной транзакции, и
    `now()` у всех задач одинаков. Перенумерация обязана раздать явные ранги и сохранить
    порядок, а не отказать и не поставить две карточки на одно место.
    """
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    third = await make_issue(summary="Третья")
    assert virtual_position(first.created_at) == virtual_position(second.created_at)

    # Якорь берётся из текущей выдачи, а не назначается: у трёх задач одна виртуальная
    # позиция, и кто из них первый, решает тайбрейкер по случайному `id`.
    before = await _backlog_keys(db_session, board, owner=owner)
    anchor_key = next(key for key in before if key != third.key)
    anchor = first if first.key == anchor_key else second

    await service.rank_issue(db_session, board, third, initiator=owner, after=anchor)
    after = await _backlog_keys(db_session, board, owner=owner)

    # Перенумерация раздала явные ранги всем задачам доски, и они различны: именно это
    # она и обязана обеспечить. Конкретные числа проверять нельзя — переставленная
    # карточка получает позицию между соседями уже после перенумерации.
    ranks = (await db_session.scalars(select(IssueRank.position))).all()
    assert len(ranks) == 3
    assert len(set(ranks)) == 3
    assert min(ranks) >= POSITION_STEP
    assert after.index(third.key) == after.index(anchor_key) + 1


async def test_an_issue_outside_the_board_cannot_be_ranked(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    make_saved_filter: MakeFilter,
    resolve_status: ResolveStatus,
) -> None:
    """Иначе в базе остался бы ранг, которого никто никогда не увидит."""
    narrow = await make_saved_filter(name="Только блокеры", query="priority: blocker")
    board = await make_board(
        saved_filter=narrow,
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    outsider = await make_issue(summary="Обычная")

    with pytest.raises(IssueNotOnBoardError):
        await service.rank_issue(db_session, board, outsider, initiator=owner, after=None)


async def test_a_move_needs_exactly_one_anchor(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    issue = await make_issue(summary="Первая")
    other = await make_issue(summary="Вторая")

    with pytest.raises(InvalidBoardMoveError) as missing:
        await service.rank_issue(db_session, board, issue, initiator=owner)
    assert missing.value.details["reason"] == "anchor_required"

    with pytest.raises(InvalidBoardMoveError) as both:
        await service.rank_issue(
            db_session, board, issue, initiator=owner, after=other, before=other
        )
    assert both.value.details["reason"] == "anchor_ambiguous"

    with pytest.raises(InvalidBoardMoveError) as itself:
        await service.rank_issue(db_session, board, issue, initiator=owner, after=issue)
    assert itself.value.details["reason"] == "anchor_is_the_issue_itself"


async def test_the_virtual_position_matches_the_one_computed_in_sql(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Формула виртуальной позиции продублирована в Python и в SQL — она обязана совпадать.

    Разойдись они, сценарий считал бы новую позицию из чисел одной шкалы, а выдача
    сортировалась бы по другой: карточка вставала бы не туда, куда её положили, и
    заметить это можно было бы только глазами.
    """
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    issue = await make_issue(summary="Первая")

    in_sql = await BoardIssueRepository(db_session).position_of(board.id, issue.id)

    assert in_sql == virtual_position(issue.created_at)


# --- Перемещение между колонками ---------------------------------------------------


async def test_moving_a_card_between_columns_is_a_workflow_transition(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Статус меняется через единую точку: растёт версия, пишется история, летит событие."""
    board = await make_board(
        columns=[
            ColumnDraft(name="Открыт", statuses=[await resolve_status("open")]),
            ColumnDraft(name="В работе", statuses=[await resolve_status("in_progress")]),  # noqa: RUF001
        ],
    )
    issue = await make_issue(summary="Первая")
    version_before = issue.version

    mutation = await service.move_issue_to_column(
        db_session,
        board,
        issue,
        board.columns[1],
        initiator=owner,
    )

    assert mutation.changed
    assert issue.version == version_before + 1
    assert await _column_keys(db_session, board, 1, owner=owner) == [issue.key]


async def test_a_move_the_workflow_forbids_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Доска не пишет статус напрямую — иначе через неё обходился бы любой процесс.

    В шаблоне очереди из `open` нет ребра сразу в `closed`, и перетаскивание карточки
    получает тот же отказ, что и обычная смена статуса.
    """
    board = await make_board(
        columns=[
            ColumnDraft(name="Открыт", statuses=[await resolve_status("open")]),
            ColumnDraft(name="Закрыт", statuses=[await resolve_status("closed")]),
        ],
    )
    issue = await make_issue(summary="Первая")

    with pytest.raises(TransitionNotAllowedError):
        await service.move_issue_to_column(
            db_session,
            board,
            issue,
            board.columns[1],
            initiator=owner,
        )


async def test_a_column_with_several_statuses_requires_a_target(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Выбор за клиентом: угадывать значило бы переводить задачу в чужой статус."""
    board = await make_board(
        columns=[
            ColumnDraft(name="Открыт", statuses=[await resolve_status("open")]),
            ColumnDraft(
                name="Дальше",
                statuses=[
                    await resolve_status("in_progress"),
                    await resolve_status("closed"),
                ],
            ),
        ],
    )
    issue = await make_issue(summary="Первая")

    with pytest.raises(InvalidBoardMoveError) as error:
        await service.move_issue_to_column(
            db_session,
            board,
            issue,
            board.columns[1],
            initiator=owner,
        )

    assert error.value.details["reason"] == "status_required"


async def test_moving_into_the_column_the_card_already_sits_in_changes_nothing(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Иначе «на всякий случай» поднялась бы версия и в историю попал бы переход, которого нет."""
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    issue = await make_issue(summary="Первая")
    version_before = issue.version

    mutation = await service.move_issue_to_column(
        db_session,
        board,
        issue,
        board.columns[0],
        initiator=owner,
    )

    assert not mutation.changed
    assert issue.version == version_before


# --- Настройки доски ---------------------------------------------------------------


async def test_updating_a_board_records_only_actual_changes(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_board: MakeBoard,
    resolve_status: ResolveStatus,
) -> None:
    board = await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )

    _, unchanged = await service.update_board(
        db_session,
        board,
        initiator=owner,
        changes=BoardChanges(name=board.name),
    )
    _, changed = await service.update_board(
        db_session,
        board,
        initiator=owner,
        changes=BoardChanges(name="Доска релиза"),
    )

    assert unchanged == ()
    assert [change.field for change in changed] == ["name"]


async def test_a_missing_board_names_itself(db_session: AsyncSession, owner: Actor) -> None:
    from app.domain.errors import BoardNotFoundError

    with pytest.raises(BoardNotFoundError):
        await service.read_board(db_session, uuid.uuid4(), initiator=owner)
