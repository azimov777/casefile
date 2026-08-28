"""Эндпоинты поиска: оболочка ответа, выбор полей, сортировка, устойчивая пагинация.

Пагинация проверяется на равных значениях ключа сортировки — именно там она и ломается:
все задачи одного теста живут в одной транзакции и получают одинаковый `created_at`
(`docs/notes/testing.md`), поэтому порядок держится только на уникальном тайбрейкере.
Тест проверяет полноту и отсутствие пересечений, а не конкретный порядок ключей.
"""

from httpx import AsyncClient


async def _create_issue(client: AsyncClient, **payload: object) -> dict:
    body = {"queue": "TRK", **payload}
    response = await client.post("/api/v1/issues", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_the_query_endpoint_returns_the_standard_envelope(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    await _create_issue(auth_client, summary="Первая", tags=["release"])
    await _create_issue(auth_client, summary="Вторая")

    response = await auth_client.get("/api/v1/search/issues", params={"query": "tags: release"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["summary"] for item in body["data"]] == ["Первая"]
    assert body["meta"] == {"next_cursor": None, "has_more": False}


async def test_the_structured_endpoint_matches_the_query_endpoint(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Одинаковые по смыслу фильтр и строка обязаны давать идентичный результат."""
    await _create_issue(auth_client, summary="Первая", tags=["release"])
    await _create_issue(auth_client, summary="Вторая", tags=["backend"])

    by_query = await auth_client.get(
        "/api/v1/search/issues", params={"query": "queue: TRK and tags: release"}
    )
    by_filter = await auth_client.post(
        "/api/v1/search/issues",
        json={"filter": {"queue": ["TRK"], "tags": ["release"]}},
    )

    assert by_query.json()["data"] == by_filter.json()["data"]


async def test_selected_fields_are_the_only_ones_returned(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Полная задача на сто позиций съедает контекст агента — выбор полей это чинит."""
    await _create_issue(auth_client, summary="Первая", description="Длинное описание")

    response = await auth_client.get(
        "/api/v1/search/issues", params={"fields": ["summary", "status"]}
    )

    assert set(response.json()["data"][0]) == {"key", "summary", "status"}


async def test_a_custom_field_reference_selects_only_that_value(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    await auth_client.post(
        "/api/v1/fields",
        json={
            "key": "severity",
            "name": "Критичность",
            "value_type": "enum",
            "queue": "TRK",
            "options": [{"key": "critical", "name": "Критическая"}],
        },
    )
    await auth_client.post(
        "/api/v1/fields",
        json={"key": "component", "name": "Компонент", "value_type": "string", "queue": "TRK"},
    )
    await _create_issue(
        auth_client,
        summary="Первая",
        values={"TRK.severity": "critical", "TRK.component": "api"},
    )

    response = await auth_client.get("/api/v1/search/issues", params={"fields": ["TRK.severity"]})

    item = response.json()["data"][0]
    assert set(item) == {"key", "values"}
    assert item["values"] == {"TRK.severity": "critical"}


async def test_a_parse_error_carries_the_position(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Агент исправляет запрос по этому ответу; «invalid query» отправил бы его в перебор."""
    response = await auth_client.get("/api/v1/search/issues", params={"query": "queue TRK"})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_search_query"
    assert error["details"]["position"] == 6
    assert error["details"]["reason"] == "expected_colon"


async def test_sorting_descending_puts_the_latest_deadline_first(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    await _create_issue(auth_client, summary="Раньше", deadline="2026-01-01T00:00:00+00:00")
    await _create_issue(auth_client, summary="Позже", deadline="2026-06-01T00:00:00+00:00")
    await _create_issue(auth_client, summary="Без дедлайна")

    response = await auth_client.get(
        "/api/v1/search/issues", params={"sort": ["-deadline"], "fields": ["summary"]}
    )

    # Пустые значения стоят последними при любом направлении: `NULLS LAST` задан явно,
    # иначе задача без дедлайна возглавила бы список «самых горящих».
    assert [item["summary"] for item in response.json()["data"]] == [
        "Позже",
        "Раньше",
        "Без дедлайна",
    ]


async def test_paging_is_stable_when_the_sort_key_repeats(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Задачи одной транзакции получают один `created_at` — порядок держит тайбрейкер.

    Без него страницы теряли бы и дублировали задачи, и тест был бы зелёным примерно
    в половине запусков.
    """
    expected = set()
    for index in range(5):
        expected.add((await _create_issue(auth_client, summary=f"Задача {index}"))["key"])

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, object] = {"limit": 2, "fields": ["key"]}
        if cursor is not None:
            params["cursor"] = cursor
        page = (await auth_client.get("/api/v1/search/issues", params=params)).json()
        seen.extend(item["key"] for item in page["data"])
        cursor = page["meta"]["next_cursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted(expected)
    assert len(seen) == len(set(seen))


async def test_paging_survives_issues_created_between_pages(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Курсор не смещается от вставок: задача, добавленная между страницами, ничего не рушит.

    Ради этого пагинация и курсорная, а не по смещению: `OFFSET` после вставки сдвинул
    бы окно, и одна из уже показанных задач приехала бы второй раз, а одна непоказанная
    исчезла бы совсем. Проверяется отсутствие дублей и полнота исходного набора —
    место новой задачи в порядке не определено, потому что время создания у всех
    задач теста одинаково.
    """
    original = {
        (await _create_issue(auth_client, summary=f"Задача {index}"))["key"] for index in range(4)
    }

    first = (
        await auth_client.get("/api/v1/search/issues", params={"limit": 2, "fields": ["key"]})
    ).json()
    seen = [item["key"] for item in first["data"]]

    # Вставка между страницами — тот самый случай, ради которого курсор и заведён.
    await _create_issue(auth_client, summary="Появилась между страницами")

    cursor = first["meta"]["next_cursor"]
    while cursor is not None:
        page = (
            await auth_client.get(
                "/api/v1/search/issues",
                params={"limit": 2, "fields": ["key"], "cursor": cursor},
            )
        ).json()
        seen.extend(item["key"] for item in page["data"])
        cursor = page["meta"]["next_cursor"]

    assert len(seen) == len(set(seen)), "задача попала в выдачу дважды"
    assert original <= set(seen), "задача выпала между страницами"


async def test_a_cursor_from_another_sort_is_refused(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Смена порядка посреди обхода — не повод молча начать сначала."""
    for index in range(3):
        await _create_issue(auth_client, summary=f"Задача {index}")
    first = (await auth_client.get("/api/v1/search/issues", params={"limit": 1})).json()["meta"][
        "next_cursor"
    ]

    response = await auth_client.get(
        "/api/v1/search/issues",
        params={"limit": 1, "cursor": first, "sort": ["-deadline", "summary"]},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_sorting_by_an_unsortable_field_lists_the_allowed_ones(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    response = await auth_client.get("/api/v1/search/issues", params={"sort": ["status"]})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "search_field_unknown"
    assert error["details"]["reason"] == "not_sortable"
    assert "deadline" in error["details"]["allowed"]


async def test_search_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/search/issues")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
