"""Теги: словарь заведённых меток и точечные операции над тегами задачи.

Проверяется главное свойство словаря — он собирается по задачам, а не ведётся отдельно:
тег появляется вместе с первой задачей и исчезает вместе с последней. Плюс то, ради
чего заведены точечные операции: добавление одной метки не требует присылать весь набор
и потому не затирает чужую.
"""

from httpx import AsyncClient


async def _create_issue(
    client: AsyncClient,
    summary: str,
    tags: list[str] | None = None,
) -> dict:
    payload: dict[str, object] = {"queue": "TRK", "summary": summary}
    if tags is not None:
        payload["tags"] = tags
    response = await client.post("/api/v1/issues", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_the_dictionary_is_built_from_issues_and_counts_them(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Справочника тегов нет: словарь показывает, что реально стоит на задачах."""
    await _create_issue(auth_client, "Первая", ["release", "backend"])
    await _create_issue(auth_client, "Вторая", ["release"])

    response = await auth_client.get("/api/v1/tags")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == [
        {"tag": "backend", "issues": 1},
        {"tag": "release", "issues": 2},
    ]
    assert body["meta"] == {"next_cursor": None, "has_more": False}


async def test_the_dictionary_searches_by_substring_case_insensitively(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    await _create_issue(auth_client, "Первая", ["Release", "backend"])

    response = await auth_client.get("/api/v1/tags?query=LEA")

    assert [item["tag"] for item in response.json()["data"]] == ["Release"]


async def test_a_wildcard_in_the_query_is_not_a_wildcard(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """`%` и `_` экранируются: иначе `100_percent` нашёлся бы по запросу `100x`.

    Молчаливая ошибка: подсказка отдавала бы совпадения, которых никто не просил, и
    заметить это можно было бы только на редком теге.
    """
    await _create_issue(auth_client, "Первая", ["100_percent", "release"])

    response = await auth_client.get("/api/v1/tags?query=100x")

    assert response.json()["data"] == []


async def test_the_dictionary_pages_alphabetically_with_a_cursor(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Алфавит устойчив, поэтому курсор идёт по самому тегу.

    Порядок по частоте менялся бы от каждой правки любой задачи, и страницы теряли бы
    и дублировали теги между запросами.
    """
    await _create_issue(auth_client, "Первая", ["alpha", "beta", "gamma"])

    first = await auth_client.get("/api/v1/tags?limit=2")
    body = first.json()
    assert [item["tag"] for item in body["data"]] == ["alpha", "beta"]
    assert body["meta"]["has_more"] is True

    second = await auth_client.get(f"/api/v1/tags?limit=2&cursor={body['meta']['next_cursor']}")
    rest = second.json()
    assert [item["tag"] for item in rest["data"]] == ["gamma"]
    assert rest["meta"]["has_more"] is False


async def test_a_broken_cursor_is_a_domain_error_not_a_five_hundred(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    response = await auth_client.get("/api/v1/tags?cursor=not-a-cursor")

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_the_dictionary_can_be_narrowed_to_a_queue(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    await _create_issue(auth_client, "Первая", ["release"])

    response = await auth_client.get("/api/v1/tags?queue=TRK")
    assert [item["tag"] for item in response.json()["data"]] == ["release"]

    missing = await auth_client.get("/api/v1/tags?queue=NOPE")
    assert missing.status_code == 404, missing.text


async def test_adding_a_tag_keeps_the_existing_ones(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Точечное добавление не требует присылать весь набор — и потому ничего не затирает."""
    issue = await _create_issue(auth_client, "Первая", ["release"])

    response = await auth_client.post(
        f"/api/v1/issues/{issue['key']}/tags",
        json={"tags": ["backend"]},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["tags"] == ["release", "backend"]
    assert data["version"] == issue["version"] + 1


async def test_adding_a_tag_that_differs_only_by_case_changes_nothing(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Два написания одной метки означали бы два разных фильтра."""
    issue = await _create_issue(auth_client, "Первая", ["release"])

    response = await auth_client.post(
        f"/api/v1/issues/{issue['key']}/tags",
        json={"tags": ["Release"]},
    )

    data = response.json()["data"]
    assert data["tags"] == ["release"]
    # Изменения не было — значит, и версия не выросла.
    assert data["version"] == issue["version"]


async def test_removing_a_tag_matches_case_insensitively_and_is_idempotent(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client, "Первая", ["release", "backend"])

    removed = await auth_client.delete(f"/api/v1/issues/{issue['key']}/tags/Release")
    assert removed.status_code == 204, removed.text

    again = await auth_client.delete(f"/api/v1/issues/{issue['key']}/tags/release")
    assert again.status_code == 204, again.text

    response = await auth_client.get(f"/api/v1/issues/{issue['key']}")
    assert response.json()["data"]["tags"] == ["backend"]


async def test_a_tag_disappears_from_the_dictionary_with_its_last_issue(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Тег существует ровно столько, сколько есть задача с ним."""
    issue = await _create_issue(auth_client, "Первая", ["release"])
    await auth_client.delete(f"/api/v1/issues/{issue['key']}/tags/release")

    response = await auth_client.get("/api/v1/tags")

    assert response.json()["data"] == []
