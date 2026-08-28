"""Эндпоинты чеклиста: оболочка ответа, отметка, перестановка, отказы.

Отдельно проверяется, что позиции наружу не выходят: клиенту отдаётся порядок, а не
координата на разреженной шкале, и перемещение задаётся соседом.
"""

from httpx import AsyncClient


async def _create_issue(client: AsyncClient, summary: str = "Починить выдачу ключей") -> str:
    response = await client.post("/api/v1/issues", json={"queue": "TRK", "summary": summary})
    assert response.status_code == 201, response.text
    return response.json()["data"]["key"]


async def _add(client: AsyncClient, issue: str, text: str, **extra: object) -> dict:
    response = await client.post(
        f"/api/v1/issues/{issue}/checklist",
        json={"text": text, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _texts(client: AsyncClient, issue: str) -> list[str]:
    response = await client.get(f"/api/v1/issues/{issue}/checklist")
    assert response.status_code == 200, response.text
    return [item["text"] for item in response.json()["data"]]


async def test_an_item_comes_back_wrapped_and_without_its_position(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Позиция — внутреннее число шкалы, наружу отдаётся только порядок."""
    issue = await _create_issue(auth_client)

    created = await _add(auth_client, issue, "Прогнать тесты")

    assert created["issue"] == issue
    assert created["is_done"] is False
    assert created["checked_by"] is None
    assert "position" not in created

    response = await auth_client.get(f"/api/v1/issues/{issue}/checklist")
    body = response.json()
    assert body["meta"] == {"next_cursor": None, "has_more": False}
    assert [item["id"] for item in body["data"]] == [created["id"]]


async def test_checking_an_item_records_who_did_it(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client)
    created = await _add(auth_client, issue, "Прогнать тесты")

    response = await auth_client.put(
        f"/api/v1/issues/{issue}/checklist/{created['id']}/done",
        json={"is_done": True},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_done"] is True
    assert data["checked_by"] == "owner"
    assert data["checked_at"] is not None


async def test_unchecking_clears_the_mark_completely(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client)
    created = await _add(auth_client, issue, "Пункт")
    await auth_client.put(
        f"/api/v1/issues/{issue}/checklist/{created['id']}/done",
        json={"is_done": True},
    )

    response = await auth_client.put(
        f"/api/v1/issues/{issue}/checklist/{created['id']}/done",
        json={"is_done": False},
    )

    data = response.json()["data"]
    assert data["is_done"] is False
    assert data["checked_by"] is None
    assert data["checked_at"] is None


async def test_moving_an_item_answers_with_the_whole_list(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Клиент попросил изменить порядок — ему и отдаётся порядок целиком.

    По одному пункту результат не проверить: позиции наружу не отдаются.
    """
    issue = await _create_issue(auth_client)
    first = await _add(auth_client, issue, "Первый")
    await _add(auth_client, issue, "Второй")
    third = await _add(auth_client, issue, "Третий")

    response = await auth_client.put(
        f"/api/v1/issues/{issue}/checklist/{third['id']}/position",
        json={"after": first["id"]},
    )

    assert response.status_code == 200, response.text
    assert [item["text"] for item in response.json()["data"]] == ["Первый", "Третий", "Второй"]


async def test_moving_to_the_top_takes_a_null_neighbour(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client)
    await _add(auth_client, issue, "Первый")
    second = await _add(auth_client, issue, "Второй")

    response = await auth_client.put(
        f"/api/v1/issues/{issue}/checklist/{second['id']}/position",
        json={"after": None},
    )

    assert [item["text"] for item in response.json()["data"]] == ["Второй", "Первый"]


async def test_updating_applies_only_the_given_fields(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Переданный `null` очищает поле, отсутствующий ключ не трогает его."""
    issue = await _create_issue(auth_client)
    created = await _add(auth_client, issue, "Пункт", assignee="owner")
    assert created["assignee"] == "owner"

    response = await auth_client.patch(
        f"/api/v1/issues/{issue}/checklist/{created['id']}",
        json={"assignee": None},
    )

    data = response.json()["data"]
    assert data["assignee"] is None
    assert data["text"] == "Пункт"


async def test_a_multiline_item_is_refused_with_a_domain_code(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Правило домена, а не схемы: тот же отказ получит MCP, идущий мимо FastAPI."""
    issue = await _create_issue(auth_client)

    response = await auth_client.post(
        f"/api/v1/issues/{issue}/checklist",
        json={"text": "Прогнать тесты\nи собрать релиз"},
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_checklist_item"
    assert error["details"]["reason"] == "multiline_not_allowed"


async def test_removing_an_item_takes_it_out_of_the_list(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    issue = await _create_issue(auth_client)
    created = await _add(auth_client, issue, "Пункт")

    response = await auth_client.delete(f"/api/v1/issues/{issue}/checklist/{created['id']}")

    assert response.status_code == 204, response.text
    assert await _texts(auth_client, issue) == []


async def test_an_item_of_another_issue_answers_not_found(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    first = await _create_issue(auth_client, "Первая")
    second = await _create_issue(auth_client, "Вторая")
    created = await _add(auth_client, first, "Пункт")

    response = await auth_client.delete(f"/api/v1/issues/{second}/checklist/{created['id']}")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "checklist_item_not_found"
