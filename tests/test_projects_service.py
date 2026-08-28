"""Сценарии проектов и портфелей: состав, прогресс, вложенность, архив.

Три вещи проверяются особенно придирчиво, потому что каждая из них ломается молча.

**Состав идёт через единую точку изменения задачи.** Присваивание `issue.project_id`
мимо `apply_issue_changes` не даёт ни записи в истории, ни события, и обнаружилось бы
это через несколько задач как дыра в истории.

**Прогресс считается по категории статуса, а не по его ключу.** Команда переименовывает
«Закрыт» в «Готово», и прогресс от этого меняться не должен.

**Цикл во вложенности портфелей ловится на произвольной глубине.** Кольцо из трёх
портфелей ломает обход состава так же, как из двух, а проверка «только прямой родитель»
выглядит работающей.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.issue import Issue
from app.db.models.project import Portfolio, Project
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind
from app.domain.errors import (
    ActorInactiveError,
    InvalidProjectError,
    PortfolioArchivedError,
    PortfolioCycleError,
    PortfolioKeyTakenError,
    ProjectArchivedError,
    ProjectKeyTakenError,
    ProjectNotFoundError,
)
from app.domain.projects import PlanningKind, ProjectStatus
from app.services import actors as actors_service
from app.services import issues as issues_service
from app.services import projects as service
from app.services import queues as queues_service
from app.services.projects import PlanningChanges

MakeIssue = Callable[..., Awaitable[Issue]]
MakeProject = Callable[..., Awaitable[Project]]
MakePortfolio = Callable[..., Awaitable[Portfolio]]


async def _closed_issue(
    session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    **kwargs: Any,
) -> Issue:
    """Задача в статусе категории `done`: именно она попадает в числитель прогресса."""
    closed = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, "closed", initiator=owner
    )
    done = await queues_service.resolve_catalog_ref(
        session, CatalogKind.RESOLUTION, "done", initiator=owner
    )
    return await make_issue(status=closed, resolution=done, **kwargs)


async def _second_queue(session: AsyncSession, owner: Actor) -> Queue:
    return await queues_service.create_queue(
        session, initiator=owner, key="OPS", name="Эксплуатация"
    )


# --- Создание ------------------------------------------------------------------------


async def test_a_project_answers_with_its_creator_as_the_lead(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    """Проект, заведённый агентом, отвечает агентом, а не владельцем установки."""
    project = await make_project()

    assert project.lead.key == owner.key
    assert project.status is ProjectStatus.NOT_STARTED
    assert project.is_archived is False


async def test_a_project_key_is_taken_once(
    db_session: AsyncSession,
    make_project: MakeProject,
) -> None:
    await make_project(key="alpha")

    with pytest.raises(ProjectKeyTakenError):
        await make_project(key="alpha")


async def test_a_project_and_a_portfolio_may_share_a_key(
    db_session: AsyncSession,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    """Пространства имён разные: адресуются они разными путями и разными фильтрами.

    Общий запрет отнимал бы имена без пользы — `alpha` как портфель и `alpha` как проект
    ни в одном запросе не встречаются вместе.
    """
    await make_project(key="alpha")
    portfolio = await make_portfolio(key="alpha")

    assert portfolio.key == "alpha"

    with pytest.raises(PortfolioKeyTakenError):
        await make_portfolio(key="alpha", name="Второй")


async def test_an_inactive_actor_cannot_be_made_a_lead(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    """Отключение — способ убрать агента, не ломая историю; назначать его заново нельзя."""
    retired, _ = await actors_service.ensure_actor(
        db_session, actor_type="agent", key="retired", display_name="Retired"
    )
    await actors_service.update_actor(db_session, retired, initiator=owner, is_active=False)

    with pytest.raises(ActorInactiveError):
        await make_project(lead=retired)


async def test_members_are_deduplicated_but_an_inactive_one_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    """Повтор — небрежность клиента, отключённый актор — расхождение с его ожиданием.

    Молча выбросить отключённого значило бы оставить клиента с уверенностью, что он
    кого-то добавил.
    """
    project = await make_project(members=[owner, owner])
    assert [member.key for member in project.members] == [owner.key]

    retired, _ = await actors_service.ensure_actor(
        db_session, actor_type="agent", key="retired", display_name="Retired"
    )
    await actors_service.update_actor(db_session, retired, initiator=owner, is_active=False)

    with pytest.raises(ActorInactiveError):
        await make_project(key="beta", members=[retired])


async def test_an_inverted_period_is_refused_at_creation(
    db_session: AsyncSession,
    make_project: MakeProject,
) -> None:
    with pytest.raises(InvalidProjectError):
        await make_project(start_date=date(2026, 3, 1), end_date=date(2026, 1, 1))


# --- Состав --------------------------------------------------------------------------


async def test_a_project_collects_issues_from_different_queues(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """То, ради чего проект и существует: результат собирается поперёк процессов команд."""
    other = await _second_queue(db_session, owner)
    first = await make_issue()
    second = await make_issue(queue=other)
    project = await make_project()

    await service.add_issues(db_session, project, initiator=owner, issues=[first, second])

    assert first.project_id == project.id
    assert second.project_id == project.id
    assert first.queue_id != second.queue_id


async def test_adding_an_issue_writes_its_history_and_an_event(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Состав проекта — поле задачи, поэтому изменение видно в истории самой задачи.

    Присваивание мимо единой точки не дало бы ни записи, ни события, и заметили бы это
    как дыру в истории спустя несколько задач.
    """
    issue = await make_issue()
    project = await make_project()

    await service.add_issues(db_session, project, initiator=owner, issues=[issue])

    entries = list(
        await db_session.scalars(select(ChangelogEntry).where(ChangelogEntry.issue_id == issue.id))
    )
    changes = [change for entry in entries for change in entry.changes]
    assert {"field": "project", "before": None, "after": "alpha"} in changes


async def test_adding_an_issue_twice_changes_nothing(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Идемпотентность: клиент, повторивший запрос, не должен получать отказ.

    Версия задачи при повторе тоже не растёт — единая точка не пишет изменения, которого
    не было.
    """
    issue = await make_issue()
    project = await make_project()
    await service.add_issues(db_session, project, initiator=owner, issues=[issue])
    version = issue.version

    mutations = await service.add_issues(db_session, project, initiator=owner, issues=[issue])

    assert mutations[0].changed is False
    assert issue.version == version


async def test_an_issue_moves_between_projects_without_a_ritual(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Переезд идёт одним действием: «сначала вынь, потом положи» — лишний шаг.

    Задача входит не более чем в один проект, поэтому старая привязка снимается сама, и
    в истории это видно как обычное изменение поля.
    """
    issue = await make_issue()
    first = await make_project(key="alpha")
    second = await make_project(key="beta", name="Витрина")
    await service.add_issues(db_session, first, initiator=owner, issues=[issue])

    await service.add_issues(db_session, second, initiator=owner, issues=[issue])

    assert issue.project_id == second.id


async def test_removing_an_issue_from_the_wrong_project_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Молчаливый успех оставил бы клиента с уверенностью, что задача вынута."""
    issue = await make_issue()
    first = await make_project(key="alpha")
    second = await make_project(key="beta", name="Витрина")
    await service.add_issues(db_session, first, initiator=owner, issues=[issue])

    with pytest.raises(ProjectNotFoundError) as error:
        await service.remove_issue(db_session, second, initiator=owner, issue=issue)

    assert error.value.details["reason"] == "issue_not_in_project"
    assert issue.project_id == first.id


async def test_an_archived_project_accepts_no_new_issues(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Архив запрещает приём новой работы; правка полей проекта при этом остаётся."""
    issue = await make_issue()
    project = await make_project()
    await service.archive_project(db_session, project, initiator=owner)

    with pytest.raises(ProjectArchivedError):
        await service.add_issues(db_session, project, initiator=owner, issues=[issue])

    renamed, _ = await service.update_project(
        db_session, project, initiator=owner, changes=PlanningChanges(name="Закрытый проект")
    )
    assert renamed.name == "Закрытый проект"


async def test_the_same_ban_holds_when_the_project_comes_from_a_plain_patch(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Запрет живёт в единой точке изменения задачи, а не только в сценарии проекта.

    Иначе он обходился бы с чёрного хода: `PATCH /issues/{key}` с полем `project` идёт
    мимо `add_issues`.
    """
    issue = await make_issue()
    project = await make_project()
    await service.archive_project(db_session, project, initiator=owner)

    with pytest.raises(ProjectArchivedError):
        await issues_service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=issues_service.IssueChanges(project=project),
        )


# --- Прогресс ------------------------------------------------------------------------


async def test_progress_counts_the_done_category_not_the_status_key(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    """Команда переименовывает «Закрыт» в «Готово» — прогресс от этого не меняется."""
    project = await make_project()
    issues = [
        await make_issue(),
        await make_issue(),
        await _closed_issue(db_session, owner, make_issue),
    ]
    await service.add_issues(db_session, project, initiator=owner, issues=issues)

    progress = (await service.project_progress(db_session, [project]))[project.id]

    assert (progress.total, progress.done) == (3, 1)


async def test_issues_outside_the_project_are_not_counted(
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    make_project: MakeProject,
) -> None:
    project = await make_project()
    inside = await make_issue()
    await make_issue()
    await service.add_issues(db_session, project, initiator=owner, issues=[inside])

    progress = (await service.project_progress(db_session, [project]))[project.id]

    assert progress.total == 1


async def test_a_project_without_issues_gets_a_zero_progress_not_a_missing_key(
    db_session: AsyncSession,
    make_project: MakeProject,
) -> None:
    """`GROUP BY` не возвращает строк для пустых групп — разбирать это должен сценарий."""
    project = await make_project()

    progress = await service.project_progress(db_session, [project])

    assert progress[project.id].total == 0
    assert progress[project.id].ratio is None


async def test_a_portfolio_sums_issues_of_every_descendant_project(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    """Прогресс портфеля — доля закрытых среди **всех** задач под ним, на любой глубине.

    Проверяется именно вложенность: проект внутреннего портфеля обязан попасть в
    счётчики внешнего, иначе агрегация врала бы ровно там, где портфели и нужны.
    """
    root = await make_portfolio(key="platform")
    nested = await make_portfolio(key="core", name="Ядро", parent=root)
    outer = await make_project(key="alpha", portfolio=root)
    inner = await make_project(key="beta", name="Ядро", portfolio=nested)

    await service.add_issues(
        db_session,
        outer,
        initiator=owner,
        issues=[await make_issue(), await _closed_issue(db_session, owner, make_issue)],
    )
    await service.add_issues(
        db_session,
        inner,
        initiator=owner,
        issues=[await _closed_issue(db_session, owner, make_issue)],
    )

    progress = await service.portfolio_progress(db_session, [root, nested])

    assert (progress[root.id].total, progress[root.id].done) == (3, 2)
    assert (progress[nested.id].total, progress[nested.id].done) == (1, 1)


async def test_a_portfolio_without_projects_has_nothing_to_measure(
    db_session: AsyncSession,
    make_portfolio: MakePortfolio,
) -> None:
    portfolio = await make_portfolio()

    progress = await service.portfolio_progress(db_session, [portfolio])

    assert progress[portfolio.id].ratio is None


async def test_child_counts_look_only_one_level_down(
    db_session: AsyncSession,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    """«Что лежит в этом портфеле» и «что под ним вообще» — разные вопросы.

    Счётчики карточки отвечают на первый; на второй отвечает прогресс.
    """
    root = await make_portfolio(key="platform")
    nested = await make_portfolio(key="core", name="Ядро", parent=root)
    await make_project(key="alpha", portfolio=root)
    await make_project(key="beta", name="Ядро", portfolio=nested)

    counts = await service.portfolio_child_counts(db_session, [root, nested])

    assert counts[root.id] == (1, 1)
    assert counts[nested.id] == (1, 0)


# --- Вложенность и циклы -------------------------------------------------------------


async def test_a_portfolio_cannot_be_put_into_itself(
    db_session: AsyncSession,
    owner: Actor,
    make_portfolio: MakePortfolio,
) -> None:
    """Отдельной проверки «сам себе родитель» нет: подъём считает портфель своим предком."""
    portfolio = await make_portfolio()

    with pytest.raises(PortfolioCycleError):
        await service.move_portfolio(db_session, portfolio, initiator=owner, parent=portfolio)


async def test_a_cycle_is_caught_at_any_depth(
    db_session: AsyncSession,
    owner: Actor,
    make_portfolio: MakePortfolio,
) -> None:
    """Кольцо из трёх ломает обход состава так же, как из двух.

    Проверка «только прямой родитель» выглядела бы работающей и пропустила бы этот
    случай — а обход состава после него ушёл бы в бесконечность.
    """
    first = await make_portfolio(key="one", name="Один")
    second = await make_portfolio(key="two", name="Два", parent=first)
    third = await make_portfolio(key="three", name="Три", parent=second)

    with pytest.raises(PortfolioCycleError):
        await service.move_portfolio(db_session, first, initiator=owner, parent=third)


async def test_a_portfolio_moves_out_to_the_top_level(
    db_session: AsyncSession,
    owner: Actor,
    make_portfolio: MakePortfolio,
) -> None:
    """`None` — осмысленное значение, а не «не передано»: портфель становится корневым."""
    root = await make_portfolio(key="platform")
    nested = await make_portfolio(key="core", name="Ядро", parent=root)

    moved = await service.move_portfolio(db_session, nested, initiator=owner, parent=None)

    assert moved.parent_id is None


async def test_a_project_moves_between_portfolios(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    first = await make_portfolio(key="one", name="Один")
    second = await make_portfolio(key="two", name="Два")
    project = await make_project(portfolio=first)

    moved = await service.move_project(db_session, project, initiator=owner, portfolio=second)

    assert moved.portfolio_id == second.id


async def test_an_archived_portfolio_accepts_no_content(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    portfolio = await make_portfolio()
    project = await make_project()
    await service.archive_portfolio(db_session, portfolio, initiator=owner)

    with pytest.raises(PortfolioArchivedError):
        await service.move_project(db_session, project, initiator=owner, portfolio=portfolio)


async def test_archiving_a_portfolio_leaves_its_content_alone(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    """Каскадная архивация состава необратима: что лежало в архиве до неё, уже не узнать."""
    portfolio = await make_portfolio()
    project = await make_project(portfolio=portfolio)

    await service.archive_portfolio(db_session, portfolio, initiator=owner)

    assert project.is_archived is False


# --- Состав портфеля -----------------------------------------------------------------


async def test_the_content_of_a_portfolio_is_one_ordered_list(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    """Проекты и вложенные портфели приезжают одним списком, различаясь полем `kind`.

    Две отдельные страницы нельзя было бы склеить: курсор указывает позицию в одном
    упорядоченном запросе, и на границе записи терялись бы.
    """
    root = await make_portfolio(key="platform")
    await make_portfolio(key="core", name="Ядро", parent=root)
    await make_project(key="alpha", portfolio=root)
    await make_project(key="beta", name="Витрина")

    page = await service.portfolio_content(db_session, root, initiator=owner)

    assert {(item.kind, item.entity.key) for item in page.items} == {
        (PlanningKind.PORTFOLIO, "core"),
        (PlanningKind.PROJECT, "alpha"),
    }


async def test_the_content_pages_without_losing_entries(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
    make_portfolio: MakePortfolio,
) -> None:
    """Проверяется полнота страниц, а не их порядок.

    Все объекты теста создаются в одной транзакции, поэтому `created_at` у них
    совпадает, и порядок задаёт случайный UUID (`docs/notes/testing.md`). Ради этого
    случая второй элемент ключа сортировки и нужен — без него страницы теряли бы записи.
    """
    root = await make_portfolio(key="platform")
    for index in range(3):
        await make_portfolio(key=f"nested{index}", name=f"Вложенный {index}", parent=root)
        await make_project(key=f"project{index}", name=f"Проект {index}", portfolio=root)

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = await service.portfolio_content(
            db_session, root, initiator=owner, limit=2, cursor=cursor
        )
        seen.extend(item.entity.key for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == sorted(
        [f"nested{index}" for index in range(3)] + [f"project{index}" for index in range(3)]
    )


# --- Правки и события ----------------------------------------------------------------


async def test_a_change_that_changes_nothing_produces_no_event(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    """То же правило, что у задачи: подписчик не должен реагировать на пустую правку."""
    project = await make_project(name="Платформа доставки")
    before = len(list(await db_session.scalars(select(OutboxEvent))))

    _, changes = await service.update_project(
        db_session,
        project,
        initiator=owner,
        changes=PlanningChanges(name="Платформа доставки"),
    )

    assert changes == ()
    assert len(list(await db_session.scalars(select(OutboxEvent)))) == before


async def test_archiving_publishes_its_own_event_type(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    """«Проект выбыл из работы» подписчик обязан отбирать по типу, а не разбором нагрузки."""
    project = await make_project()

    await service.archive_project(db_session, project, initiator=owner)

    events = list(await db_session.scalars(select(OutboxEvent)))
    assert events[-1].event_type == "project.archived"
    assert events[-1].object_key == "alpha"
    assert events[-1].payload["project"]["is_archived"] is True


async def test_archiving_is_idempotent(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    project = await make_project()
    await service.archive_project(db_session, project, initiator=owner)
    count = len(list(await db_session.scalars(select(OutboxEvent))))

    await service.archive_project(db_session, project, initiator=owner)

    assert len(list(await db_session.scalars(select(OutboxEvent)))) == count


async def test_the_period_is_validated_against_the_state_after_the_change(
    db_session: AsyncSession,
    owner: Actor,
    make_project: MakeProject,
) -> None:
    """Клиент вправе прислать только одну границу — сравнивать её надо с будущей второй.

    Проверка «по одной границе» пропустила бы вывернутый период, собранный из старой
    даты начала и новой даты окончания.
    """
    project = await make_project(start_date=date(2026, 3, 1))

    with pytest.raises(InvalidProjectError):
        await service.update_project(
            db_session,
            project,
            initiator=owner,
            changes=PlanningChanges(end_date=date(2026, 1, 1)),
        )
