"""Эндпоинты портфелей: вложенность, состав одним списком, агрегированный прогресс."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _portfolio(client: AsyncClient, **payload: object) -> dict:
    body = {"key": "platform", "name": "Платформа", **payload}
    response = await client.post("/api/v1/portfolios", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _project(client: AsyncClient, **payload: object) -> dict:
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


# --- Карточка и вложенность ----------------------------------------------------------


async def test_a_created_portfolio_reports_an_empty_composition(auth_client: AsyncClient) -> None:
    data = await _portfolio(auth_client)

    assert data["key"] == "platform"
    assert (data["projects_count"], data["portfolios_count"]) == (0, 0)
    assert data["progress"]["ratio"] is None


async def test_a_portfolio_counts_only_its_direct_children(auth_client: AsyncClient) -> None:
    """«Что лежит здесь» и «что под этим вообще» — разные вопросы, и счётчики про первый."""
    await _portfolio(auth_client, key="platform")
    await _portfolio(auth_client, key="core", name="Ядро", portfolio="platform")
    await _project(auth_client, key="alpha", portfolio="platform")
    await _project(auth_client, key="beta", name="Ядро", portfolio="core")

    response = await auth_client.get("/api/v1/portfolios/platform")

    data = response.json()["data"]
    assert (data["projects_count"], data["portfolios_count"]) == (1, 1)


async def test_a_nested_portfolio_reads_its_parent(auth_client: AsyncClient) -> None:
    """Регрессия: карточка вложенного портфеля обязана открываться.

    Ловушка была в стратегии загрузки самоссылки: `selectin` у связи «многие к одному»
    на ту же таблицу молча не срабатывает, атрибут остаётся ленивым, и сборка ответа
    падает `MissingGreenlet` — в живом запросе и только у портфеля, **у которого есть
    родитель**. Тесты этого не видели, потому что читали корневой портфель.
    """
    await _portfolio(auth_client, key="platform")
    await _portfolio(auth_client, key="core", name="Ядро", portfolio="platform")

    response = await auth_client.get("/api/v1/portfolios/core")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["portfolio"] == "platform"


async def test_a_nested_portfolio_shows_up_in_the_list(auth_client: AsyncClient) -> None:
    """Та же ловушка на странице списка: там объекты грузятся другим запросом."""
    await _portfolio(auth_client, key="platform")
    await _portfolio(auth_client, key="core", name="Ядро", portfolio="platform")

    response = await auth_client.get("/api/v1/portfolios")

    assert response.status_code == 200, response.text
    parents = {item["key"]: item["portfolio"] for item in response.json()["data"]}
    assert parents == {"platform": None, "core": "platform"}


async def test_nesting_a_portfolio_into_itself_is_a_conflict(auth_client: AsyncClient) -> None:
    await _portfolio(auth_client)

    response = await auth_client.put(
        "/api/v1/portfolios/platform/parent", json={"portfolio": "platform"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "portfolio_cycle_detected"


async def test_a_cycle_of_three_is_a_conflict_too(auth_client: AsyncClient) -> None:
    """Проверка «только прямой родитель» выглядела бы работающей и пропустила бы это."""
    await _portfolio(auth_client, key="one", name="Один")
    await _portfolio(auth_client, key="two", name="Два", portfolio="one")
    await _portfolio(auth_client, key="three", name="Три", portfolio="two")

    response = await auth_client.put("/api/v1/portfolios/one/parent", json={"portfolio": "three"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "portfolio_cycle_detected"


async def test_an_archived_portfolio_accepts_no_content(auth_client: AsyncClient) -> None:
    await _portfolio(auth_client)
    await _project(auth_client)
    await auth_client.post("/api/v1/portfolios/platform/archive")

    response = await auth_client.put(
        "/api/v1/projects/alpha/portfolio", json={"portfolio": "platform"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "portfolio_archived"


# --- Состав --------------------------------------------------------------------------


async def test_the_content_mixes_projects_and_portfolios_in_one_list(
    auth_client: AsyncClient,
) -> None:
    """Одна коллекция под `data`, вид позиции — в поле `kind`.

    Две коллекции в одном ответе нарушили бы оболочку, а две страницы, склеенные в
    памяти, сломали бы курсор.
    """
    await _portfolio(auth_client, key="platform")
    await _portfolio(auth_client, key="core", name="Ядро", portfolio="platform")
    await _project(auth_client, key="alpha", portfolio="platform")
    await _project(auth_client, key="beta", name="Витрина")

    response = await auth_client.get("/api/v1/portfolios/platform/content")

    body = response.json()
    assert {(item["kind"], item["key"]) for item in body["data"]} == {
        ("portfolio", "core"),
        ("project", "alpha"),
    }
    assert body["meta"]["has_more"] is False


async def test_the_content_pages_with_a_cursor(auth_client: AsyncClient) -> None:
    """Проверяется полнота страниц, а не порядок: у объектов одного теста одно `created_at`."""
    await _portfolio(auth_client, key="platform")
    for index in range(3):
        await _portfolio(
            auth_client, key=f"nested{index}", name=f"Вложенный {index}", portfolio="platform"
        )
        await _project(
            auth_client, key=f"project{index}", name=f"Проект {index}", portfolio="platform"
        )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = await auth_client.get("/api/v1/portfolios/platform/content", params=params)
        body = page.json()
        seen.extend(item["key"] for item in body["data"])
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted(
        [f"nested{index}" for index in range(3)] + [f"project{index}" for index in range(3)]
    )


# --- Прогресс ------------------------------------------------------------------------


async def test_the_portfolio_progress_sums_issues_of_all_descendants(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
) -> None:
    """Три задачи под портфелем, две закрыты — две трети, а не среднее от двух проектов.

    Среднее дало бы 0,75: проект с одной закрытой задачей весил бы столько же, сколько
    проект с двумя. Прогресс портфеля отвечает на вопрос «сколько работы сделано».
    """
    await _portfolio(auth_client, key="platform")
    await _portfolio(auth_client, key="core", name="Ядро", portfolio="platform")
    await _project(auth_client, key="alpha", portfolio="platform")
    await _project(auth_client, key="beta", name="Ядро", portfolio="core")

    open_issue = await make_issue()
    first_done = await _close(db_session, owner, make_issue)
    second_done = await _close(db_session, owner, make_issue)
    await auth_client.post(
        "/api/v1/projects/alpha/issues", json={"issues": [open_issue.key, first_done.key]}
    )
    await auth_client.post("/api/v1/projects/beta/issues", json={"issues": [second_done.key]})

    response = await auth_client.get("/api/v1/portfolios/platform")

    progress = response.json()["data"]["progress"]
    assert (progress["total"], progress["done"]) == (3, 2)
    assert round(progress["ratio"], 4) == round(2 / 3, 4)


async def test_every_content_entry_carries_its_own_progress(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: MakeIssue,
) -> None:
    """У вложенного портфеля прогресс агрегированный, у проекта — по его собственным задачам."""
    await _portfolio(auth_client, key="platform")
    await _portfolio(auth_client, key="core", name="Ядро", portfolio="platform")
    await _project(auth_client, key="alpha", portfolio="platform")
    await _project(auth_client, key="beta", name="Ядро", portfolio="core")

    await auth_client.post(
        "/api/v1/projects/alpha/issues", json={"issues": [(await make_issue()).key]}
    )
    await auth_client.post(
        "/api/v1/projects/beta/issues",
        json={"issues": [(await _close(db_session, owner, make_issue)).key]},
    )

    response = await auth_client.get("/api/v1/portfolios/platform/content")

    by_key = {item["key"]: item["progress"] for item in response.json()["data"]}
    assert by_key["alpha"] == {"total": 1, "done": 0, "ratio": 0.0}
    assert by_key["core"] == {"total": 1, "done": 1, "ratio": 1.0}
