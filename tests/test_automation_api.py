"""Эндпоинты автоматики: список правил, настройка, журнал, ручной запуск макроса.

Проверяется контракт, а не поведение движка: оболочка ответа, обе половины правила в
одном объекте, отказ на мусорных параметрах при сохранении и то, что неудача макроса
приходит записью журнала, а не пятисоткой.

Заведения и удаления правил в API нет — правило это код, — поэтому и проверять здесь
нечего, кроме того, что таких маршрутов действительно не существует.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule
from app.db.models.issue import Issue

MakeIssue = Callable[..., Awaitable[Issue]]
EnableRule = Callable[..., Awaitable[AutomationRule]]


async def test_the_rule_list_shows_the_declaration_next_to_the_state(
    auth_client: AsyncClient,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Правило отдаётся целиком: форма и события из кода, включённость и параметры из базы."""
    response = await auth_client.get("/api/v1/automation/rules")

    assert response.status_code == 200
    body = response.json()
    assert "meta" in body
    rules = {item["key"]: item for item in body["data"]}

    trigger = rules["close_children_with_parent"]
    assert trigger["kind"] == "trigger"
    assert trigger["events"] == ["issue.status_changed"]
    assert trigger["is_available"] is True
    # Новое правило приезжает выключенным: включённое с выкладкой начало бы менять
    # задачи в ту же минуту, когда его ещё никто не настроил.
    assert trigger["is_enabled"] is False
    # Схема параметров нужна интерфейсу, чтобы построить форму настройки.
    assert "mode" in trigger["params_schema"]["properties"]

    scheduled = rules["nudge_stale_issues"]
    assert scheduled["kind"] == "scheduled"
    assert scheduled["schedule_seconds"] == 6 * 60 * 60
    assert "updated_at" in (scheduled["query"] or "")


async def test_a_rule_is_read_by_its_key(
    auth_client: AsyncClient,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Адресация ключом из кода, а не идентификатором строки."""
    response = await auth_client.get("/api/v1/automation/rules/prepare_release")

    assert response.status_code == 200
    assert response.json()["data"]["kind"] == "macro"


async def test_an_unknown_rule_answers_with_its_own_code(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/automation/rules/no_such_rule")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "automation_rule_not_found"


async def test_a_rule_is_switched_on_and_configured_without_a_restart(
    auth_client: AsyncClient,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Включение и параметры меняются запросом; расписание сразу получает срок."""
    response = await auth_client.patch(
        "/api/v1/automation/rules/nudge_stale_issues",
        json={"is_enabled": True, "params": {"silence_days": 3, "unassign": True}},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_enabled"] is True
    assert data["params"]["silence_days"] == 3
    # Включённое автодействие обязано попасть в выборку планировщика, а не ждать
    # полного периода: человек включил его, чтобы оно заработало.
    assert data["next_run_at"] is not None


async def test_turning_a_scheduled_rule_off_clears_its_schedule(
    auth_client: AsyncClient,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Выключенное правило не должно подниматься выборкой планировщика каждый тик."""
    await auth_client.patch(
        "/api/v1/automation/rules/nudge_stale_issues",
        json={"is_enabled": True},
    )
    response = await auth_client.patch(
        "/api/v1/automation/rules/nudge_stale_issues",
        json={"is_enabled": False},
    )

    assert response.json()["data"]["next_run_at"] is None


async def test_bad_parameters_are_refused_when_saved(
    auth_client: AsyncClient,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Мусор в параметрах — отказ сейчас, а не падение в фоне через неделю."""
    response = await auth_client.patch(
        "/api/v1/automation/rules/nudge_stale_issues",
        json={"params": {"silence_days": 0}},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "automation_params_invalid"
    assert error["details"]["fields"][0]["field"] == "silence_days"


async def test_a_rule_is_bound_to_a_queue_by_its_key(
    auth_client: AsyncClient,
    automation_rules: dict[str, AutomationRule],
    queue: Any,
) -> None:
    """Привязка задаётся ключом очереди и снимается передачей `null`."""
    bound = await auth_client.patch(
        "/api/v1/automation/rules/close_children_with_parent",
        json={"queue": "TRK"},
    )
    assert bound.json()["data"]["queue"] == "TRK"

    released = await auth_client.patch(
        "/api/v1/automation/rules/close_children_with_parent",
        json={"queue": None},
    )
    assert released.json()["data"]["queue"] is None


async def test_a_macro_is_run_by_hand_and_answers_with_the_journal_entry(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Ответ на ручной запуск — запись журнала: что сделано, кем и за сколько."""
    await enable_rule("prepare_release")
    issue = await make_issue(summary="Релиз 1.4")

    response = await auth_client.post(
        "/api/v1/automation/rules/prepare_release/run",
        json={"issue": issue.key, "params": {"tags": ["release"], "checklist": []}},
    )

    assert response.status_code == 200
    run = response.json()["data"]
    assert run["status"] == "success"
    assert run["trigger"] == "manual"
    assert run["issue"] == issue.key
    assert run["initiator"] == "owner"
    assert {action["action"] for action in run["actions"]} == {"update"}


async def test_a_disabled_macro_is_refused_by_the_endpoint(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
    automation_rules: dict[str, AutomationRule],
) -> None:
    """Выключатель действует и на ручной запуск, иначе он работал бы наполовину."""
    issue = await make_issue()

    response = await auth_client.post(
        "/api/v1/automation/rules/prepare_release/run",
        json={"issue": issue.key},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "automation_rule_disabled"


async def test_a_trigger_cannot_be_run_through_the_macro_endpoint(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Форма правила проверяется до выполнения: триггеру нечем заменить событие."""
    await enable_rule("close_children_with_parent")
    issue = await make_issue()

    response = await auth_client.post(
        "/api/v1/automation/rules/close_children_with_parent/run",
        json={"issue": issue.key},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "automation_rule_kind_mismatch"


async def test_the_journal_lists_runs_and_filters_them(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: EnableRule,
) -> None:
    """Журнал листается общей пагинацией и отбирается по правилу, задаче и результату."""
    await enable_rule("prepare_release")
    issue = await make_issue(summary="Релиз 1.4")
    await auth_client.post(
        "/api/v1/automation/rules/prepare_release/run",
        json={"issue": issue.key, "params": {"checklist": []}},
    )

    listed = await auth_client.get("/api/v1/automation/runs")
    assert listed.status_code == 200
    body = listed.json()
    assert body["meta"]["has_more"] is False
    assert [item["rule"] for item in body["data"]] == ["prepare_release"]

    by_issue = await auth_client.get("/api/v1/automation/runs", params={"issue": issue.key})
    assert len(by_issue.json()["data"]) == 1

    by_status = await auth_client.get("/api/v1/automation/runs", params={"status": "failed"})
    assert by_status.json()["data"] == []


async def test_rules_cannot_be_created_through_the_api(auth_client: AsyncClient) -> None:
    """Правило — это код в репозитории, а не строка, которую можно завести запросом."""
    response = await auth_client.post("/api/v1/automation/rules", json={"key": "invented"})

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
