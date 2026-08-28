"""Эндпоинты проектов: карточка, состав, прогресс, перенос, архив.

Smoke-уровень плюс два места, которые сами по себе нетривиальны: список задач проекта
(он обязан быть настоящим поиском, а не урезанной копией) и оболочка ответа.
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _create(client: AsyncClient, **payload: object) -> dict:
    body = {"key": "alpha", "name": "Платформа доставки", **payload}
    response = await client.post("/api/v1/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _close(session: AsyncSession, owner: Actor, make_issue: MakeIssue) -> Issue:
    closed = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, "closed", initiator=owner
    )
    done = await queues_service.resolve_catalog_ref(
        session, CatalogKind.RESOLUTION, "done", initiator=owner
    )
    return await make_issue(status=closed, resolution=done)


# --- Карточка ------------------------------------------------------------------------


async def test_a_created_project_comes_back_in_the_data_envelope(
    auth_client: AsyncClient,
    owner: Actor,
) -> None:
    """Оболочка одна на весь API: ресурс под `data`, ничего голого."""
    data = await _create(auth_client, description="Сборка результата из трёх очередей")

    assert data["key"] == "alpha"
    assert data["lead"] == owner.key
    assert data["status"] == "not_started"
    assert data["portfolio"] is None
    assert data["progress"] == {"total": 0, "done": 0, "ratio": None}


async def test_a_project_is_addressed_softly(auth_client: AsyncClient) -> None:
    """Адресация мягкая: `/projects/Alpha` находит `alpha`, как у очередей и статусов."""
    await _create(auth_client)

    response = await auth_client.get("/api/v1/projects/Alpha")

    assert response.status_code == 200
    assert response.json()["data"]["key"] == "alpha"


async def test_an_unknown_project_answers_with_a_stable_code(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/projects/nosuch")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


async def test_a_bad_key_is_refused_by_the_schema(auth_client: AsyncClient) -> None:
    """Ключ придумывают при создании, поэтому шаблон стоит именно здесь.

    У параметра пути шаблона нет: там адресация мягкая, и отказ приходит из домена
    с объяснением в `details`.
    """
    response = await auth_client.post(
        "/api/v1/projects", json={"key": "Alpha-One", "name": "Платформа"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_a_partial_update_touches_only_what_was_sent(auth_client: AsyncClient) -> None:
    await _create(auth_client, description="Было")

    response = await auth_client.patch(
        "/api/v1/projects/alpha",
        json={"status": "in_progress", "start_date": "2026-01-01"},
    )

    data = response.json()["data"]
    assert (data["status"], data["start_date"], data["description"]) == (
        "in_progress",
        "2026-01-01",
        "Было",
    )


async def test_an_inverted_period_names_the_field(auth_client: AsyncClient) -> None:
    await _create(auth_client, start_date="2026-03-01")

    response = await auth_client.patch("/api/v1/projects/alpha", json={"end_date": "2026-01-01"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_project"
    assert response.json()["error"]["details"]["field"] == "end_date"


# --- Состав и прогресс ---------------------------------------------------------------


async def test_issues_are_added_and_the_progress_follows(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
) -> None:
    """Прогресс приезжает в самой карточке: он считается по запросу, а не хранится."""
    await _create(auth_client)
    open_issue = await make_issue()
    closed_issue = await _close(db_session, owner, make_issue)

    response = await auth_client.post(
        "/api/v1/projects/alpha/issues",
        json={"issues": [open_issue.key, closed_issue.key]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["progress"] == {"total": 2, "done": 1, "ratio": 0.5}


async def test_an_issue_carries_its_project_in_its_own_card(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    """Проект — поле задачи, поэтому виден в её ответе, а не только в списке проекта."""
    await _create(auth_client)
    issue = await make_issue()
    await auth_client.post("/api/v1/projects/alpha/issues", json={"issues": [issue.key]})

    response = await auth_client.get(f"/api/v1/issues/{issue.key}")

    assert response.json()["data"]["project"] == "alpha"


async def test_an_issue_is_removed_from_the_project_but_keeps_living(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    await _create(auth_client)
    issue = await make_issue()
    await auth_client.post("/api/v1/projects/alpha/issues", json={"issues": [issue.key]})

    removed = await auth_client.delete(f"/api/v1/projects/alpha/issues/{issue.key}")

    assert removed.status_code == 204
    card = await auth_client.get(f"/api/v1/issues/{issue.key}")
    assert card.status_code == 200
    assert card.json()["data"]["project"] is None


async def test_removing_an_issue_of_another_project_explains_itself(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    await _create(auth_client, key="alpha")
    await _create(auth_client, key="beta", name="Витрина")
    issue = await make_issue()
    await auth_client.post("/api/v1/projects/alpha/issues", json={"issues": [issue.key]})

    response = await auth_client.delete(f"/api/v1/projects/beta/issues/{issue.key}")

    assert response.status_code == 404
    assert response.json()["error"]["details"]["reason"] == "issue_not_in_project"


async def test_an_archived_project_refuses_new_issues(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    await _create(auth_client)
    issue = await make_issue()
    archived = await auth_client.post("/api/v1/projects/alpha/archive")
    assert archived.json()["data"]["is_archived"] is True

    response = await auth_client.post("/api/v1/projects/alpha/issues", json={"issues": [issue.key]})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_archived"

    restored = await auth_client.post("/api/v1/projects/alpha/unarchive")
    assert restored.json()["data"]["is_archived"] is False


# --- Список задач проекта ------------------------------------------------------------


async def test_the_issue_list_is_the_search_with_the_project_glued_in(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
) -> None:
    """В проекте работают язык запросов и выбор полей — ровно как в общем поиске.

    Своего набора фильтров у проекта нет намеренно: он разошёлся бы с поиском на первом
    же краевом случае, и разошёлся бы молча — разной выдачей на одинаковый по смыслу
    вопрос.
    """
    await _create(auth_client)
    open_issue = await make_issue(summary="Открытая")
    closed_issue = await _close(db_session, owner, make_issue)
    await auth_client.post(
        "/api/v1/projects/alpha/issues",
        json={"issues": [open_issue.key, closed_issue.key]},
    )

    response = await auth_client.get(
        "/api/v1/projects/alpha/issues",
        params={"query": "status_category: done", "fields": ["key", "status"]},
    )

    body = response.json()
    assert [item["key"] for item in body["data"]] == [closed_issue.key]
    # Непрошенное поле не приезжает ни как `null`, ни как значение по умолчанию.
    assert set(body["data"][0]) == {"key", "status"}


async def test_the_issue_list_cannot_be_widened_beyond_the_project(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    """Условие проекта склеивается по `and`: сузить можно, выйти наружу — нет."""
    await _create(auth_client, key="alpha")
    await _create(auth_client, key="beta", name="Витрина")
    mine = await make_issue()
    foreign = await make_issue()
    await auth_client.post("/api/v1/projects/alpha/issues", json={"issues": [mine.key]})
    await auth_client.post("/api/v1/projects/beta/issues", json={"issues": [foreign.key]})

    response = await auth_client.get(
        "/api/v1/projects/alpha/issues", params={"query": "project: beta"}
    )

    assert response.json()["data"] == []


async def test_the_search_finds_issues_by_project_key(
    auth_client: AsyncClient,
    make_issue: MakeIssue,
) -> None:
    """Требование задачи 12, закрытое здесь: `project: alpha` больше не отвечает «ещё нет»."""
    await _create(auth_client)
    inside = await make_issue()
    outside = await make_issue()
    await auth_client.post("/api/v1/projects/alpha/issues", json={"issues": [inside.key]})

    found = await auth_client.get("/api/v1/search/issues", params={"query": "project: alpha"})
    orphans = await auth_client.get("/api/v1/search/issues", params={"query": "project: empty()"})

    assert [item["key"] for item in found.json()["data"]] == [inside.key]
    assert [item["key"] for item in orphans.json()["data"]] == [outside.key]


async def test_a_filter_by_an_unknown_project_is_a_bad_value_not_a_404(
    auth_client: AsyncClient,
) -> None:
    """Для поиска ненайденный проект — неверное значение фильтра, а не отсутствующий ресурс.

    `404` на поиске сбивал бы клиента с толку: сам маршрут существует и отработал.
    """
    response = await auth_client.get("/api/v1/search/issues", params={"query": "project: nosuch"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "search_value_invalid"
    assert response.json()["error"]["details"]["reason"] == "project_not_found"


# --- Перенос -------------------------------------------------------------------------


async def test_a_project_moves_between_portfolios_and_back_to_the_top(
    auth_client: AsyncClient,
) -> None:
    await auth_client.post("/api/v1/portfolios", json={"key": "platform", "name": "Платформа"})
    await _create(auth_client)

    moved = await auth_client.put(
        "/api/v1/projects/alpha/portfolio", json={"portfolio": "platform"}
    )
    assert moved.json()["data"]["portfolio"] == "platform"

    detached = await auth_client.put("/api/v1/projects/alpha/portfolio", json={"portfolio": None})
    assert detached.json()["data"]["portfolio"] is None


async def test_the_list_filters_by_portfolio_and_archive(auth_client: AsyncClient) -> None:
    await auth_client.post("/api/v1/portfolios", json={"key": "platform", "name": "Платформа"})
    await _create(auth_client, key="alpha", portfolio="platform")
    await _create(auth_client, key="beta", name="Витрина")
    await auth_client.post("/api/v1/projects/beta/archive")

    inside = await auth_client.get("/api/v1/projects", params={"portfolio": "platform"})
    alive = await auth_client.get("/api/v1/projects", params={"is_archived": False})

    assert [item["key"] for item in inside.json()["data"]] == ["alpha"]
    assert [item["key"] for item in alive.json()["data"]] == ["alpha"]
