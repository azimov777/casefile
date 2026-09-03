"""Эндпоинты связей: обзорные проверки задачи 24 через HTTP.

Проверки идут так, как их пройдёт агент: поставить связь, упереться в отказ, закрыть
блокер, пройти. Отдельного маршрута чтения связей нет — они приезжают в карточке.
"""

from typing import Any

from httpx import AsyncClient

from app.db.models.queue import Queue

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

SUMMARY = {
    "done": "разобрался",
    "remaining": "дописать",
    "blockers": "нет",
    "next_step": "дописать тест",
}


async def create(client: AsyncClient, title: str) -> str:
    response = await client.post("/api/v1/tasks", json={**READY, "title": title})
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["key"])


async def move(client: AsyncClient, key: str, to: str, **body: Any) -> Any:
    return await client.post(f"/api/v1/tasks/{key}/transition", json={"to": to, **body})


async def close(client: AsyncClient, key: str) -> None:
    """Проводит задачу до `done`, подшивая сводку и вердикт по каждой проверке."""
    assert (await move(client, key, "open")).status_code == 200
    assert (await move(client, key, "in_progress")).status_code == 200
    await client.post(f"/api/v1/tasks/{key}/entries", json={"type": "summary", "payload": SUMMARY})
    assert (await move(client, key, "review")).status_code == 200
    for check_no in range(1, len(READY["checks"]) + 1):
        await client.post(
            f"/api/v1/tasks/{key}/entries",
            json={"type": "verdict", "payload": {"check_no": check_no, "outcome": "passed"}},
        )
    assert (await move(client, key, "done")).status_code == 200, key


async def link(client: AsyncClient, key: str, kind: str, other: str) -> Any:
    return await client.post(f"/api/v1/tasks/{key}/links", json={"kind": kind, "other": other})


async def card(client: AsyncClient, key: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/tasks/{key}")
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def links_of(client: AsyncClient, key: str) -> list[tuple[str, str]]:
    """Связи из карточки: вид со стороны этой задачи и ключ задачи на другой стороне."""
    return [(item["kind"], item["other"]["key"]) for item in (await card(client, key))["links"]]


# --- Постановка и снятие ----------------------------------------------------------------


async def test_a_link_shows_up_on_both_cards_under_its_own_kind(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорные проверки 5 и 7: имена с обеих сторон и статус задачи на другой стороне."""
    first = await create(auth_client, "первая")
    second = await create(auth_client, "вторая")

    created = await link(auth_client, first, "blocks", second)
    assert created.status_code == 201, created.text
    assert created.json()["data"]["kind"] == "blocks"
    assert created.json()["data"]["other"]["key"] == second
    assert created.json()["data"]["other"]["status"] == "backlog"

    assert await links_of(auth_client, first) == [("blocks", second)]
    assert await links_of(auth_client, second) == [("blocked_by", first)]


async def test_a_link_is_removed_from_either_side(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    first = await create(auth_client, "первая")
    second = await create(auth_client, "вторая")
    assert (await link(auth_client, first, "blocks", second)).status_code == 201

    removed = await auth_client.delete(f"/api/v1/tasks/{second}/links/blocked_by/{first}")

    assert removed.status_code == 204
    assert removed.content == b""
    assert await links_of(auth_client, first) == []


async def test_removing_a_link_that_is_not_there_answers_404(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    first = await create(auth_client, "первая")
    second = await create(auth_client, "вторая")

    response = await auth_client.delete(f"/api/v1/tasks/{first}/links/relates/{second}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "link_not_found"


# --- Отказы -----------------------------------------------------------------------------


async def test_a_cycle_is_refused_in_the_hierarchy_and_in_blocking(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорная проверка 3: кольцо из двух в иерархии и из трёх в блокировках."""
    first = await create(auth_client, "первая")
    second = await create(auth_client, "вторая")
    third = await create(auth_client, "третья")
    assert (await link(auth_client, first, "parent", second)).status_code == 201

    hierarchy = await link(auth_client, second, "parent", first)
    assert hierarchy.status_code == 409
    assert hierarchy.json()["error"]["code"] == "link_cycle_detected"

    assert (await link(auth_client, first, "blocks", second)).status_code == 201
    assert (await link(auth_client, second, "blocks", third)).status_code == 201
    blocking = await link(auth_client, third, "blocks", first)

    assert blocking.status_code == 409
    assert blocking.json()["error"]["code"] == "link_cycle_detected"


async def test_a_self_link_is_refused(auth_client: AsyncClient, queue: Queue) -> None:
    first = await create(auth_client, "первая")

    response = await link(auth_client, first, "relates", first)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "link_self_not_allowed"


async def test_a_closed_task_does_not_take_new_links(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорная проверка 6."""
    closed = await create(auth_client, "закрытая")
    other = await create(auth_client, "живая")
    await close(auth_client, closed)

    response = await link(auth_client, closed, "relates", other)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "task_closed"


async def test_an_unknown_kind_never_reaches_the_service(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Вид связи — перечисление в схеме, поэтому промах ловится схемой запроса."""
    first = await create(auth_client, "первая")
    second = await create(auth_client, "вторая")

    response = await link(auth_client, first, "duplicates", second)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Валидации переходов ----------------------------------------------------------------


async def test_a_blocker_keeps_the_task_out_of_work_until_it_closes(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорная проверка 1: отказ со списком блокеров, после закрытия блокера — проход."""
    blocker = await create(auth_client, "блокер")
    blocked = await create(auth_client, "заблокированная")
    assert (await link(auth_client, blocker, "blocks", blocked)).status_code == 201
    assert (await move(auth_client, blocked, "open")).status_code == 200

    refused = await move(auth_client, blocked, "in_progress")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "task_blocked"
    assert refused.json()["error"]["details"]["blockers"] == [blocker]
    assert (await card(auth_client, blocked))["features"]["blocked"] is True

    await close(auth_client, blocker)

    assert (await card(auth_client, blocked))["features"]["blocked"] is False
    assert (await move(auth_client, blocked, "in_progress")).status_code == 200


async def test_a_parent_does_not_close_while_a_child_is_open(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорная проверка 2: отказ со списком детей, после отмены ребёнка — проход."""
    parent = await create(auth_client, "родитель")
    child = await create(auth_client, "ребёнок")
    # Со стороны ребёнка: «этот — ребёнок того». Та же строка, что и `parent` с другой
    # стороны, — и заодно проверка, что перевёрнутое направление доходит до базы верным.
    assert (await link(auth_client, child, "child", parent)).status_code == 201
    assert (await move(auth_client, child, "open")).status_code == 200

    assert (await move(auth_client, parent, "open")).status_code == 200
    assert (await move(auth_client, parent, "in_progress")).status_code == 200
    await auth_client.post(
        f"/api/v1/tasks/{parent}/entries", json={"type": "summary", "payload": SUMMARY}
    )
    assert (await move(auth_client, parent, "review")).status_code == 200
    await auth_client.post(
        f"/api/v1/tasks/{parent}/entries",
        json={"type": "verdict", "payload": {"check_no": 1, "outcome": "passed"}},
    )

    refused = await move(auth_client, parent, "done")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "task_has_unclosed_children"
    assert refused.json()["error"]["details"]["children"] == [child]

    assert (await move(auth_client, child, "cancelled", reason="не понадобился")).status_code == 200
    assert (await move(auth_client, parent, "done")).status_code == 200


# --- Записи о связях --------------------------------------------------------------------


async def test_the_link_entry_is_read_back_by_its_own_variant(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Обзорные проверки 4 и 4a: записи в обоих делах и чтение их вариантом `LinkEntryRead`."""
    first = await create(auth_client, "первая")
    second = await create(auth_client, "вторая")
    assert (await link(auth_client, first, "blocks", second)).status_code == 201

    response = await auth_client.get(
        f"/api/v1/tasks/{first}/entries", params={"types": ["link_added"]}
    )
    assert response.status_code == 200, response.text
    (added,) = response.json()["data"]
    assert added["type"] == "link_added"
    assert added["payload"] == {"kind": "blocks", "other": second}
    assert added["title"] == f"Link added: blocks {second}"

    other_side = await auth_client.get(
        f"/api/v1/tasks/{second}/entries", params={"types": ["link_added"]}
    )
    assert other_side.json()["data"][0]["payload"] == {"kind": "blocked_by", "other": first}

    await auth_client.delete(f"/api/v1/tasks/{first}/links/blocks/{second}")

    for key, kind, other in ((first, "blocks", second), (second, "blocked_by", first)):
        removed = await auth_client.get(
            f"/api/v1/tasks/{key}/entries", params={"types": ["link_removed"]}
        )
        assert removed.json()["data"][0]["payload"] == {"kind": kind, "other": other}
