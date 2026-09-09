"""Эндпоинты задач: обзорные проверки задачи 22 через HTTP."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from httpx import AsyncClient

from app.db.models.queue import Queue
from app.db.models.task import Task

READY = {
    "queue": "trk",
    "title": "Починить выдачу ключей",
    "description": "Ключ сгорает на неудачном запросе",
    "goal": "Ключи не сгорают",
    "context": "Номер выдаёт очередь",
    "constraints": "Счётчик не переписывать",
    "output": "Тест на несгоревший номер",
    "checks": ["Создание задачи без названия не тратит номер"],
}


async def create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/tasks", json={**READY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


SUMMARY = {
    "done": "Разобрался",
    "remaining": "Дописать",
    "blockers": "нет",
    "next_step": "Дописать проверку",
}


async def summary(client: AsyncClient, key: str) -> dict[str, Any]:
    """Сводка ради перехода: без неё из `in_progress` не выйти (задача 23)."""
    response = await client.post(
        f"/api/v1/tasks/{key}/entries",
        json={"type": "summary", "payload": SUMMARY},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def move(client: AsyncClient, key: str, *statuses: str, reason: str | None = None) -> None:
    """Проводит задачу по цепочке, подшивая то, без чего переход не пройдёт.

    Сводка перед выходом из `in_progress` и вердикты перед `done` — правила перехода,
    а не предмет здешних тестов: без них до `done` не добраться вовсе. Сами правила
    проверяются в `tests/test_case_api.py`. В `done` ведёт закрытие, а не переход, и
    сводку с вердиктами оно подшивает само.
    """
    for status in statuses:
        current = (await client.get(f"/api/v1/tasks/{key}")).json()["data"]["task"]
        if status == "done":
            closed = await client.post(
                f"/api/v1/tasks/{key}/close",
                json={
                    "summary": SUMMARY,
                    "verdicts": [
                        {"check_no": check_no, "outcome": "passed"}
                        for check_no in range(1, len(current["checks"]) + 1)
                    ],
                },
            )
            assert closed.status_code == 200, closed.text
            continue
        if current["status"] == "in_progress":
            await summary(client, key)
        response = await client.post(
            f"/api/v1/tasks/{key}/transition", json={"to": status, "reason": reason}
        )
        assert response.status_code == 200, response.text


async def case(client: AsyncClient, key: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/tasks/{key}/entries", params={"limit": 200})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_creation_answers_with_backlog_and_a_created_entry(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 1."""
    data = await create(auth_client)

    assert data["key"] == "TRK-1"
    assert data["status"] == "backlog"
    assert data["version"] == 1
    assert data["queue"] == {"key": "TRK", "title": "Трекер"}
    assert data["created_by"] == {"kind": "human", "signature": "owner"}

    package = (await auth_client.get("/api/v1/tasks/trk-1")).json()["data"]
    assert sorted(package) == [
        "features",
        "index",
        "links",
        "questions",
        "remarks",
        "summary",
        "task",
        "transitions",
    ]
    assert package["links"] == []
    assert package["task"]["key"] == "TRK-1"
    assert package["transitions"] == ["open", "waiting", "cancelled"]
    assert package["summary"] is None
    assert package["questions"] == []
    assert package["features"] == {
        "blocked": False,
        "open_questions": 0,
        "open_blocking_questions": 0,
        "open_remarks": 0,
        "last_summary_at": None,
        # В деле только служебная `created`: записей агента ещё нет, признак пуст.
        "last_entry_at": None,
    }
    assert len(package["index"]) == 1
    heading = package["index"][0]
    assert sorted(heading) == ["author", "created_at", "facts", "no", "title", "type"]
    assert heading["no"] == 1
    assert heading["type"] == "created"
    # У заведения называть строкой нечего, кроме самого типа: форма фактов пуста, и в
    # ответе от неё остаётся одна разметка — ни одного ключа «на всякий случай».
    assert heading["facts"] == {"type": "created"}
    assert heading["author"] == {"kind": "human", "signature": "owner"}


async def test_a_status_at_creation_is_rejected(auth_client: AsyncClient, queue: Queue) -> None:
    response = await auth_client.post("/api/v1/tasks", json={**READY, "status": "open"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_opening_without_checks_lists_the_unfilled_sections(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 2."""
    await create(auth_client, checks=[], output="")

    response = await auth_client.post("/api/v1/tasks/TRK-1/transition", json={"to": "open"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "task_sections_incomplete"
    assert error["details"]["fields"] == ["output", "checks"]


async def test_a_move_outside_the_table_is_a_conflict_with_the_allowed_list(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 3."""
    await create(auth_client)
    await move(auth_client, "TRK-1", "open")

    response = await auth_client.post("/api/v1/tasks/TRK-1/transition", json={"to": "done"})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "transition_not_allowed"
    assert error["details"]["allowed"] == ["in_progress", "waiting", "backlog", "cancelled"]


async def test_a_step_back_needs_a_reason_that_lands_in_the_case(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 4."""
    await create(auth_client)
    await move(auth_client, "TRK-1", "open", "in_progress")
    # Сводка — отдельным шагом: без неё выход из `in_progress` упёрся бы в неё, а
    # проверяется здесь именно причина, и порядок проверок не должен это скрывать.
    await summary(auth_client, "TRK-1")

    refused = await auth_client.post("/api/v1/tasks/TRK-1/transition", json={"to": "open"})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "transition_reason_required"

    passed = await auth_client.post(
        "/api/v1/tasks/TRK-1/transition", json={"to": "open", "reason": "Жду ответа"}
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()["data"]["status"] == "open"

    last = (await case(auth_client, "TRK-1"))[-1]
    assert last["type"] == "status_changed"
    assert last["payload"] == {"from": "in_progress", "to": "open", "reason": "Жду ответа"}
    assert last["task_key"] == "TRK-1"
    assert last["author"] == {"kind": "human", "signature": "owner"}


async def test_sections_are_locked_outside_backlog(auth_client: AsyncClient, queue: Queue) -> None:
    """Обзорная проверка 5."""
    await create(auth_client)

    changed = await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": "Новая цель"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["goal"] == "Новая цель"
    assert changed.json()["data"]["version"] == 2
    last = (await case(auth_client, "TRK-1"))[-1]
    assert last["type"] == "section_changed"
    # `check_no` пуст у всякой правки, кроме точечной правки проверки: в хранимой
    # нагрузке его тогда нет вовсе, а в ответе он приезжает `null` — пустые поля в
    # ответе едут вместе с остальными, иначе клиент теряет схему (`docs/notes/api.md`).
    assert last["payload"] == {
        "field": "goal",
        "before": "Ключи не сгорают",
        "after": "Новая цель",
        "check_no": None,
    }

    await move(auth_client, "TRK-1", "open")
    refused = await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": "Ещё"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "task_field_locked"
    assert refused.json()["error"]["details"]["fields"] == ["goal"]


async def test_the_assignee_changes_in_progress_but_not_in_done(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 6."""
    await create(auth_client)
    await move(auth_client, "TRK-1", "open", "in_progress")

    changed = await auth_client.patch("/api/v1/tasks/TRK-1", json={"assignee": "release_bot"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["assignee"] == "release_bot"
    last = (await case(auth_client, "TRK-1"))[-1]
    assert last["type"] == "assignee_changed"
    assert last["payload"] == {"before": None, "after": "release_bot"}

    await move(auth_client, "TRK-1", "done")
    refused = await auth_client.patch("/api/v1/tasks/TRK-1", json={"assignee": None})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "task_closed"


async def test_null_unassigns_and_an_omitted_field_stays(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await create(auth_client, assignee="release_bot", priority="high")

    response = await auth_client.patch("/api/v1/tasks/TRK-1", json={"assignee": None})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["assignee"] is None
    assert data["priority"] == "high", "an omitted field must stay as it was"


async def test_a_stale_version_is_a_version_conflict(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 7."""
    await create(auth_client)
    await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": "x"})

    response = await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": "y", "version": 1})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"] == {"key": "TRK-1", "expected": 1, "actual": 2}


async def test_the_status_cannot_be_patched(auth_client: AsyncClient, queue: Queue) -> None:
    await create(auth_client)

    response = await auth_client.patch("/api/v1/tasks/TRK-1", json={"status": "open"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_seq_is_monotonic_across_queues_and_no_restarts_per_task(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 8."""
    created = await auth_client.post("/api/v1/queues", json={"key": "OPS", "title": "Эксплуатация"})
    assert created.status_code == 201, created.text
    await create(auth_client)
    await create(auth_client, queue="ops", title="Дежурство")
    await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": "a"})
    await auth_client.patch("/api/v1/tasks/OPS-1", json={"goal": "b"})
    await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": "c"})

    first = await case(auth_client, "TRK-1")
    second = await case(auth_client, "OPS-1")

    assert [entry["no"] for entry in first] == [1, 2, 3]
    assert [entry["no"] for entry in second] == [1, 2]
    everything = sorted(first + second, key=lambda entry: entry["seq"])
    seqs = [entry["seq"] for entry in everything]
    assert seqs == sorted(set(seqs)), "seq must be strictly increasing"
    assert [(entry["task_key"], entry["no"]) for entry in everything] == [
        ("TRK-1", 1),
        ("OPS-1", 1),
        ("TRK-1", 2),
        ("OPS-1", 2),
        ("TRK-1", 3),
    ]


def test_entries_have_no_patch_or_delete_routes(app: FastAPI) -> None:
    """Обзорная проверка 9: неизменяемость видна в схеме, а не только в коде."""
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    entry_paths = {path: methods for path, methods in schema["paths"].items() if "entries" in path}

    assert entry_paths, "the entries route must exist"
    for path, methods in entry_paths.items():
        assert not {"patch", "delete", "put"} & set(methods), f"{path}: {sorted(methods)}"


async def test_a_removed_field_is_refused_and_not_silently_dropped(
    auth_client: AsyncClient, queue: Queue, task: Task
) -> None:
    """Метки сняты (`CONCEPT.md`, 6), и запрос с ними обязан отказать, а не промолчать.

    Тихое игнорирование — худший исход снятия поля: агент, писавший `tags`, получил бы
    `201` и был бы уверен, что метка сохранена. `extra="forbid"` в схемах превращает это
    в отказ с именем поля.
    """
    created = await auth_client.post("/api/v1/tasks", json={**READY, "tags": ["release"]})
    updated = await auth_client.patch(f"/api/v1/tasks/{task.key}", json={"tags": ["release"]})

    for response in (created, updated):
        assert response.status_code == 422, response.text
        problem = response.json()["error"]
        assert problem["code"] == "validation_error"
        assert [item["loc"] for item in problem["details"]["errors"]] == [["body", "tags"]]
        assert problem["details"]["errors"][0]["type"] == "extra_forbidden"


async def test_an_unknown_key_and_a_malformed_key_answer_differently(
    auth_client: AsyncClient, queue: Queue
) -> None:
    missing = await auth_client.get("/api/v1/tasks/TRK-99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "task_not_found"

    malformed = await auth_client.get("/api/v1/tasks/TRK-007")
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_task_key"


async def test_the_task_scope_runs_the_cycle(
    client: AsyncClient, task_secret: str, queue: Queue, task: Task
) -> None:
    """Рабочий цикл агента открыт набору `task`."""
    client.headers["Authorization"] = f"Bearer {task_secret}"

    changed = await client.patch(f"/api/v1/tasks/{task.key}", json={"priority": "high"})
    assert changed.status_code == 200, changed.text
    await move(client, task.key, "open", "in_progress")

    package = (await client.get(f"/api/v1/tasks/{task.key}")).json()["data"]
    assert package["task"]["status"] == "in_progress"
    assert package["transitions"] == ["done", "waiting", "open", "backlog", "cancelled"]


async def test_entries_are_paged_by_number(auth_client: AsyncClient, queue: Queue) -> None:
    await create(auth_client)
    for goal in ("a", "b", "c"):
        await auth_client.patch("/api/v1/tasks/TRK-1", json={"goal": goal})

    first = await auth_client.get("/api/v1/tasks/TRK-1/entries", params={"limit": 3})
    assert first.status_code == 200
    payload = first.json()
    assert [entry["no"] for entry in payload["data"]] == [1, 2, 3]
    assert payload["meta"]["has_more"] is True

    second = await auth_client.get(
        "/api/v1/tasks/TRK-1/entries",
        params={"limit": 3, "cursor": payload["meta"]["next_cursor"]},
    )
    assert [entry["no"] for entry in second.json()["data"]] == [4]
    assert second.json()["meta"] == {"next_cursor": None, "has_more": False}
