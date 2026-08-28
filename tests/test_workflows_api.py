"""REST воркфлоу: граф целиком, точечный редактор и переход задачи."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind, StatusCategory
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[Issue]]


def _direct_graph(name: str = "Direct close") -> dict[str, object]:
    return {
        "name": name,
        "initial_status": "open",
        "statuses": ["open", "closed"],
        "transitions": [
            {
                "name": "Complete",
                "from_status": "open",
                "to_status": "closed",
                "requires_resolution": True,
            },
            {
                "name": "Reopen",
                "from_status": "closed",
                "to_status": "open",
            },
        ],
    }


async def test_config_exposes_the_default_graph_and_assignments(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    response = await auth_client.get("/api/v1/queues/TRK/config")

    assert response.status_code == 200
    (workflow,) = response.json()["data"]["workflows"]
    assert workflow["name"] == "Default workflow"
    assert set(workflow["issue_types"]) == {"task", "bug", "epic"}
    assert [status["ref"] for status in workflow["statuses"]] == [
        "open",
        "in_progress",
        "closed",
    ]
    assert workflow["initial_status"] == "open"
    assert workflow["impact"] == {
        "issues_without_outgoing_transitions": 0,
        "by_status": [],
    }


async def test_templates_are_ready_starting_points(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/workflow-templates")

    assert response.status_code == 200
    assert [item["key"] for item in response.json()["data"]] == ["simple", "review"]


async def test_complete_graph_is_created_and_assigned_in_one_call(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    payload = _direct_graph()
    payload["issue_types"] = ["bug"]

    response = await auth_client.post("/api/v1/queues/TRK/workflows", json=payload)

    assert response.status_code == 201
    graph = response.json()["data"]
    assert graph["issue_types"] == ["bug"]
    assert [status["ref"] for status in graph["statuses"]] == ["open", "closed"]
    assert graph["transitions"][0]["requires_resolution"] is True

    config = (await auth_client.get("/api/v1/queues/TRK/config")).json()["data"]
    assigned = {
        issue_type: workflow["name"]
        for workflow in config["workflows"]
        for issue_type in workflow["issue_types"]
    }
    assert assigned == {
        "task": "Default workflow",
        "epic": "Default workflow",
        "bug": "Direct close",
    }


async def test_invalid_graph_returns_all_concrete_problems(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    payload = _direct_graph("Broken")
    payload["statuses"] = ["open", "in_progress", "closed"]

    response = await auth_client.post("/api/v1/queues/TRK/workflows", json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_workflow_graph"
    reasons = {problem["reason"] for problem in error["details"]["problems"]}
    assert {"unreachable_status", "dead_end"} <= reasons


async def test_graph_read_representation_can_be_saved_back_without_losing_ids(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    config = (await auth_client.get("/api/v1/queues/TRK/config")).json()["data"]
    graph = config["workflows"][0]
    transition_ids = [item["id"] for item in graph["transitions"]]
    graph["name"] = "Renamed default"

    response = await auth_client.put(
        f"/api/v1/workflows/{graph['id']}",
        json=graph,
    )

    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["name"] == "Renamed default"
    assert [item["id"] for item in saved["transitions"]] == transition_ids


async def test_available_transition_explains_missing_fields_and_executes_atomically(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
    queue: Queue,
) -> None:
    config = (await auth_client.get("/api/v1/queues/TRK/config")).json()["data"]
    workflow = config["workflows"][0]
    start = next(item for item in workflow["transitions"] if item["name"] == "Start progress")
    changed = {
        "name": start["name"],
        "from_status": start["from_status"],
        "to_status": start["to_status"],
        "required_fields": ["description"],
    }
    updated = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}/transitions/{start['id']}",
        json=changed,
    )
    assert updated.status_code == 200
    issue = await make_issue(description="")

    available = await auth_client.get(f"/api/v1/issues/{issue.key}/transitions")
    assert available.json()["data"][0]["is_available"] is False
    assert available.json()["data"][0]["missing_fields"] == ["description"]

    rejected = await auth_client.post(
        f"/api/v1/issues/{issue.key}/transitions/{start['id']}",
        json={"version": 1},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"]["missing_fields"] == ["description"]

    performed = await auth_client.post(
        f"/api/v1/issues/{issue.key}/transitions/{start['id']}",
        json={"version": 1, "description": "Причина и контекст"},
    )
    assert performed.status_code == 200
    assert performed.json()["data"]["status"] == "in_progress"
    assert performed.json()["data"]["description"] == "Причина и контекст"
    assert performed.json()["data"]["version"] == 2


async def test_close_requires_resolution_and_reopen_clears_it(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
    queue: Queue,
) -> None:
    issue = await make_issue()
    transitions = (await auth_client.get(f"/api/v1/issues/{issue.key}/transitions")).json()["data"]
    start = next(item for item in transitions if item["to_status"] == "in_progress")
    await auth_client.post(
        f"/api/v1/issues/{issue.key}/transitions/{start['id']}",
        json={"version": 1},
    )
    transitions = (await auth_client.get(f"/api/v1/issues/{issue.key}/transitions")).json()["data"]
    complete = next(item for item in transitions if item["to_status"] == "closed")
    assert complete["is_available"] is False
    assert complete["missing_fields"] == ["resolution"]

    rejected = await auth_client.post(
        f"/api/v1/issues/{issue.key}/transitions/{complete['id']}",
        json={"version": 2},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "issue_resolution_required"

    closed = await auth_client.post(
        f"/api/v1/issues/{issue.key}/transitions/{complete['id']}",
        json={"version": 2, "resolution": "done"},
    )
    assert closed.json()["data"]["status"] == "closed"
    assert closed.json()["data"]["resolution"] == "done"

    transitions = (await auth_client.get(f"/api/v1/issues/{issue.key}/transitions")).json()["data"]
    reopen = next(item for item in transitions if item["to_status"] == "open")
    reopened = await auth_client.post(
        f"/api/v1/issues/{issue.key}/transitions/{reopen['id']}",
        json={"version": 3},
    )
    assert reopened.json()["data"]["status"] == "open"
    assert reopened.json()["data"]["resolution"] is None

    history = (await auth_client.get(f"/api/v1/issues/{issue.key}/changelog")).json()["data"]
    assert history[-1]["changes"] == [
        {"field": "status", "before": "closed", "after": "open"},
        {"field": "resolution", "before": "done", "after": None},
    ]


async def test_point_editor_adds_changes_deletes_and_removes(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    created = await auth_client.post(
        "/api/v1/statuses",
        json={
            "key": "review",
            "name": "Review",
            "category": "in_progress",
            "queue": "TRK",
        },
    )
    assert created.status_code == 201
    workflow = (await auth_client.get("/api/v1/queues/TRK/config")).json()["data"]["workflows"][0]
    workflow_id = workflow["id"]

    added_status = await auth_client.post(
        f"/api/v1/workflows/{workflow_id}/statuses",
        json={
            "status": "TRK.review",
            "transitions": [
                {
                    "name": "Send to review",
                    "from_status": "in_progress",
                    "to_status": "TRK.review",
                },
                {
                    "name": "Approve",
                    "from_status": "TRK.review",
                    "to_status": "closed",
                    "requires_resolution": True,
                },
            ],
        },
    )
    assert added_status.status_code == 200
    graph = added_status.json()["data"]
    direct = next(
        item
        for item in graph["transitions"]
        if item["from_status"] == "in_progress" and item["to_status"] == "closed"
    )
    deleted = await auth_client.delete(
        f"/api/v1/workflows/{workflow_id}/transitions/{direct['id']}"
    )
    assert deleted.status_code == 200

    graph = deleted.json()["data"]
    send = next(item for item in graph["transitions"] if item["name"] == "Send to review")
    changed = await auth_client.put(
        f"/api/v1/workflows/{workflow_id}/transitions/{send['id']}",
        json={
            "name": "Request review",
            "from_status": "in_progress",
            "to_status": "TRK.review",
            "required_fields": ["description"],
        },
    )
    assert changed.status_code == 200

    restored = await auth_client.post(
        f"/api/v1/workflows/{workflow_id}/transitions",
        json={
            "name": "Complete directly",
            "from_status": "in_progress",
            "to_status": "closed",
            "requires_resolution": True,
        },
    )
    assert restored.status_code == 200
    removed = await auth_client.delete(f"/api/v1/workflows/{workflow_id}/statuses/TRK.review")
    assert removed.status_code == 200
    assert "TRK.review" not in [item["ref"] for item in removed.json()["data"]["statuses"]]


async def test_move_then_graph_edit_allows_catalog_status_deletion(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
    queue: Queue,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    in_progress = await queues_service.resolve_catalog_ref(
        db_session,
        CatalogKind.STATUS,
        "in_progress",
        initiator=owner,
    )
    await make_issue(status=in_progress)
    moved = await auth_client.post(
        "/api/v1/statuses/in_progress/move-issues",
        json={"target_status": "open"},
    )
    assert moved.json()["data"]["moved"] == 1

    workflow = (await auth_client.get("/api/v1/queues/TRK/config")).json()["data"]["workflows"][0]
    replacement = _direct_graph(workflow["name"])
    replaced = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json=replacement,
    )
    assert replaced.status_code == 200

    deleted = await auth_client.delete("/api/v1/statuses/in_progress")
    assert deleted.status_code == 204


async def test_clone_must_be_unassigned_before_delete(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    config = (await auth_client.get("/api/v1/queues/TRK/config")).json()["data"]
    default = config["workflows"][0]
    clone = await auth_client.post(
        f"/api/v1/workflows/{default['id']}/clone",
        json={"name": "Bug workflow"},
    )
    clone_id = clone.json()["data"]["id"]
    assigned = await auth_client.put(
        "/api/v1/queues/TRK/issue-types/bug/workflow",
        json={"workflow_id": clone_id},
    )
    assert assigned.status_code == 200

    rejected = await auth_client.delete(f"/api/v1/workflows/{clone_id}")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "workflow_in_use"

    await auth_client.put(
        "/api/v1/queues/TRK/issue-types/bug/workflow",
        json={"workflow_id": default["id"]},
    )
    deleted = await auth_client.delete(f"/api/v1/workflows/{clone_id}")
    assert deleted.status_code == 204


async def test_workflow_status_category_is_locked_without_issues(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    response = await auth_client.patch(
        "/api/v1/statuses/in_progress",
        json={"category": StatusCategory.NEW.value},
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "workflows_exist"

    disabled = await auth_client.patch(
        "/api/v1/statuses/in_progress",
        json={"is_active": False},
    )
    assert disabled.status_code == 409
    assert disabled.json()["error"]["details"]["reason"] == "workflows_exist"
