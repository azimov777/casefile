"""HTTP-слой досок: маршруты, оболочка ответа и перевод ошибок.

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
