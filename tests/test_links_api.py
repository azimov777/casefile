"""Эндпоинты связей и дерева подзадач.

Проверяется контракт: единая оболочка ответа, связь видна с обеих сторон под разными
именами, доменные отказы приезжают своими кодами, дерево ограничено глубиной и честно
сообщает об обрезке.

Дерево отдаётся как одиночный ресурс, а не как коллекция, и это намеренно: курсор
посреди поддерева не имел бы смысла ни для клиента, ни для базы.
"""

from httpx import AsyncClient

from app.domain.links import DEFAULT_TREE_DEPTH, MAX_TREE_DEPTH, LinkType


async def _create_issue(client: AsyncClient, summary: str, issue_type: str | None = None) -> str:
    payload: dict[str, object] = {"queue": "TRK", "summary": summary}
    if issue_type is not None:
        payload["issue_type"] = issue_type
    response = await client.post("/api/v1/issues", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["key"]


async def _link(client: AsyncClient, issue: str, link_type: LinkType, other: str) -> dict:
    response = await client.post(
        f"/api/v1/issues/{issue}/links",
        json={"type": link_type.value, "issue": other},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_a_link_comes_back_wrapped_and_named_from_the_asking_side(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Оболочка `data`, полная запись второй задачи, имя связи — со стороны спросившего."""
    blocker = await _create_issue(auth_client, "Починить выдачу ключей")
    blocked = await _create_issue(auth_client, "Выпустить релиз")

    created = await _link(auth_client, blocked, LinkType.DEPENDS_ON, blocker)

    assert created["type"] == LinkType.DEPENDS_ON
    assert created["issue"]["key"] == blocker.upper()
    assert created["issue"]["summary"] == "Починить выдачу ключей"
    assert created["author"] == "owner"

    response = await auth_client.get(f"/api/v1/issues/{blocker}/links")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"] == {"next_cursor": None, "has_more": False}
    assert len(body["data"]) == 1
    # Та же строка, вторая сторона — обратное имя. Второй записи в базе нет.
    assert body["data"][0]["type"] == LinkType.BLOCKS
    assert body["data"][0]["issue"]["key"] == blocked
    assert body["data"][0]["id"] == created["id"]


async def test_the_same_link_from_the_other_side_is_a_conflict(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Повтор не проходит молча: тихий успех скрыл бы ошибку в стороне или типе."""
    first = await _create_issue(auth_client, "Первая")
    second = await _create_issue(auth_client, "Вторая")
    await _link(auth_client, second, LinkType.DEPENDS_ON, first)

    response = await auth_client.post(
        f"/api/v1/issues/{first}/links",
        json={"type": LinkType.BLOCKS.value, "issue": second},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "link_already_exists"


async def test_linking_an_issue_to_itself_is_rejected(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    key = await _create_issue(auth_client, "Одинокая")

    response = await auth_client.post(
        f"/api/v1/issues/{key}/links",
        json={"type": LinkType.RELATES.value, "issue": key},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "link_self_reference"


async def test_a_second_parent_is_refused(auth_client: AsyncClient, queue: object) -> None:
    child = await _create_issue(auth_client, "Подзадача")
    parent = await _create_issue(auth_client, "Родитель")
    other = await _create_issue(auth_client, "Другой родитель")
    await _link(auth_client, child, LinkType.SUBTASK_OF, parent)

    response = await auth_client.post(
        f"/api/v1/issues/{child}/links",
        json={"type": LinkType.SUBTASK_OF.value, "issue": other},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "link_parent_exists"


async def test_a_cycle_is_refused_with_its_own_code(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    top = await _create_issue(auth_client, "Верхняя задача")
    middle = await _create_issue(auth_client, "Средняя задача")
    bottom = await _create_issue(auth_client, "Нижняя задача")
    await _link(auth_client, middle, LinkType.SUBTASK_OF, top)
    await _link(auth_client, bottom, LinkType.SUBTASK_OF, middle)

    response = await auth_client.post(
        f"/api/v1/issues/{top}/links",
        json={"type": LinkType.SUBTASK_OF.value, "issue": bottom},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "link_cycle_detected"


async def test_an_epic_cannot_be_given_a_parent(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Эпик — это тип задачи, и родителя у него не бывает."""
    epic = await _create_issue(auth_client, "Эпик", issue_type="epic")
    task = await _create_issue(auth_client, "Задача")

    response = await auth_client.post(
        f"/api/v1/issues/{epic}/links",
        json={"type": LinkType.SUBTASK_OF.value, "issue": task},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "epic_cannot_have_parent"


async def test_an_unknown_issue_on_either_side_is_a_domain_404(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    key = await _create_issue(auth_client, "Единственная")

    response = await auth_client.post(
        f"/api/v1/issues/{key}/links",
        json={"type": LinkType.RELATES.value, "issue": "TRK-999"},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "issue_not_found"


async def test_a_link_is_removed_from_both_sides_at_once(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Удаление одной строки убирает связь у обеих задач — второй записи нет."""
    first = await _create_issue(auth_client, "Первая")
    second = await _create_issue(auth_client, "Вторая")
    created = await _link(auth_client, first, LinkType.RELATES, second)

    response = await auth_client.delete(f"/api/v1/issues/{first}/links/{created['id']}")

    assert response.status_code == 204, response.text
    assert response.content == b""
    for key in (first, second):
        body = (await auth_client.get(f"/api/v1/issues/{key}/links")).json()
        assert body["data"] == []


async def test_a_link_of_another_pair_is_not_reachable_through_this_issue(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    first = await _create_issue(auth_client, "Первая")
    second = await _create_issue(auth_client, "Вторая")
    outsider = await _create_issue(auth_client, "Посторонняя")
    created = await _link(auth_client, first, LinkType.RELATES, second)

    response = await auth_client.delete(f"/api/v1/issues/{outsider}/links/{created['id']}")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "link_not_found"


async def test_the_changelog_of_both_issues_mentions_the_link(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """История ведётся по задаче, поэтому запись получают обе стороны."""
    blocked = await _create_issue(auth_client, "Выпустить релиз")
    blocker = await _create_issue(auth_client, "Починить выдачу ключей")
    await _link(auth_client, blocked, LinkType.DEPENDS_ON, blocker)

    blocked_history = (await auth_client.get(f"/api/v1/issues/{blocked}/changelog")).json()
    blocker_history = (await auth_client.get(f"/api/v1/issues/{blocker}/changelog")).json()

    assert blocked_history["data"][-1]["event_type"] == "link.created"
    assert blocked_history["data"][-1]["changes"][0]["after"] == {
        "type": LinkType.DEPENDS_ON.value,
        "issue": blocker,
    }
    assert blocker_history["data"][-1]["changes"][0]["after"] == {
        "type": LinkType.BLOCKS.value,
        "issue": blocked,
    }


# --- Дерево -----------------------------------------------------------------------


async def test_the_tree_is_a_single_resource_limited_by_depth(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Дерево приезжает в `data` одним объектом и обрывается там, где кончилась глубина."""
    root = await _create_issue(auth_client, "Корень")
    first = await _create_issue(auth_client, "Первый уровень")
    second = await _create_issue(auth_client, "Второй уровень")
    await _link(auth_client, first, LinkType.SUBTASK_OF, root)
    await _link(auth_client, second, LinkType.SUBTASK_OF, first)

    response = await auth_client.get(f"/api/v1/issues/{root}/tree", params={"depth": 1})

    assert response.status_code == 200, response.text
    body = response.json()
    assert "meta" not in body
    node = body["data"]
    assert node["issue"]["key"] == root
    assert [child["issue"]["key"] for child in node["children"]] == [first]
    # Обрезка не молчаливая: клиент видит, что под узлом ещё что-то есть.
    assert node["children"][0]["children"] == []
    assert node["children"][0]["has_more_children"] is True


async def test_the_tree_reaches_deeper_when_asked(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    root = await _create_issue(auth_client, "Корень")
    first = await _create_issue(auth_client, "Первый уровень")
    second = await _create_issue(auth_client, "Второй уровень")
    await _link(auth_client, first, LinkType.SUBTASK_OF, root)
    await _link(auth_client, second, LinkType.SUBTASK_OF, first)

    body = (
        await auth_client.get(f"/api/v1/issues/{root}/tree", params={"depth": DEFAULT_TREE_DEPTH})
    ).json()

    grandchild = body["data"]["children"][0]["children"][0]
    assert grandchild["issue"]["key"] == second
    assert grandchild["has_more_children"] is False


async def test_a_depth_beyond_the_ceiling_is_refused(
    auth_client: AsyncClient,
    queue: object,
) -> None:
    """Границы объявлены в параметре запроса, поэтому мусор отсекается на входе."""
    key = await _create_issue(auth_client, "Корень")

    response = await auth_client.get(
        f"/api/v1/issues/{key}/tree",
        params={"depth": MAX_TREE_DEPTH + 1},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
