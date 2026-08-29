"""Агрегирующие эндпоинты: одно обращение вместо пяти.

Главное, что здесь проверяется, — агрегат отдаёт **то же самое**, что отдали бы
отдельные эндпоинты. Ради этого почти каждая проверка сравнивает ответ агрегата с
ответом соответствующего маршрута, а не с ожиданиями, выписанными руками: ожидания,
выписанные руками, разъезжаются с обоими сразу и молча.

Второе — что агрегат не завёл своей пагинации: коллекция внутри отдаётся первой
страницей и курсором того эндпоинта, который её листает.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.services import demo as demo_service


def _data(response: Any) -> Any:
    assert response.status_code == 200, f"{response.request.url}: {response.text}"
    return response.json()["data"]


async def test_the_card_repeats_what_the_separate_endpoints_answer(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Карточка — это ровно пять ответов, сложенных вместе, и ничего больше."""
    await demo_service.seed_demo(db_session, owner=owner)

    card = _data(await auth_client.get("/api/v1/issues/TRK-2/card"))

    assert card["issue"] == _data(await auth_client.get("/api/v1/issues/TRK-2"))
    assert card["transitions"] == _data(await auth_client.get("/api/v1/issues/TRK-2/transitions"))
    assert card["links"] == _data(await auth_client.get("/api/v1/issues/TRK-2/links"))
    assert card["comments"] == _data(await auth_client.get("/api/v1/issues/TRK-2/comments"))
    assert card["checklist"] == _data(await auth_client.get("/api/v1/issues/TRK-2/checklist"))


async def test_the_card_hands_pagination_over_instead_of_inventing_its_own(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Курсор карточки — это курсор ленты комментариев, и он там работает.

    Проверка именно такая, потому что сломаться может ровно это: свой курсор, похожий
    на чужой, отдал бы вторую страницу не от того места, и заметно это стало бы уже во
    фронтенде — пропущенной репликой посреди обсуждения.
    """
    await demo_service.seed_demo(db_session, owner=owner)

    card = _data(await auth_client.get("/api/v1/issues/TRK-2/card", params={"limit": 1}))
    assert len(card["comments"]) == 1
    assert card["comments_next_cursor"] is not None

    rest = await auth_client.get(
        "/api/v1/issues/TRK-2/comments",
        params={"cursor": card["comments_next_cursor"]},
    )
    remaining = _data(rest)
    seen = [comment["id"] for comment in card["comments"]] + [
        comment["id"] for comment in remaining
    ]
    whole = [
        comment["id"] for comment in _data(await auth_client.get("/api/v1/issues/TRK-2/comments"))
    ]
    assert seen == whole


async def test_the_card_shows_a_transition_together_with_what_it_still_needs(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Недоступный переход приезжает с причиной: интерфейс объясняет отказ заранее."""
    await demo_service.seed_demo(db_session, owner=owner)

    card = _data(await auth_client.get("/api/v1/issues/TRK-2/card"))
    complete = next(item for item in card["transitions"] if item["name"] == "Complete")

    assert not complete["is_available"]
    assert complete["missing_fields"] == ["resolution"]


async def test_bootstrap_carries_the_actor_the_queues_and_the_unread_count(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Стартовые данные повторяют ответы своих эндпоинтов, а не пересобирают их."""
    await demo_service.seed_demo(db_session, owner=owner)

    bootstrap = _data(await auth_client.get("/api/v1/bootstrap"))

    assert bootstrap["actor"] == _data(await auth_client.get("/api/v1/actors/me"))
    # Множеством, а не списком: обе очереди созданы одной транзакцией, поэтому
    # `created_at` у них совпадает и порядок вырождается в порядок случайных UUID
    # (docs/notes/testing.md).
    assert {queue["key"] for queue in bootstrap["queues"]} == {"TRK", "OPS"}
    assert bootstrap["statuses"] == _data(await auth_client.get("/api/v1/statuses"))
    assert bootstrap["issue_types"] == _data(await auth_client.get("/api/v1/issue-types"))
    assert bootstrap["resolutions"] == _data(await auth_client.get("/api/v1/resolutions"))
    assert bootstrap["unread_notifications"] == 0


async def test_bootstrap_leaves_out_archived_queues_and_queue_local_entries(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Стартовому экрану нужны навигация и общие справочники, а не всё, что есть.

    Локальные записи принадлежат своей очереди: показывать их до того, как пользователь
    в неё зашёл, значит показывать ключи, которые вне очереди ничего не значат.
    """
    await demo_service.seed_demo(db_session, owner=owner)
    assert (await auth_client.post("/api/v1/queues/OPS/archive")).status_code == 200

    bootstrap = _data(await auth_client.get("/api/v1/bootstrap"))

    assert [queue["key"] for queue in bootstrap["queues"]] == ["TRK"]
    # Локальное поле очереди OPS в стартовые данные не попадает, глобальное — попадает.
    refs = {field["ref"] for field in bootstrap["fields"]}
    assert "component" in refs
    assert "OPS.severity" not in refs
    # Локальный статус процесса с ревью — тоже: его отдаёт конфигурация очереди.
    assert "TRK.review" not in {entry["ref"] for entry in bootstrap["statuses"]}


async def test_bootstrap_counts_what_is_unread_for_this_actor(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    system_actor: Actor,
) -> None:
    """Счётчик считает инбокс того, чей токен: чужой прочитан или нет — не его дело.

    Токен подменяется на том же клиенте, а не берётся вторым: фикстура `auth_client` —
    это `client` с проставленным заголовком, то есть тот же объект. Два «разных»
    клиента в тесте делили бы заголовки и проверяли бы одного актора дважды.
    """
    from app.services import actors as actors_service
    from app.services import notifications as notifications_service

    await demo_service.seed_demo(db_session, owner=owner)
    agent = await actors_service.get_actor_by_key(db_session, "release_bot")
    await notifications_service.notify_actor(
        db_session,
        actor=agent,
        body="Что-то произошло",
    )
    assert _data(await auth_client.get("/api/v1/bootstrap"))["unread_notifications"] == 0

    issued = await actors_service.issue_token(
        db_session, agent, initiator=system_actor, name="aggregates"
    )
    auth_client.headers["Authorization"] = f"Bearer {issued.secret}"

    bootstrap = _data(await auth_client.get("/api/v1/bootstrap"))
    assert bootstrap["actor"]["key"] == agent.key
    assert bootstrap["unread_notifications"] == 1


async def test_the_project_summary_repeats_the_card_and_the_issue_list(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Сводка — карточка проекта плюс первая страница его задач, без своего отбора."""
    await demo_service.seed_demo(db_session, owner=owner)

    summary = _data(await auth_client.get("/api/v1/projects/alpha/summary"))

    assert summary["project"] == _data(await auth_client.get("/api/v1/projects/alpha"))
    listed = await auth_client.get("/api/v1/projects/alpha/issues")
    assert summary["issues"] == listed.json()["data"]
    assert summary["issues_next_cursor"] == listed.json()["meta"]["next_cursor"]


async def test_the_project_summary_narrows_with_the_same_query_language(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """`query` сужает выдачу и не может вывести её за пределы проекта."""
    await demo_service.seed_demo(db_session, owner=owner)

    narrowed = _data(
        await auth_client.get("/api/v1/projects/alpha/summary", params={"query": "queue: OPS"})
    )
    assert {issue["queue"] for issue in narrowed["issues"]} == {"OPS"}

    # Условие проекта приклеено первым и складывается по «и»: задача чужого проекта не
    # приедет, даже если её прямо попросить.
    escaped = _data(
        await auth_client.get("/api/v1/projects/alpha/summary", params={"query": "key: TRK-1"})
    )
    assert escaped["issues"] == []


async def test_a_board_answers_with_every_issue_it_shows(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Задача в статусе вне колонок видна через доску — ради этого маршрут и заведён.

    До него такая задача пропадала молча: сборка по колонкам её не показывала, а
    заметить пропажу можно было только сравнив доску с поиском по её же фильтру.
    """
    await demo_service.seed_demo(db_session, owner=owner)
    board = _data(await auth_client.get("/api/v1/boards"))[0]
    review = next(column for column in board["columns"] if column["name"] == "Ревью")

    assert (
        await auth_client.delete(f"/api/v1/boards/{board['id']}/columns/{review['id']}")
    ).status_code == 204

    from_columns = {
        card["key"]
        for column in _data(await auth_client.get(f"/api/v1/boards/{board['id']}"))["columns"]
        for card in _data(
            await auth_client.get(f"/api/v1/boards/{board['id']}/columns/{column['id']}/issues")
        )
    }
    everything = {
        card["key"] for card in _data(await auth_client.get(f"/api/v1/boards/{board['id']}/issues"))
    }

    assert "TRK-2" in everything, "the board must show an issue whose status has no column"
    assert "TRK-2" not in from_columns
    assert from_columns < everything
