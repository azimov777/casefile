"""Сохранённые фильтры: цикл жизни, единственный источник отбора, запуск из поиска.

Главное здесь — два свойства. Описание проверяется при сохранении, поэтому опечатка в
имени поля становится ошибкой сразу, а не пустой выдачей в правиле автоматики через
неделю. И функции вычисляются при выполнении, поэтому один фильтр «мои задачи»
работает у каждого, кто его запускает.
"""

from httpx import AsyncClient


async def _create_issue(client: AsyncClient, **payload: object) -> dict:
    response = await client.post("/api/v1/issues", json={"queue": "TRK", **payload})
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _create_filter(client: AsyncClient, **payload: object) -> dict:
    response = await client.post("/api/v1/filters", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_a_query_filter_is_created_and_read_back(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    saved = await _create_filter(
        auth_client,
        name="Мои открытые",
        query="assignee: me() and status: open",
        sort=["-deadline"],
    )

    assert saved["owner"] == "owner"
    assert saved["query"] == "assignee: me() and status: open"
    assert saved["filter"] is None
    assert saved["sort"] == ["-deadline"]

    response = await auth_client.get(f"/api/v1/filters/{saved['id']}")
    assert response.json()["data"] == saved


async def test_a_structured_filter_is_stored_in_its_canonical_form(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """В колонке лежат ровно те условия, которые выполняются, — их и показывает ответ."""
    saved = await _create_filter(
        auth_client,
        name="Релизные",
        filter=[{"field": "tags", "values": ["release"]}],
    )

    assert saved["query"] is None
    assert saved["filter"] == [{"field": "tags", "operator": "=", "values": ["release"]}]


async def test_a_filter_needs_exactly_one_source(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Два описания одного отбора немедленно порождают вопрос, какое из них главное."""
    both = await auth_client.post(
        "/api/v1/filters",
        json={
            "name": "Двойной",
            "query": "tags: release",
            "filter": [{"field": "tags", "values": ["release"]}],
        },
    )
    neither = await auth_client.post("/api/v1/filters", json={"name": "Ничего"})

    assert both.status_code == 422, both.text
    assert both.json()["error"]["code"] == "invalid_saved_filter"
    assert neither.status_code == 422, neither.text


async def test_a_broken_filter_is_refused_at_save_time(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Иначе опечатка всплыла бы пустой выдачей в правиле автоматики, где логов не читают."""
    parse_error = await auth_client.post(
        "/api/v1/filters", json={"name": "Кривой", "query": "queue TRK"}
    )
    unknown_field = await auth_client.post(
        "/api/v1/filters", json={"name": "Неизвестное поле", "query": "nosuchfield: 1"}
    )

    assert parse_error.status_code == 422
    assert parse_error.json()["error"]["code"] == "invalid_search_query"
    assert unknown_field.status_code == 422
    assert unknown_field.json()["error"]["code"] == "search_field_unknown"


async def test_the_name_is_unique_per_owner(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    await _create_filter(auth_client, name="Мои", query="assignee: me()")

    response = await auth_client.post(
        "/api/v1/filters", json={"name": "Мои", "query": "status: open"}
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "saved_filter_name_taken"


async def test_updating_the_source_replaces_it_whole(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Передали условия — строка снята: держать оба описания сразу нельзя."""
    saved = await _create_filter(auth_client, name="Мои", query="assignee: me()")

    response = await auth_client.patch(
        f"/api/v1/filters/{saved['id']}",
        json={"filter": [{"field": "tags", "values": ["release"]}]},
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["query"] is None
    assert body["filter"] == [{"field": "tags", "operator": "=", "values": ["release"]}]


async def test_a_saved_filter_runs_from_the_search_endpoint(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Запуск — параметр поиска, а не отдельный маршрут: иначе у него не было бы `fields`."""
    await _create_issue(auth_client, summary="Релизная", tags=["release"])
    await _create_issue(auth_client, summary="Обычная")
    saved = await _create_filter(auth_client, name="Релизные", query="tags: release")

    response = await auth_client.get(
        "/api/v1/search/issues",
        params={"saved_filter": saved["id"], "fields": ["summary"]},
    )

    assert [item["summary"] for item in response.json()["data"]] == ["Релизная"]


async def test_a_saved_filter_narrows_further_with_a_query(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Источники складываются по `and`, поэтому «доска плюс условие» — обычный запрос."""
    await _create_issue(auth_client, summary="Релизная", tags=["release", "backend"])
    await _create_issue(auth_client, summary="Другая релизная", tags=["release"])
    saved = await _create_filter(auth_client, name="Релизные", query="tags: release")

    response = await auth_client.get(
        "/api/v1/search/issues",
        params={"saved_filter": saved["id"], "query": "tags: backend", "fields": ["summary"]},
    )

    assert [item["summary"] for item in response.json()["data"]] == ["Релизная"]


async def test_me_is_evaluated_when_the_filter_runs(
    auth_client: AsyncClient,
    client: AsyncClient,
    db_session: object,
    queue: object,
) -> None:
    """Ради этого фильтр и хранится текстом: `me()` означает «мои» для каждого."""
    await _create_issue(auth_client, summary="Моя", assignee="owner")
    saved = await _create_filter(auth_client, name="Мои", query="assignee: me()")

    agent = await auth_client.post(
        "/api/v1/actors",
        json={"type": "agent", "key": "release_bot", "display_name": "Релизный бот"},
    )
    assert agent.status_code == 201, agent.text
    token = await auth_client.post("/api/v1/actors/release_bot/tokens", json={"name": "ci"})
    secret = token.json()["data"]["secret"]

    client.headers["Authorization"] = f"Bearer {secret}"
    response = await client.get("/api/v1/search/issues", params={"saved_filter": saved["id"]})

    assert response.json()["data"] == []


async def test_a_filter_is_deleted(auth_client: AsyncClient, queue: object) -> None:
    saved = await _create_filter(auth_client, name="Мои", query="assignee: me()")

    deleted = await auth_client.delete(f"/api/v1/filters/{saved['id']}")
    missing = await auth_client.get(f"/api/v1/filters/{saved['id']}")

    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "saved_filter_not_found"
