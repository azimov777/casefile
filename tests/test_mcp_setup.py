"""Инструменты настройки процесса: агент конструирует процесс, а не только работает в нём.

Главная проверка здесь — сценарий «с нуля»: очередь со своими статусами, собственный
воркфлоу и задача, заведённая в нём. Ровно этим задача 16 описывает готовность, и
разваливается такая сборка обычно на стыках: статус заведён, но не включён в граф; граф
собран, но не назначен типу задачи.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.services import queues as queues_service

type Call = Callable[..., Awaitable[dict[str, Any]]]


async def test_an_agent_builds_a_queue_with_its_own_process_and_files_an_issue(
    mcp_call: Call,
) -> None:
    """Полный сценарий настройки: очередь → свои статусы → свой процесс → задача в нём.

    Порядок шагов здесь не произволен, и он же — единственный работающий. Стартовый
    статус очереди обязан входить в граф каждого назначенного типа задачи, поэтому
    сначала свои статусы въезжают в существующий граф **вместе** со старым стартовым,
    потом умолчание очереди переезжает на свой статус, и только после этого старый
    статус из графа убирается.
    """
    await mcp_call("create_queue", key="OPS", name="Эксплуатация")
    await mcp_call("create_status", key="triage", name="Разбор", category="new", queue="OPS")
    await mcp_call("create_status", key="fixing", name="Чиним", category="in_progress", queue="OPS")
    await mcp_call("create_status", key="fixed", name="Починено", category="done", queue="OPS")
    await mcp_call("create_issue_type", key="incident", name="Инцидент", queue="OPS")
    await mcp_call("create_resolution", key="mitigated", name="Обошли", queue="OPS")
    await mcp_call("set_queue_issue_types", queue="OPS", issue_types=["task", "OPS.incident"])

    graphs = await mcp_call("get_workflow", queue="OPS")
    process = graphs["workflows"][0]
    own_statuses = [
        {"name": "Взять", "from_status": "OPS.triage", "to_status": "OPS.fixing"},
        {
            "name": "Починить",
            "from_status": "OPS.fixing",
            "to_status": "OPS.fixed",
            "requires_resolution": True,
        },
        {"name": "Вернуть", "from_status": "OPS.fixed", "to_status": "OPS.triage"},
    ]

    widened = await mcp_call(
        "replace_workflow",
        workflow=process["id"],
        name="Инциденты",
        initial_status="open",
        statuses=["open", "OPS.triage", "OPS.fixing", "OPS.fixed"],
        transitions=[
            {"name": "Взять в разбор", "from_status": "open", "to_status": "OPS.triage"},
            *own_statuses,
        ],
    )
    assert widened["applied"] is True

    await mcp_call("update_queue", queue="OPS", changes={"default_status": "OPS.triage"})

    narrowed = await mcp_call(
        "replace_workflow",
        workflow=process["id"],
        name="Инциденты",
        initial_status="OPS.triage",
        statuses=["OPS.triage", "OPS.fixing", "OPS.fixed"],
        transitions=own_statuses,
    )

    assert narrowed["initial_status"] == "OPS.triage"
    assert {item["ref"] for item in narrowed["statuses"]} == {
        "OPS.triage",
        "OPS.fixing",
        "OPS.fixed",
    }
    assert narrowed["impact"]["issues_without_outgoing_transitions"] == 0

    created = await mcp_call(
        "create_issue", queue="OPS", summary="Упал шлюз", issue_type="OPS.incident"
    )

    assert created["key"] == "OPS-1"
    assert created["status"] == "OPS.triage"

    available = await mcp_call("list_transitions", issue=created["key"])
    assert [item["to_status"] for item in available["transitions"]] == ["OPS.fixing"]


async def test_a_dry_run_reports_the_impact_and_writes_nothing(
    mcp_call: Call,
    db_session: AsyncSession,
    queue: Queue,
    owner: Any,
) -> None:
    """Предварительная проверка выполняет операцию по-настоящему и откатывает её."""
    await mcp_call("create_status", key="parked", name="Отложено", category="new", queue="TRK")

    preview = await mcp_call(
        "create_workflow",
        queue="TRK",
        name="Черновик процесса",
        initial_status="TRK.parked",
        statuses=["TRK.parked", "closed"],
        transitions=[
            {
                "name": "Закрыть",
                "from_status": "TRK.parked",
                "to_status": "closed",
                "requires_resolution": True,
            }
        ],
        dry_run=True,
    )

    assert preview["applied"] is False
    assert preview["name"] == "Черновик процесса"

    # Очередь перечитывается, а не берётся из фикстуры: откат внутри `dry_run` пометил
    # уже загруженные объекты сессии устаревшими, и обращение к их полям ушло бы в базу
    # мимо async-контекста.
    reloaded = await queues_service.get_queue_by_key(db_session, "TRK")
    config = await queues_service.get_queue_config(db_session, reloaded, initiator=owner)
    assert "Черновик процесса" not in {view.workflow.name for view in config.workflows}


async def test_a_graph_that_traps_issues_is_refused_with_the_rule_it_breaks(
    mcp_call: Call,
    queue: Queue,
) -> None:
    """Граф проверяется целиком: недостижимый статус — отказ, а не половина процесса."""
    with pytest.raises(ToolError) as failure:
        await mcp_call(
            "create_workflow",
            queue="TRK",
            name="Тупиковый процесс",
            initial_status="open",
            statuses=["open", "in_progress", "closed"],
            transitions=[
                {
                    "name": "Закрыть",
                    "from_status": "open",
                    "to_status": "closed",
                    "requires_resolution": True,
                }
            ],
        )

    message = str(failure.value)
    assert "workflow" in message
    assert "in_progress" in message


async def test_a_transition_is_replaced_and_the_answer_carries_the_whole_graph(
    mcp_call: Call,
    queue: Queue,
) -> None:
    """Точечная правка проверяется против всего графа и отдаёт его новое состояние."""
    graphs = await mcp_call("get_workflow", queue="TRK")
    graph = graphs["workflows"][0]
    start = next(item for item in graph["transitions"] if item["to_status"] == "in_progress")

    updated = await mcp_call(
        "update_workflow_transition",
        workflow=graph["id"],
        transition=start["id"],
        definition={
            "name": "Взять в работу",
            "from_status": "open",
            "to_status": "in_progress",
            "required_fields": ["assignee"],
        },
    )

    changed = next(item for item in updated["transitions"] if item["id"] == start["id"])
    assert changed["name"] == "Взять в работу"
    assert changed["required_fields"] == ["assignee"]


async def test_a_required_field_blocks_the_transition_until_it_is_filled(
    mcp_call: Call,
    make_issue: Callable[..., Awaitable[Any]],
    queue: Queue,
) -> None:
    """Требование перехода видно заранее: список называет, чего не хватает."""
    graphs = await mcp_call("get_workflow", queue="TRK")
    graph = graphs["workflows"][0]
    start = next(item for item in graph["transitions"] if item["to_status"] == "in_progress")
    await mcp_call(
        "update_workflow_transition",
        workflow=graph["id"],
        transition=start["id"],
        definition={
            "name": "Взять в работу",
            "from_status": "open",
            "to_status": "in_progress",
            "required_fields": ["assignee"],
        },
    )
    issue = await make_issue()

    available = await mcp_call("list_transitions", issue=issue.key)
    forward = next(item for item in available["transitions"] if item["id"] == start["id"])

    assert forward["is_available"] is False
    assert forward["missing_fields"] == ["assignee"]


async def test_a_custom_field_is_created_and_required_on_creation(
    mcp_call: Call,
    queue: Queue,
) -> None:
    """Поле заводится без миграции, а обязательность видна в ошибке создания задачи."""
    field = await mcp_call(
        "create_field",
        key="severity",
        name="Серьёзность",
        value_type="enum",
        queue="TRK",
        is_required=True,
        options=[{"key": "minor", "name": "Малая"}, {"key": "major", "name": "Большая"}],
    )

    assert field["ref"] == "TRK.severity"
    assert field["options"] == ["minor", "major"]

    with pytest.raises(ToolError) as failure:
        await mcp_call("create_issue", queue="TRK", summary="Без серьёзности")

    message = str(failure.value)
    assert "TRK.severity" in message
    assert "required" in message

    created = await mcp_call(
        "create_issue",
        queue="TRK",
        summary="Заполненная серьёзность",
        values={"TRK.severity": "major"},
    )
    assert created["values"] == {"TRK.severity": "major"}


async def test_hiding_a_field_is_how_it_is_retired(mcp_call: Call, queue: Queue) -> None:
    """Скрытие — единственный способ убрать поле, которым уже пользовались."""
    await mcp_call("create_field", key="note", name="Заметка", value_type="string", queue="TRK")

    hidden = await mcp_call("update_field", field="TRK.note", changes={"is_hidden": True})

    assert hidden["is_hidden"] is True
    config = await mcp_call("get_queue_config", queue="TRK")
    assert "TRK.note" not in {item["ref"] for item in config["fields"]}


async def test_an_automation_rule_is_switched_on_through_the_tool(
    mcp_call: Call,
    automation_rules: dict[str, Any],
) -> None:
    """Правило настраивается схемой самого правила, второй проверки в MCP нет."""
    rules = await mcp_call("list_automation_rules")
    macro = next(item for item in rules["items"] if item["kind"] == "macro")

    configured = await mcp_call(
        "configure_automation_rule", rule=macro["key"], changes={"is_enabled": True}
    )

    assert configured["is_enabled"] is True
    assert configured["params_schema"]["type"] == "object"


async def test_rule_parameters_are_rejected_by_the_rule_schema(
    mcp_call: Call,
    automation_rules: dict[str, Any],
) -> None:
    """Мусор в параметрах отвергается при сохранении, а не всплывает падением в фоне."""
    rules = await mcp_call("list_automation_rules")
    rule = next(item for item in rules["items"] if item["params_schema"].get("properties"))

    with pytest.raises(ToolError) as failure:
        await mcp_call(
            "configure_automation_rule",
            rule=rule["key"],
            changes={"params": {"unknown_parameter": 1}},
        )

    assert "automation" in str(failure.value)
