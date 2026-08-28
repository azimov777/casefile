"""Жизненный цикл спринта: планирование, запуск, состав и завершение с переносом.

Главное здесь — завершение: оно уводит незакрытые задачи туда, куда сказал вызывающий,
и делает это через единую точку изменения задачи. Проверяется и сам перенос, и его
следы: у задачи растёт версия, а в истории видно, куда она уехала.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.board import Board, Sprint
from app.db.models.catalog import Resolution, Status
from app.db.models.event import ChangelogEntry
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.boards import SprintState, UnfinishedPolicy
from app.domain.catalogs import CatalogKind
from app.domain.errors import (
    BoardSprintActiveError,
    InvalidBoardError,
    SprintNotEmptyError,
    SprintNotFoundError,
    SprintStateError,
)
from app.domain.issues import IssueField
from app.services import boards as service
from app.services import queues as queues_service
from app.services.boards import ColumnDraft, SprintChanges

MakeBoard = Callable[..., Awaitable[Board]]
MakeSprint = Callable[..., Awaitable[Sprint]]
MakeIssue = Callable[..., Awaitable[Issue]]
ResolveStatus = Callable[[str], Awaitable[Status]]


@pytest.fixture
async def board(make_board: MakeBoard, resolve_status: ResolveStatus, queue: Queue) -> Board:
    return await make_board(
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )


async def _resolution(session: AsyncSession, owner: Actor, ref: str) -> Resolution:
    entry = await queues_service.resolve_catalog_ref(
        session,
        CatalogKind.RESOLUTION,
        ref,
        initiator=owner,
    )
    assert isinstance(entry, Resolution)
    return entry


# --- Планирование и запуск ---------------------------------------------------------


async def test_a_sprint_is_planned_not_started(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """Запуск — отдельное решение: иначе нельзя было бы запланировать второй спринт."""
    sprint = await make_sprint(board)

    assert sprint.state is SprintState.PLANNED
    assert sprint.started_at is None


async def test_starting_a_sprint_records_the_actual_moment(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """План и факт различаются: спринт запускают не в тот день, на который планировали."""
    sprint = await make_sprint(board)

    await service.start_sprint(db_session, sprint, initiator=owner)

    assert sprint.state is SprintState.ACTIVE
    assert sprint.started_at is not None


async def test_a_board_cannot_have_two_active_sprints(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """Иначе `sprint: current` и колонки доски потеряли бы единственный ответ."""
    first = await make_sprint(board, name="Спринт 1")
    second = await make_sprint(board, name="Спринт 2")
    await service.start_sprint(db_session, first, initiator=owner)

    with pytest.raises(BoardSprintActiveError):
        await service.start_sprint(db_session, second, initiator=owner)


async def test_starting_an_already_active_sprint_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """Не идемпотентно намеренно: тихий успех скрыл бы уже идущий спринт."""
    sprint = await make_sprint(board)
    await service.start_sprint(db_session, sprint, initiator=owner)

    with pytest.raises(SprintStateError) as error:
        await service.start_sprint(db_session, sprint, initiator=owner)

    assert error.value.details["reason"] == "cannot_start"


# --- Состав ------------------------------------------------------------------------


async def test_taking_an_issue_into_a_sprint_shows_up_in_its_history(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
) -> None:
    """Спринт — обычное поле задачи: правка идёт через единую точку и попадает в историю."""
    sprint = await make_sprint(board)
    issue = await make_issue(summary="Первая")
    version_before = issue.version

    await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[issue])

    assert issue.sprint_id == sprint.id
    assert issue.version == version_before + 1
    entries = (
        await db_session.scalars(select(ChangelogEntry).where(ChangelogEntry.issue_id == issue.id))
    ).all()
    fields = [change["field"] for entry in entries for change in entry.changes]
    assert IssueField.SPRINT.value in fields


async def test_taking_the_same_issue_twice_changes_nothing(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
) -> None:
    sprint = await make_sprint(board)
    issue = await make_issue(summary="Первая")
    await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[issue])
    version_before = issue.version

    mutations = await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[issue])

    assert not mutations[0].changed
    assert issue.version == version_before


async def test_an_issue_of_another_sprint_is_not_removed_silently(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
) -> None:
    """Молчаливый успех оставил бы клиента, перепутавшего спринт, с ложной уверенностью."""
    mine = await make_sprint(board, name="Мой спринт")
    other = await make_sprint(board, name="Чужой спринт")
    issue = await make_issue(summary="Первая")
    await service.add_sprint_issues(db_session, other, initiator=owner, issues=[issue])

    with pytest.raises(SprintNotFoundError) as error:
        await service.remove_sprint_issue(db_session, mine, initiator=owner, issue=issue)

    assert error.value.details["reason"] == "issue_not_in_sprint"


async def test_a_completed_sprint_accepts_no_new_issues(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
) -> None:
    """Задача, добавленная задним числом, переписала бы уже сделанный вывод о спринте."""
    sprint = await make_sprint(board)
    await service.start_sprint(db_session, sprint, initiator=owner)
    await service.complete_sprint(
        db_session,
        sprint,
        initiator=owner,
        unfinished=UnfinishedPolicy.BACKLOG,
    )
    issue = await make_issue(summary="Опоздавшая")

    with pytest.raises(SprintStateError) as error:
        await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[issue])

    assert error.value.details["reason"] == "cannot_accept_issues"


# --- Завершение --------------------------------------------------------------------


async def test_completing_a_sprint_returns_unfinished_issues_to_the_backlog(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
    resolve_status: ResolveStatus,
) -> None:
    """Закрытые остаются в спринте: он и есть запись о том, что команда успела."""
    sprint = await make_sprint(board)
    unfinished = await make_issue(summary="Осталась незакрытой")
    finished = await make_issue(
        summary="Закрыта до конца спринта",
        status=await resolve_status("closed"),
        resolution=await _resolution(db_session, owner, "done"),
    )
    await service.add_sprint_issues(
        db_session, sprint, initiator=owner, issues=[unfinished, finished]
    )
    await service.start_sprint(db_session, sprint, initiator=owner)

    completion = await service.complete_sprint(
        db_session,
        sprint,
        initiator=owner,
        unfinished=UnfinishedPolicy.BACKLOG,
    )

    assert completion.sprint.state is SprintState.COMPLETED
    assert completion.moved == (unfinished.key,)
    assert completion.target is None
    assert unfinished.sprint_id is None
    assert finished.sprint_id == sprint.id


async def test_completing_a_sprint_carries_unfinished_issues_over(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
) -> None:
    sprint = await make_sprint(board, name="Спринт 1")
    following = await make_sprint(board, name="Спринт 2")
    issue = await make_issue(summary="Осталась незакрытой")
    await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[issue])
    await service.start_sprint(db_session, sprint, initiator=owner)

    completion = await service.complete_sprint(
        db_session,
        sprint,
        initiator=owner,
        unfinished=UnfinishedPolicy.SPRINT,
        target=following,
    )

    assert completion.target is following
    assert issue.sprint_id == following.id


async def test_carrying_over_requires_a_target_sprint(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """Умолчания у выбора нет: молчаливое «в бэклог» однажды растащило бы чужой спринт."""
    sprint = await make_sprint(board)
    await service.start_sprint(db_session, sprint, initiator=owner)

    with pytest.raises(InvalidBoardError) as error:
        await service.complete_sprint(
            db_session,
            sprint,
            initiator=owner,
            unfinished=UnfinishedPolicy.SPRINT,
        )

    assert error.value.details["reason"] == "required"


async def test_a_sprint_of_another_board_is_not_a_valid_target(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_board: MakeBoard,
    make_sprint: MakeSprint,
    make_saved_filter: Callable[..., Awaitable[Any]],
    resolve_status: ResolveStatus,
) -> None:
    sprint = await make_sprint(board)
    await service.start_sprint(db_session, sprint, initiator=owner)
    other_board = await make_board(
        name="Вторая доска",
        saved_filter=await make_saved_filter(name="Второй фильтр"),
        columns=[ColumnDraft(name="Открыт", statuses=[await resolve_status("open")])],
    )
    foreign = await make_sprint(other_board, name="Чужой спринт")

    with pytest.raises(InvalidBoardError) as error:
        await service.complete_sprint(
            db_session,
            sprint,
            initiator=owner,
            unfinished=UnfinishedPolicy.SPRINT,
            target=foreign,
        )

    assert error.value.details["reason"] == "other_board"


async def test_only_an_active_sprint_can_be_completed(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    sprint = await make_sprint(board)

    with pytest.raises(SprintStateError) as error:
        await service.complete_sprint(
            db_session,
            sprint,
            initiator=owner,
            unfinished=UnfinishedPolicy.BACKLOG,
        )

    assert error.value.details["reason"] == "cannot_complete"


# --- Правка и удаление -------------------------------------------------------------


async def test_updating_a_sprint_records_only_actual_changes(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    sprint = await make_sprint(board)

    _, unchanged = await service.update_sprint(
        db_session,
        sprint,
        initiator=owner,
        changes=SprintChanges(name=sprint.name),
    )
    _, changed = await service.update_sprint(
        db_session,
        sprint,
        initiator=owner,
        changes=SprintChanges(goal="Закрыть выдачу ключей"),
    )

    assert unchanged == ()
    assert [change.field for change in changed] == ["goal"]


async def test_a_sprint_with_issues_is_not_deleted(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board: Board,
    make_sprint: MakeSprint,
    make_issue: MakeIssue,
) -> None:
    """Удаление унесло бы принадлежность задач молча."""
    sprint = await make_sprint(board)
    issue = await make_issue(summary="Первая")
    await service.add_sprint_issues(db_session, sprint, initiator=owner, issues=[issue])

    with pytest.raises(SprintNotEmptyError):
        await service.delete_sprint(db_session, sprint, initiator=owner)


async def test_an_active_sprint_is_not_deleted(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """Отмена идущей работы не бывает исправлением записи."""
    sprint = await make_sprint(board)
    await service.start_sprint(db_session, sprint, initiator=owner)

    with pytest.raises(SprintStateError) as error:
        await service.delete_sprint(db_session, sprint, initiator=owner)

    assert error.value.details["reason"] == "cannot_delete"


async def test_an_empty_planned_sprint_is_deleted(
    db_session: AsyncSession,
    owner: Actor,
    board: Board,
    make_sprint: MakeSprint,
) -> None:
    """Маршрут существует ради опечатки при планировании."""
    sprint = await make_sprint(board)

    await service.delete_sprint(db_session, sprint, initiator=owner)

    assert (await db_session.scalars(select(Sprint))).all() == []
