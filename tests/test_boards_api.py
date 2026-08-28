"""HTTP-слой досок и спринтов: маршруты, оболочка ответа и перевод ошибок.

Проверяется то, чего не видно из сценариев: доска собирается покомпонентно, порядок
карточек виден в выдаче колонки, а перемещение карточки отдаёт ошибку процесса, а не
пятисотку. Плюс договор поиска: `fields` работает на доске так же, как в общем поиске.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.models.saved_filter import SavedFilter
from app.domain.catalogs import CatalogKind, StatusCategory
from app.services import catalogs as catalogs_service

MakeFilter = Callable[..., Awaitable[SavedFilter]]
MakeIssue = Callable[..., Awaitable[Issue]]


@pytest.fixture
async def board_payload(make_saved_filter: MakeFilter) -> dict[str, Any]:
    saved_filter = await make_saved_filter()
    return {
        "name": "Доска команды",
        "saved_filter": str(saved_filter.id),
        "columns": [
            {"name": "Открыт", "statuses": ["open"]},
            {"name": "Работа", "statuses": ["in_progress"], "wip_limit": 2},
            {"name": "Закрыт", "statuses": ["closed"]},
        ],
    }


async def _make_status(
    session: AsyncSession,
    owner: Actor,
    queue: Queue,
    *,
    key: str,
    name: str,
) -> None:
    await catalogs_service.create_entry(
        session,
        CatalogKind.STATUS,
        initiator=owner,
        key=key,
        name=name,
        queue=queue,
        category=StatusCategory.IN_PROGRESS,
    )


async def _create_board(client: AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/v1/boards", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_a_board_is_created_with_its_columns(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
) -> None:
    board = await _create_board(auth_client, board_payload)

    assert [column["name"] for column in board["columns"]] == ["Открыт", "Работа", "Закрыт"]
    assert board["columns"][1]["wip_limit"] == 2
    assert board["columns"][0]["statuses"] == ["open"]


async def test_a_board_is_read_with_its_columns(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
) -> None:
    created = await _create_board(auth_client, board_payload)

    response = await auth_client.get(f"/api/v1/boards/{created['id']}")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == created["id"]


async def test_a_column_page_returns_only_the_requested_fields(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """`fields` на доске работает как в поиске: карточке не нужна задача целиком."""
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")
    column = board["columns"][0]["id"]

    response = await auth_client.get(
        f"/api/v1/boards/{board['id']}/columns/{column}/issues",
        params=[("fields", "summary"), ("fields", "status")],
    )

    assert response.status_code == 200
    card = response.json()["data"][0]
    assert card == {"key": issue.key, "summary": "Первая", "status": "open"}


async def test_the_backlog_shows_the_issues_outside_any_sprint(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")

    response = await auth_client.get(f"/api/v1/boards/{board['id']}/backlog")

    assert response.status_code == 200
    assert [card["key"] for card in response.json()["data"]] == [issue.key]


async def test_ranking_reorders_the_column(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """Порядок задаётся соседом, и он виден в следующей же выдаче колонки."""
    board = await _create_board(auth_client, board_payload)
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    column = board["columns"][0]["id"]

    await auth_client.put(
        f"/api/v1/boards/{board['id']}/issues/{first.key}/rank",
        json={"after": None},
    )
    moved = await auth_client.put(
        f"/api/v1/boards/{board['id']}/issues/{second.key}/rank",
        json={"after": first.key},
    )

    assert moved.status_code == 200
    page = await auth_client.get(f"/api/v1/boards/{board['id']}/columns/{column}/issues")
    assert [card["key"] for card in page.json()["data"]] == [first.key, second.key]


async def test_ranking_without_an_anchor_is_refused(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")

    response = await auth_client.put(
        f"/api/v1/boards/{board['id']}/issues/{issue.key}/rank",
        json={},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_board_move"
    assert response.json()["error"]["details"]["reason"] == "anchor_required"


async def test_moving_a_card_goes_through_the_workflow(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")

    response = await auth_client.post(
        f"/api/v1/boards/{board['id']}/issues/{issue.key}/column",
        json={"column": board["columns"][1]["id"]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "in_progress"


async def test_a_move_the_workflow_forbids_is_a_conflict_not_a_crash(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """Доска не обходит процесс: прямого перехода `open → closed` в шаблоне нет."""
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")

    response = await auth_client.post(
        f"/api/v1/boards/{board['id']}/issues/{issue.key}/column",
        json={"column": board["columns"][2]["id"]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "transition_not_allowed"


async def test_closing_a_card_from_the_board_takes_a_resolution(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """Иначе перетаскивание в «Закрыт» означало бы два запроса с промежуточным состоянием."""
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")
    await auth_client.post(
        f"/api/v1/boards/{board['id']}/issues/{issue.key}/column",
        json={"column": board["columns"][1]["id"]},
    )

    response = await auth_client.post(
        f"/api/v1/boards/{board['id']}/issues/{issue.key}/column",
        json={"column": board["columns"][2]["id"], "resolution": "done"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "closed"
    assert response.json()["data"]["resolution"] == "done"


async def test_a_column_is_added_and_removed(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board_payload: dict[str, Any],
) -> None:
    """Место новой колонки задаётся соседом; в ответе — вся доска, а не одна колонка."""
    board = await _create_board(auth_client, board_payload)
    await _make_status(db_session, owner, queue, key="review", name="Ревью")

    added = await auth_client.post(
        f"/api/v1/boards/{board['id']}/columns",
        json={"name": "Ревью", "statuses": ["TRK.review"], "after": board["columns"][0]["id"]},
    )
    assert added.status_code == 201
    assert [column["name"] for column in added.json()["data"]["columns"]] == [
        "Открыт",
        "Ревью",
        "Работа",
        "Закрыт",
    ]

    removed = await auth_client.delete(
        f"/api/v1/boards/{board['id']}/columns/{board['columns'][2]['id']}"
    )
    assert removed.status_code == 204

    left = await auth_client.get(f"/api/v1/boards/{board['id']}")
    assert [column["name"] for column in left.json()["data"]["columns"]] == [
        "Открыт",
        "Ревью",
        "Работа",
    ]


async def test_a_column_without_statuses_is_refused_by_the_schema(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
) -> None:
    """Пустой набор в фильтре означает «не фильтровать», то есть все задачи доски."""
    board = await _create_board(auth_client, board_payload)

    response = await auth_client.post(
        f"/api/v1/boards/{board['id']}/columns",
        json={"name": "Пустая", "statuses": []},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Спринты -----------------------------------------------------------------------


async def test_the_sprint_lifecycle_runs_through_the_api(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """Планирование, запуск, состав и завершение с переносом — одним сценарием."""
    board = await _create_board(auth_client, board_payload)
    issue = await make_issue(summary="Первая")

    planned = await auth_client.post(
        "/api/v1/sprints",
        json={"board": board["id"], "name": "Спринт 1", "goal": "Закрыть выдачу ключей"},
    )
    assert planned.status_code == 201
    sprint = planned.json()["data"]
    assert sprint["state"] == "planned"

    following = await auth_client.post(
        "/api/v1/sprints",
        json={"board": board["id"], "name": "Спринт 2"},
    )
    assert following.status_code == 201

    taken = await auth_client.post(
        f"/api/v1/sprints/{sprint['id']}/issues",
        json={"issues": [issue.key]},
    )
    assert taken.status_code == 200

    started = await auth_client.post(f"/api/v1/sprints/{sprint['id']}/start")
    assert started.status_code == 200
    assert started.json()["data"]["state"] == "active"

    completed = await auth_client.post(
        f"/api/v1/sprints/{sprint['id']}/complete",
        json={"unfinished": "sprint", "sprint": following.json()["data"]["id"]},
    )
    assert completed.status_code == 200
    body = completed.json()["data"]
    assert body["sprint"]["state"] == "completed"
    assert body["moved"] == [issue.key]
    assert body["target"] == following.json()["data"]["id"]


async def test_the_sprint_issue_list_is_a_search_with_a_glued_condition(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """Язык запросов работает, но за пределы спринта не выводит."""
    board = await _create_board(auth_client, board_payload)
    taken = await make_issue(summary="Взята")
    await make_issue(summary="Осталась в бэклоге")
    sprint = (
        await auth_client.post(
            "/api/v1/sprints",
            json={"board": board["id"], "name": "Спринт 1"},
        )
    ).json()["data"]
    await auth_client.post(
        f"/api/v1/sprints/{sprint['id']}/issues",
        json={"issues": [taken.key]},
    )

    everything = await auth_client.get(f"/api/v1/sprints/{sprint['id']}/issues")
    widened = await auth_client.get(
        f"/api/v1/sprints/{sprint['id']}/issues",
        params={"query": "queue: TRK"},
    )

    assert [card["key"] for card in everything.json()["data"]] == [taken.key]
    assert [card["key"] for card in widened.json()["data"]] == [taken.key]


async def test_the_current_sprint_is_addressable_by_word(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """`sprint: current` — самый частый вопрос доски, и он работает и в общем поиске."""
    board = await _create_board(auth_client, board_payload)
    taken = await make_issue(summary="Взята")
    await make_issue(summary="Осталась в бэклоге")
    sprint = (
        await auth_client.post(
            "/api/v1/sprints",
            json={"board": board["id"], "name": "Спринт 1"},
        )
    ).json()["data"]
    await auth_client.post(
        f"/api/v1/sprints/{sprint['id']}/issues",
        json={"issues": [taken.key]},
    )
    await auth_client.post(f"/api/v1/sprints/{sprint['id']}/start")

    response = await auth_client.get(
        "/api/v1/search/issues",
        params={"query": "sprint: current"},
    )

    assert response.status_code == 200
    assert [card["key"] for card in response.json()["data"]] == [taken.key]


async def test_the_backlog_is_addressable_as_an_empty_sprint(
    auth_client: AsyncClient,
    queue: Queue,
    board_payload: dict[str, Any],
    make_issue: MakeIssue,
) -> None:
    """`sprint: empty()` и есть бэклог: второго способа сказать «значения нет» нет."""
    board = await _create_board(auth_client, board_payload)
    taken = await make_issue(summary="Взята")
    left = await make_issue(summary="Осталась")
    sprint = (
        await auth_client.post(
            "/api/v1/sprints",
            json={"board": board["id"], "name": "Спринт 1"},
        )
    ).json()["data"]
    await auth_client.post(
        f"/api/v1/sprints/{sprint['id']}/issues",
        json={"issues": [taken.key]},
    )

    response = await auth_client.get(
        "/api/v1/search/issues",
        params={"query": "sprint: empty()"},
    )

    assert [card["key"] for card in response.json()["data"]] == [left.key]


async def test_a_sprint_filter_by_a_bad_reference_names_itself(
    auth_client: AsyncClient,
    queue: Queue,
) -> None:
    """Отказ называет, что ожидалось: агент иначе уходит в слепой перебор."""
    response = await auth_client.get(
        "/api/v1/search/issues",
        params={"query": "sprint: nosuchthing"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["reason"] == "invalid_sprint_ref"
