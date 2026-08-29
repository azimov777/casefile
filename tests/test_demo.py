"""Демо-данные: свойства набора, без которых он бесполезен.

Проверяется не «сколько чего создалось» — такой тест ломается от любой правки набора и
не ловит ничего. Проверяются свойства, ради которых набор вообще существует: он создан
сценариями (а значит, на нём работают история, события и автоматика), в нём включено
правило, доска покрывает все статусы процесса, а проект собран поперёк очередей.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.repositories.automation import AutomationRuleRepository
from app.services import boards as boards_service
from app.services import demo as demo_service
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import projects as projects_service
from app.services import queues as queues_service
from app.services import workflow as workflow_service


async def test_the_set_is_created_through_scenarios_so_it_has_history_and_events(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Главное свойство набора: он неотличим от данных, наработанных руками.

    Прямые вставки в базу дали бы задачи без истории и без событий — то есть набор, на
    котором нельзя проверить ни автоматику, ни уведомления, ни поток событий. Проверка
    именно на это, а не на число строк.
    """
    await demo_service.seed_demo(db_session, owner=owner)

    events = await db_session.scalar(select(func.count()).select_from(OutboxEvent))
    changes = await db_session.scalar(select(func.count()).select_from(ChangelogEntry))
    assert events and events > 20, f"the set produced only {events} events"
    assert changes and changes > 20, f"the set produced only {changes} changelog entries"

    # У проведённой по процессу задачи в журнале есть и создание, и смена статуса.
    issue = await issues_service.get_issue_by_key(db_session, f"{demo_service.DEV_QUEUE_KEY}-2")
    page = await events_service.list_changelog(db_session, issue, initiator=owner, limit=50)
    recorded = [entry.event_type for entry in page.items]
    assert recorded[0] == "issue.created"
    assert "issue.status_changed" in recorded


async def test_the_set_ships_with_an_enabled_automation_rule(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Без включённого правила демо-контур показывает трекер без его главной механики.

    Поставочные правила приезжают выключенными, и включить одно — часть набора, а не
    настройка на стороне того, кто его развернул: иначе сквозной сценарий «правило
    сработало → пришло уведомление» не на чем прогнать.
    """
    await demo_service.seed_demo(db_session, owner=owner)

    rules = {rule.rule_key: rule for rule in await AutomationRuleRepository(db_session).list_all()}
    enabled = [key for key, rule in rules.items() if rule.is_enabled]

    assert enabled == [demo_service.DEMO_RULE_KEY]
    bound = rules[demo_service.DEMO_RULE_KEY]
    assert bound.queue is not None and bound.queue.key == demo_service.DEV_QUEUE_KEY
    # Режим по умолчанию: правило комментирует родителя, а не закрывает чужие задачи.
    assert bound.params.get("mode", "announce") == "announce"


async def test_the_board_covers_every_status_of_its_workflow(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Статус без колонки прячет свои задачи от доски — набор не должен этому учить.

    Найти такую задачу через доску можно только маршрутом «все задачи доски»; через
    колонки её не видно вовсе. Демо-набор поэтому раскладывает все статусы процесса.
    """
    await demo_service.seed_demo(db_session, owner=owner)

    dev = await queues_service.get_queue_by_key(db_session, demo_service.DEV_QUEUE_KEY)
    config = await queues_service.get_queue_config(db_session, dev, initiator=owner)
    graph = workflow_service.graph_definition(config.workflows[0].workflow)
    in_process = {status.ref for status in graph.statuses}

    board = (await boards_service.list_boards(db_session, initiator=owner)).items[0]
    in_columns = {link.status.ref for column in board.columns for link in column.status_links}

    assert in_process <= in_columns, sorted(in_process - in_columns)


async def test_the_project_spans_two_queues(db_session: AsyncSession, owner: Actor) -> None:
    """Проект, собранный из одной очереди, ничем не отличался бы от самой очереди."""
    await demo_service.seed_demo(db_session, owner=owner)

    project = await projects_service.get_project_by_key(db_session, "alpha")
    outcome = await projects_service.list_project_issues(
        db_session, project, initiator=owner, limit=50
    )

    assert {issue.queue.key for issue in outcome.page.items} == {
        demo_service.DEV_QUEUE_KEY,
        demo_service.OPS_QUEUE_KEY,
    }


async def test_a_seeded_installation_is_recognised_as_seeded(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Признак нужен команде: повторный запуск обязан отказать, а не создать вторую копию."""
    assert not await demo_service.demo_is_present(db_session)

    await demo_service.seed_demo(db_session, owner=owner)

    assert await demo_service.demo_is_present(db_session)
