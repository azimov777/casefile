"""Сквозные сценарии: система целиком, а не по слоям.

Каждый тест здесь проходит путь, которым пойдёт живой пользователь или агент, и
проверяет результат так, как его увидит он: через HTTP, а где речь об агенте — через
MCP. Тесты слоёв этого не заменяют и не заменяются им: они ловят разное. Сценарий не
знает, в каком модуле сломалось, но замечает, что связка не работает; тест слоя знает
модуль, но связку не видит.

Именно поэтому здесь почти нет обращений к сервисам напрямую. Единственные исключения —
разбор очереди событий и работа от имени второго актора: у воркера нет HTTP-входа, а
второй токен нужен ровно затем, чтобы уведомление пришло не тому, кто его породил.

Если сквозной сценарий упирается в противоречие архитектуры, его надо фиксировать
задачей, а не обходить здесь: тест, обошедший противоречие, закрепляет его.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from mcp.server.mcpserver import MCPServer
from mcp_types import InputRequiredResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation import engine
from app.db.models.actor import Actor
from app.domain.actors import ActorType
from app.mcp.runtime import use_headers
from app.services import actors as actors_service
from app.services import demo as demo_service
from app.services import events as events_service
from app.services.event_bus import SubscriberRegistry
from app.services.events import EventEnvelope
from app.services.notification_subscriber import deliver as deliver_notifications

Call = Callable[..., Awaitable[dict[str, Any]]]


# --- Вспомогательное ---------------------------------------------------------------


def _data(response: Any) -> Any:
    """Тело успешного ответа. Падает с текстом ошибки, а не с `KeyError` на `data`."""
    assert response.status_code < 300, (
        f"{response.request.url} -> {response.status_code}: {response.text}"
    )
    return response.json()["data"]


async def _transition(client: AsyncClient, key: str, name: str, **changes: Any) -> dict[str, Any]:
    """Проводит задачу по названному ребру процесса — так же, как это делает интерфейс.

    Версия читается прямо перед переходом: у перехода она обязательна, в отличие от
    `PATCH`. Это часть контракта, а не особенность теста, — см. `perform_issue_transition`.
    """
    issue = _data(await client.get(f"/api/v1/issues/{key}"))
    transitions = _data(await client.get(f"/api/v1/issues/{key}/transitions"))
    available = {item["name"]: item for item in transitions}
    assert name in available, f"{key}: no transition {name!r}, available: {sorted(available)}"
    # Недоступность допустима ровно тогда, когда недостающее приезжает этим же запросом:
    # переход в закрывающий статус требует резолюцию, а требуемые поля заполняются в
    # `values` — и то и другое едет вместе с ходом, одной мутацией.
    supplied = set(changes) | set(changes.get("values") or {})
    missing = set(available[name]["missing_fields"]) - supplied
    assert not missing, f"{key}: transition {name!r} still needs {sorted(missing)}"
    response = await client.post(
        f"/api/v1/issues/{key}/transitions/{available[name]['id']}",
        json={"version": issue["version"], **changes},
    )
    return _data(response)


async def _drain(session: AsyncSession, *, limit: int = 200) -> int:
    """Разбирает очередь событий до пустоты — то, чем в контуре занят воркер.

    Подписчики те же, что и в бою, но реестр собирается здесь: глобальный общий на
    процесс, и его состав зависел бы от того, какие модули успели импортироваться.

    Потолок обязателен: незатухающая цепочка правил без него повесила бы прогон вместо
    того, чтобы упасть с внятным числом.
    """
    registry = SubscriberRegistry()

    async def automation(session: AsyncSession, event: EventEnvelope) -> None:
        await engine.dispatch_event(session, event)

    registry.register(automation, name="automation")
    registry.register(deliver_notifications, name="notifications")

    processed = 0
    while processed < limit:
        if await events_service.process_next_event(session, registry=registry) is None:
            return processed
        processed += 1
    raise AssertionError(f"event queue did not drain within {limit} events")


@pytest.fixture
async def agent(db_session: AsyncSession) -> Actor:
    """Агент — второй актор сценариев: уведомление должно прийти не автору действия."""
    actor, _ = await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="release_bot",
        display_name="Релизный бот",
    )
    return actor


@pytest.fixture
def agent_call(
    mcp_server: MCPServer,
    db_session: AsyncSession,
    system_actor: Actor,
    agent: Actor,
) -> Call:
    """Вызов инструмента MCP от имени агента, с его собственным токеном.

    Не фикстура `mcp_call`: та ходит от владельца, а весь смысл сценария с уведомлением
    в том, что его получает **другой** актор — тот, кто ничего не делал.
    """

    async def _call(tool: str, /, **arguments: Any) -> dict[str, Any]:
        issued = await actors_service.issue_token(
            db_session, agent, initiator=system_actor, name="e2e"
        )
        async with use_headers({"authorization": f"Bearer {issued.secret}"}):
            result = await mcp_server.call_tool(tool, arguments)
        assert not isinstance(result, InputRequiredResult)
        assert result.structured_content is not None
        return result.structured_content

    return _call


# --- Сценарий 1: очередь, процесс, поля, задача от создания до закрытия -------------


async def test_a_queue_is_set_up_and_an_issue_goes_all_the_way_to_closed(
    auth_client: AsyncClient,
) -> None:
    """Путь владельца свежей установки: собрать процесс и провести по нему задачу.

    Проверяется именно связка. Каждый шаг в отдельности покрыт тестами своего слоя, но
    только вместе они отвечают на вопрос «можно ли на этом работать»: очередь знает про
    свой процесс, процесс требует поле, задача без поля не закрывается, а с полем —
    закрывается и получает резолюцию.
    """
    queue = _data(
        await auth_client.post(
            "/api/v1/queues",
            json={"key": "E2E", "name": "Сквозная очередь", "issue_types": ["task"]},
        )
    )
    assert queue["key"] == "E2E"

    field = _data(
        await auth_client.post(
            "/api/v1/fields",
            json={
                "key": "release_notes",
                "name": "Заметки к релизу",
                "value_type": "text",
                "queue": "E2E",
            },
        )
    )
    assert field["ref"] == "E2E.release_notes"

    workflow = _data(
        await auth_client.post(
            "/api/v1/queues/E2E/workflows/from-template",
            json={"template": "simple", "name": "Сквозной процесс", "issue_types": ["task"]},
        )
    )
    # Закрытие требует заметок к релизу: поле объявляется требованием перехода, а не
    # обязательным полем очереди — обязательное пришлось бы заполнять при создании.
    complete = next(item for item in workflow["transitions"] if item["name"] == "Complete")
    _data(
        await auth_client.put(
            f"/api/v1/workflows/{workflow['id']}/transitions/{complete['id']}",
            json={
                "name": "Complete",
                "from_status": complete["from_status"],
                "to_status": complete["to_status"],
                "required_fields": ["E2E.release_notes"],
                "requires_resolution": True,
            },
        )
    )

    issue = _data(
        await auth_client.post(
            "/api/v1/issues",
            json={"queue": "E2E", "summary": "Сквозная задача"},
        )
    )
    key = issue["key"]
    assert key.startswith("E2E-")
    assert issue["status"] == "open"

    assert (await _transition(auth_client, key, "Start progress"))["status"] == "in_progress"

    # Закрытие без требуемого поля не предлагается вовсе, и это видно заранее: переход
    # приезжает недоступным и с названием того, чего ему не хватает.
    transitions = _data(await auth_client.get(f"/api/v1/issues/{key}/transitions"))
    blocked = next(item for item in transitions if item["name"] == "Complete")
    assert not blocked["is_available"]
    # Резолюция в том же списке: для карточки это такое же незаполненное требование, как
    # и поле, и разделять их значило бы заставлять интерфейс знать про них по отдельности.
    assert set(blocked["missing_fields"]) == {"E2E.release_notes", "resolution"}

    closed = await _transition(
        auth_client,
        key,
        "Complete",
        resolution="done",
        values={"E2E.release_notes": "Собрано и выложено"},
    )
    assert closed["status"] == "closed"
    assert closed["resolution"] == "done"

    # История собралась сама, из тех же изменений: отдельного вызова «записать в журнал»
    # нигде не было.
    changelog = _data(await auth_client.get(f"/api/v1/issues/{key}/changelog"))
    recorded = [entry["event_type"] for entry in changelog]
    assert recorded[0] == "issue.created"
    assert "issue.status_changed" in recorded


# --- Сценарий 2: проект поперёк очередей и его прогресс -----------------------------


async def test_a_project_collects_issues_from_two_queues_and_counts_progress(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Главное свойство проекта: он не привязан к очереди.

    Прогресс считается по категории статуса, а не по его названию, поэтому две очереди
    с разными процессами дают один осмысленный процент. Демо-набор здесь именно затем,
    что в нём две очереди с разными графами: собрать такую же пару руками означало бы
    держать вторую копию набора.
    """
    await demo_service.seed_demo(db_session, owner=owner)

    summary = _data(await auth_client.get("/api/v1/projects/alpha/summary"))
    queues = {issue["queue"] for issue in summary["issues"]}
    assert len(queues) == 2, f"the project must span two queues, got {queues}"

    progress = summary["project"]["progress"]
    assert progress["total"] == 5
    assert progress["done"] == 1
    assert progress["ratio"] == pytest.approx(0.2)

    # Закрытая задача поднимает долю — и её видно тем же запросом, без пересчёта руками.
    await _transition(auth_client, "OPS-1", "Start progress")
    await _transition(auth_client, "OPS-1", "Complete", resolution="done")

    updated = _data(await auth_client.get("/api/v1/projects/alpha/summary"))["project"]["progress"]
    assert updated["done"] == 2
    assert updated["ratio"] == pytest.approx(0.4)

    # Задача, выведенная из проекта, остаётся жить в своей очереди.
    response = await auth_client.delete("/api/v1/projects/alpha/issues/OPS-1")
    assert response.status_code == 204
    assert _data(await auth_client.get("/api/v1/issues/OPS-1"))["project"] is None
    assert (
        _data(await auth_client.get("/api/v1/projects/alpha/summary"))["project"]["progress"][
            "total"
        ]
        == 4
    )


# --- Сценарий 3: декомпозиция и дерево ---------------------------------------------


async def test_an_issue_is_decomposed_and_the_tree_shows_the_hierarchy(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Декомпозиция целиком: связь, обратная сторона, дерево и защита от цикла."""
    await demo_service.seed_demo(db_session, owner=owner)

    child = _data(
        await auth_client.post(
            "/api/v1/issues",
            json={"queue": "TRK", "summary": "Внучатая задача"},
        )
    )
    _data(
        await auth_client.post(
            f"/api/v1/issues/{child['key']}/links",
            json={"type": "subtask_of", "issue": "TRK-2"},
        )
    )

    # Связь хранится один раз и называется со стороны спрашивающего: у ребёнка это
    # `subtask_of`, у родителя — `parent_of`.
    from_child = _data(await auth_client.get(f"/api/v1/issues/{child['key']}/links"))
    assert [(item["type"], item["issue"]["key"]) for item in from_child] == [
        ("subtask_of", "TRK-2")
    ]
    from_parent = _data(await auth_client.get("/api/v1/issues/TRK-2/links"))
    assert ("parent_of", child["key"]) in [
        (item["type"], item["issue"]["key"]) for item in from_parent
    ]

    tree = _data(await auth_client.get("/api/v1/issues/TRK-1/tree"))
    assert tree["issue"]["key"] == "TRK-1"
    first_level = {node["issue"]["key"] for node in tree["children"]}
    assert first_level == {"TRK-2", "TRK-3", "TRK-5"}
    grandchildren = next(node for node in tree["children"] if node["issue"]["key"] == "TRK-2")
    assert [node["issue"]["key"] for node in grandchildren["children"]] == [child["key"]]

    # Цикл на произвольной глубине не заводится. Проверяется на своей цепочке без
    # родителей: у задачи родитель может быть только один, и на демо-задачах отказ
    # пришёл бы раньше и по другой причине — `link_parent_exists`.
    top = _data(
        await auth_client.post("/api/v1/issues", json={"queue": "TRK", "summary": "Вершина"})
    )
    middle = _data(
        await auth_client.post("/api/v1/issues", json={"queue": "TRK", "summary": "Середина"})
    )
    bottom = _data(
        await auth_client.post("/api/v1/issues", json={"queue": "TRK", "summary": "Низ"})
    )
    for lower, upper in ((middle, top), (bottom, middle)):
        _data(
            await auth_client.post(
                f"/api/v1/issues/{lower['key']}/links",
                json={"type": "subtask_of", "issue": upper["key"]},
            )
        )
    response = await auth_client.post(
        f"/api/v1/issues/{top['key']}/links",
        json={"type": "subtask_of", "issue": bottom["key"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "link_cycle_detected"

    # А у эпика родителя не бывает вовсе: это верхний уровень планирования.
    refused = await auth_client.post(
        "/api/v1/issues/TRK-1/links",
        json={"type": "subtask_of", "issue": top["key"]},
    )
    assert refused.json()["error"]["code"] == "epic_cannot_have_parent"


# --- Сценарий 4: правило сработало, агент узнал об этом через MCP -------------------


async def test_a_rule_fires_and_the_agent_picks_the_notification_up_through_mcp(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
    agent: Actor,
    agent_call: Call,
) -> None:
    """Полный круг механики, ради которой во многом всё и строится.

    Владелец закрывает эпик → правило автоматики видит открытые подзадачи и пишет
    комментарий → подписчик уведомлений кладёт его в инбокс наблюдателя → агент забирает
    уведомление инструментом MCP и читает по нему задачу.

    Проверяется **инбокс**, а не MCP-нотификация: нотификации идут подписками
    `subscriptions/listen` и требуют протокола `2026-07-28`, который реальный клиент
    (Claude Code) не согласовывает. Тест на нотификациях проверял бы канал, которого у
    клиента нет (выявлено в задаче 16).
    """
    await demo_service.seed_demo(db_session, owner=owner)
    # Демо-набор уже включил правило и подписал агента на эпик: сценарию остаётся
    # закрыть эпик. Проверяем это явно — иначе тест зелёный и на выключенном правиле.
    rule = _data(await auth_client.get(f"/api/v1/automation/rules/{demo_service.DEMO_RULE_KEY}"))
    assert rule["is_enabled"], "the demo set must ship with an enabled rule"
    assert agent.key in _data(await auth_client.get("/api/v1/issues/TRK-1"))["followers"]

    await _drain(db_session)
    seen_before = {
        item["id"] for item in (await agent_call("list_notifications", unread_only=False))["items"]
    }

    await _transition(auth_client, "TRK-1", "Start progress")
    await _transition(auth_client, "TRK-1", "Send to review")
    await _transition(auth_client, "TRK-1", "Complete", resolution="done")
    await _drain(db_session)

    fresh = [
        item
        for item in (await agent_call("list_notifications", unread_only=False))["items"]
        if item["id"] not in seen_before
    ]
    announcements = [item for item in fresh if item["event_type"] == "comment.created"]
    assert announcements, f"the agent got no comment notification, only {fresh}"

    # Комментарий написан системным актором — правило работает от его имени, — и назвал
    # именно те подзадачи, которые остались открытыми.
    comments = _data(await auth_client.get("/api/v1/issues/TRK-1/comments"))
    announcement = comments[-1]
    assert announcement["author"] == "system"
    assert "TRK-2" in announcement["body"] and "TRK-3" in announcement["body"]

    # Агент дочитывает контекст тем же инструментом, которым пользуется в работе.
    issue = await agent_call("get_issue", issue="TRK-1", detail="full")
    assert issue["key"] == "TRK-1"
    assert issue["status"] == "closed"

    # И разбирает инбокс: повторный вызов не приносит того же дважды.
    marked = await agent_call(
        "mark_notifications_read", notifications=[item["id"] for item in fresh]
    )
    assert marked["marked"] == len(fresh)
    still_unread = await agent_call("list_notifications", unread_only=True)
    taken = {entry["id"] for entry in fresh}
    assert not [item for item in still_unread["items"] if item["id"] in taken]


# --- Сценарий 5: доска, перенос карточки и ранжирование ----------------------------


async def test_a_board_moves_a_card_through_the_process_and_keeps_its_order(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Доска целиком: сборка, перенос карточки переходом и ручной порядок.

    Два движения карточки — разные операции, и это видно снаружи: перенос в другую
    колонку меняет статус и потому идёт через процесс, а перестановка внутри колонки
    статуса не касается и версию задачи не поднимает.
    """
    await demo_service.seed_demo(db_session, owner=owner)
    board = _data(await auth_client.get("/api/v1/boards"))[0]
    columns = {column["name"]: column for column in board["columns"]}

    backlog = columns["Бэклог"]["id"]
    in_progress = columns["В работе"]["id"]  # noqa: RUF001
    cards = _data(await auth_client.get(f"/api/v1/boards/{board['id']}/columns/{backlog}/issues"))
    keys = [card["key"] for card in cards]
    assert {"TRK-3", "TRK-5"} <= set(keys)

    # Перенос карточки — это переход воркфлоу со всеми его проверками.
    before = _data(await auth_client.get("/api/v1/issues/TRK-3"))
    moved = _data(
        await auth_client.post(
            f"/api/v1/boards/{board['id']}/issues/TRK-3/column",
            json={"column": in_progress, "version": before["version"]},
        )
    )
    assert moved["status"] == "in_progress"
    assert moved["version"] > before["version"]

    working = _data(
        await auth_client.get(f"/api/v1/boards/{board['id']}/columns/{in_progress}/issues")
    )
    assert "TRK-3" in [card["key"] for card in working]

    # Перестановка задаётся соседом, а не позицией: разреженная шкала наружу не выходит.
    ordered = [
        card["key"]
        for card in _data(
            await auth_client.get(f"/api/v1/boards/{board['id']}/columns/{backlog}/issues")
        )
    ]
    assert len(ordered) >= 2
    last, first = ordered[-1], ordered[0]
    version_before_ranking = _data(await auth_client.get(f"/api/v1/issues/{last}"))["version"]
    response = await auth_client.put(
        f"/api/v1/boards/{board['id']}/issues/{last}/rank",
        json={"before": first},
    )
    assert response.status_code == 200

    reordered = [
        card["key"]
        for card in _data(
            await auth_client.get(f"/api/v1/boards/{board['id']}/columns/{backlog}/issues")
        )
    ]
    assert reordered[0] == last, f"the card was not moved to the top: {reordered}"

    # Ранг живёт на доске, а не на задаче: версия от перестановки не растёт и в историю
    # она не попадает — это способ смотреть, а не данные о работе.
    assert _data(await auth_client.get(f"/api/v1/issues/{last}"))["version"] == (
        version_before_ranking
    )

    # И вся доска целиком видна одним запросом, независимо от раскладки по колонкам.
    everything = _data(await auth_client.get(f"/api/v1/boards/{board['id']}/issues"))
    assert {"TRK-1", "TRK-2", "TRK-3", "TRK-4", "TRK-5"} == {card["key"] for card in everything}
