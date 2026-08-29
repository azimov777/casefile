"""Сплошная проверка контракта: форма ответов у всех маршрутов сразу.

Тесты здесь не про отдельный эндпоинт, а про то, что у **всех** эндпоинтов одинаково.
При полутора сотнях операций глазами такое не отлавливается: расхождение появляется в
одном маршруте из ста сорока и живёт до тех пор, пока его не найдёт фронтенд.

Маршруты берутся из собранной схемы OpenAPI, а не из списка руками. Список руками
устаревает молча — новый роутер в него просто не попадает, и проверка продолжает
проходить, ничего не проверяя.

## Две развёртки, потому что они ловят разное

**Без токена** — по всем операциям всех методов. Ошибка приходит не из кода эндпоинта, а
из зависимости и обработчиков исключений, поэтому эта развёртка стережёт именно
фреймворк: переопределённые обработчики, оболочку ошибки, статус.

**С токеном** — по всем `GET` на демо-данных, с настоящими значениями параметров пути.
Эта развёртка стережёт успешный ответ: `data` у одиночного ресурса, `data` плюс `meta`
у коллекции, и ничего лишнего рядом.

Маршрут, для параметра которого нет настоящего значения, **роняет** тест, а не
пропускается. Пропуск — это способ незаметно потерять покрытие: новый маршрут с новым
параметром тихо выпал бы из проверки, а выглядела бы она по-прежнему сплошной.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contract import (
    BODYLESS_STATUS_CODES,
    ENVELOPE_EXEMPT,
    declared_error_classes,
    error_catalog,
    render_error_catalog,
)
from app.db.models.actor import Actor
from app.services import demo as demo_service
from app.services import queues as queues_service
from app.services import saved_filters as saved_filters_service
from app.services import webhooks as webhooks_service

#: Значение-затычка для развёртки без токена: до параметров дело не доходит, потому что
#: зависимость аутентификации отказывает раньше. UUID, а не «x», чтобы параметры типа
#: UUID тоже разбирались — иначе часть маршрутов ответила бы `422` вместо `401`, и
#: развёртка проверяла бы не то.
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

#: Маршруты, которые нельзя дёрнуть обычным запросом в развёртке с токеном.
#: Каждый — с причиной; молча пропускать здесь нечего.
UNCALLABLE: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/events/stream"): (
        "An endless stream. ASGITransport assembles the response only after the "
        "application is done, so this request would hang until the run times out "
        "(docs/notes/testing.md). Its error shape is covered by the tokenless sweep, "
        "and its frame shape by tests/test_events_stream.py"
    ),
}

#: Параметры ожидания, чтобы длинный опрос не держал прогон.
QUERY_OVERRIDES: dict[str, dict[str, Any]] = {
    "/api/v1/notifications/wait": {"timeout": 0.05},
}


@pytest.fixture
def schema(app: FastAPI) -> dict[str, Any]:
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


def operations(schema: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Все операции схемы: метод, путь, описание."""
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            yield method.upper(), path, operation


# --- Оболочка в схеме --------------------------------------------------------------


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
    return node


def test_declared_success_responses_are_the_envelope(schema: dict[str, Any]) -> None:
    """Каждый успешный ответ описан оболочкой — кроме перечисленных исключений.

    Проверяется схема, а не ответ: клиент генерируется именно из неё, и маршрут,
    описанный мимо оболочки, ломает генерацию раньше, чем кто-нибудь сделает запрос.
    """
    deviations: dict[tuple[str, str], str] = {}
    for method, path, operation in operations(schema):
        for code, response in operation.get("responses", {}).items():
            if not code.startswith("2") or code in BODYLESS_STATUS_CODES:
                continue
            content = response.get("content", {})
            body = content.get("application/json")
            if body is None:
                deviations[method, path] = f"{code}: {sorted(content) or 'no content'}"
                continue
            properties = _resolve(schema, body["schema"]).get("properties", {})
            is_collection = "data" in properties and (
                _resolve(schema, properties["data"]).get("type") == "array"
            )
            if "data" not in properties:
                deviations[method, path] = f"{code}: no data"
            elif is_collection and "meta" not in properties:
                deviations[method, path] = f"{code}: collection without meta"

    assert set(deviations) == set(ENVELOPE_EXEMPT), (
        f"envelope deviations {deviations}, declared exemptions {sorted(ENVELOPE_EXEMPT)}"
    )


def test_every_exemption_points_at_a_real_route(schema: dict[str, Any]) -> None:
    """Исключение, потерявшее свой маршрут, — это разрешение, выданное неизвестно кому."""
    declared = {(method, path) for method, path, _ in operations(schema)}

    assert set(ENVELOPE_EXEMPT) <= declared, sorted(set(ENVELOPE_EXEMPT) - declared)


def test_exemptions_carry_a_reason() -> None:
    """Причина обязательна: молча пропущенный маршрут неотличим от забытого."""
    for route, reason in ENVELOPE_EXEMPT.items():
        assert len(reason) > 40, route


def test_errors_are_described_with_the_common_envelope(schema: dict[str, Any]) -> None:
    """Ошибка любого маршрута — обычный JSON-конверт, даже если успех им не является.

    Ловит класс дефектов, который чтением кода не виден: `response_class` маршрута
    задаёт тип содержимого **всем** ответам операции, включая ошибки, и поток событий
    описывал бы `401` как `text/event-stream` (выявлено в задаче 15).
    """
    for method, path, operation in operations(schema):
        if not path.startswith("/api/v1"):
            continue
        responses = operation.get("responses", {})
        assert "401" in responses, f"{method} {path} does not describe 401"
        for code, response in responses.items():
            if code.startswith("2"):
                continue
            content = response.get("content")
            assert content is not None, f"{method} {path} describes {code} without a body"
            assert sorted(content) == ["application/json"], (
                f"{method} {path} {code}: {sorted(content)}"
            )
            reference = content["application/json"]["schema"].get("$ref", "")
            assert reference.endswith("/ErrorResponse"), f"{method} {path} {code}: {reference}"


# --- Оболочка в живом ответе -------------------------------------------------------


async def test_every_route_answers_with_the_error_envelope_without_a_token(
    client: AsyncClient,
    schema: dict[str, Any],
) -> None:
    """Развёртка по всем операциям: без токена каждая отвечает `401` в общей оболочке.

    Ошибка приходит из зависимости роутера и обработчика исключений, а не из кода
    эндпоинта, поэтому проверять её надо именно так — по всем маршрутам сразу.
    """
    checked = 0
    for method, path, _ in operations(schema):
        if not path.startswith("/api/v1"):
            continue
        url = _substitute(path, dict.fromkeys(_path_params(path), PLACEHOLDER))
        response = await client.request(method, url)

        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        payload = response.json()
        assert sorted(payload) == ["error"], f"{method} {path}: {sorted(payload)}"
        assert sorted(payload["error"]) == ["code", "details", "message"], f"{method} {path}"
        assert payload["error"]["code"] == "unauthorized", f"{method} {path}"
        assert payload["error"]["message"].isascii(), f"{method} {path}: message is not English"
        checked += 1

    assert checked > 100, f"the sweep covered only {checked} operations"


async def test_every_readable_route_answers_with_the_data_envelope(
    auth_client: AsyncClient,
    schema: dict[str, Any],
    sample: dict[str, str],
) -> None:
    """Развёртка по всем `GET` на демо-данных: `data`, а у коллекций ещё и `meta`.

    Значения параметров пути — настоящие, поэтому ответ настоящий: `404` здесь означал
    бы, что маршрут ищет не то, что отдают его соседи.
    """
    checked = 0
    for method, path, operation in operations(schema):
        if method != "GET" or (method, path) in UNCALLABLE:
            continue
        response = await auth_client.get(
            _substitute(path, sample),
            params=QUERY_OVERRIDES.get(path),
        )

        assert response.status_code == 200, f"GET {path} -> {response.status_code} {response.text}"
        payload = response.json()
        if (method, path) in ENVELOPE_EXEMPT:
            continue
        assert "data" in payload, f"GET {path}: {sorted(payload)}"
        declared = _resolve(
            schema,
            operation["responses"]["200"]["content"]["application/json"]["schema"],
        )
        expected = ["data", "meta"] if "meta" in declared.get("properties", {}) else ["data"]
        assert sorted(payload) == expected, f"GET {path}: {sorted(payload)}"
        if "meta" in expected:
            assert sorted(payload["meta"]) == ["has_more", "next_cursor"], f"GET {path}"
        checked += 1

    assert checked > 40, f"the sweep covered only {checked} readable routes"


def _path_params(path: str) -> list[str]:
    return [chunk.split("}")[0] for chunk in path.split("{")[1:]]


def _substitute(path: str, values: dict[str, str]) -> str:
    """Подставляет значения в путь. Неизвестный параметр — ошибка, а не пропуск."""
    url = path
    for name in _path_params(path):
        if name not in values:
            raise AssertionError(
                f"{path}: no sample value for path parameter {name!r}. Add one to the "
                "`sample` fixture instead of skipping the route: a skipped route looks "
                "exactly like a covered one"
            )
        url = url.replace(f"{{{name}}}", values[name])
    return url


@pytest.fixture
async def sample(db_session: AsyncSession, owner: Actor) -> dict[str, str]:
    """Настоящие значения для каждого параметра пути, взятые из демо-набора.

    Демо-набор, а не свои фикстуры: он и так обязан быть связным и разнообразным, и
    вторая копия такого же набора разошлась бы с ним на первой правке.
    """
    await demo_service.seed_demo(db_session, owner=owner)
    dev = await queues_service.get_queue_by_key(db_session, demo_service.DEV_QUEUE_KEY)
    config = await queues_service.get_queue_config(db_session, dev, initiator=owner)
    filters = await saved_filters_service.list_saved_filters(db_session, initiator=owner)
    board = await _board(db_session, owner=owner)
    subscription = await webhooks_service.create_subscription(
        db_session,
        initiator=owner,
        name="Демо-подписка",
        url="https://example.test/hook",
    )
    return {
        "actor_key": owner.key,
        "queue_key": dev.key,
        "status_ref": "open",
        "issue_type_ref": "task",
        "resolution_ref": "done",
        "field_ref": "component",
        "issue_key": f"{dev.key}-2",
        "project_key": "alpha",
        "portfolio_key": "platform",
        "board_id": str(board.id),
        "column_id": str(board.columns[0].id),
        "filter_id": str(filters.items[0].id),
        "workflow_id": str(config.workflows[0].workflow.id),
        "rule_key": demo_service.DEMO_RULE_KEY,
        "subscription_id": str(subscription.id),
        # Параметры, которые встречаются только у изменяющих маршрутов: развёртка с
        # токеном ходит лишь по `GET`, но подстановка обязана знать их все — иначе
        # новый `GET` с таким параметром упал бы не с внятным сообщением, а с KeyError.
        "token_id": str(uuid.uuid4()),
        "comment_id": str(uuid.uuid4()),
        "item_id": str(uuid.uuid4()),
        "link_id": str(uuid.uuid4()),
        "transition_id": str(uuid.uuid4()),
        "delivery_id": str(uuid.uuid4()),
        "tag": "контракт",
    }


async def _board(db_session: AsyncSession, *, owner: Actor) -> Any:
    from app.services import boards as boards_service

    page = await boards_service.list_boards(db_session, initiator=owner)
    return page.items[0]


# --- Справочник кодов ошибок -------------------------------------------------------


def test_error_codes_are_unique() -> None:
    """Два класса с одним кодом означают, что клиент не может по нему решать."""
    codes = [entry.code for entry in error_catalog()]

    assert len(codes) == len(set(codes)), sorted({code for code in codes if codes.count(code) > 1})


def test_error_codes_are_snake_case_and_described() -> None:
    for entry in error_catalog():
        assert entry.code.islower() and " " not in entry.code, entry.code
        assert entry.message.isascii(), f"{entry.code}: message is not English"
        assert entry.summary, f"{entry.code}: no description of when it happens"


def test_the_catalog_covers_every_error_declared_in_the_code() -> None:
    """Класс ошибки вне справочника — код, о котором фронтенд узнает от пользователя.

    Обход всего пакета, а не доверие импортам справочника: справочник грузит три модуля
    руками, и ошибка, объявленная в четвёртом, попала бы в ответы, но не в документ.
    """
    known = {entry.code for entry in error_catalog()}
    declared = {error_class.code for error_class in declared_error_classes()}

    assert declared <= known, sorted(declared - known)


def test_the_error_document_is_up_to_date() -> None:
    """`docs/ERRORS.md` собирается командой, поэтому обязан совпадать с кодом.

    Документ, который расходится с кодом, хуже отсутствующего: по нему принимают
    решения. Пересобрать: `docker compose run --rm schema`.
    """
    document = Path(__file__).resolve().parents[1] / "docs" / "ERRORS.md"

    assert document.read_text(encoding="utf-8") == render_error_catalog(), (
        "docs/ERRORS.md is stale, regenerate it: docker compose run --rm schema"
    )


# --- Полнота документации ----------------------------------------------------------


def test_every_operation_carries_a_summary_and_a_description(schema: dict[str, Any]) -> None:
    """Описание операции — это строка документации обработчика, и она обязательна.

    Схема — поставляемый артефакт: по ней фронтенд пишет интерфейс, не спрашивая. Пустое
    описание превращает маршрут в загадку ровно там, где загадок быть не должно, —
    у маршрута, который выглядит понятным автору и никому больше.
    """
    undocumented = [
        f"{method} {path}"
        for method, path, operation in operations(schema)
        if not operation.get("summary") or not operation.get("description")
    ]

    assert not undocumented, f"operations without a summary or a description: {undocumented}"


def test_every_path_parameter_is_described(schema: dict[str, Any]) -> None:
    """Параметр пути без описания приезжает в сгенерированный клиент безымянной строкой.

    Ловится только так: в коде маршрут с `issue_key: str` выглядит совершенно нормально,
    и отличить его от маршрута с общим псевдонимом типа можно лишь по схеме.
    """
    undescribed = [
        f"{method} {path} -> {parameter['name']}"
        for method, path, operation in operations(schema)
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "path" and not parameter.get("description")
    ]

    assert not undescribed, f"path parameters without a description: {undescribed}"


# --- Совпадение имён у REST и MCP --------------------------------------------------

#: Поля, которых у одного из слоёв нет намеренно. Ключ — имя поля, значение — причина.
#: Список закрытый: любое другое расхождение означает, что интерфейсы разъехались.
KNOWN_LAYER_DIFFERENCES: dict[str, str] = {
    "id": (
        "REST only. An agent addresses an issue by key and by key alone, so the "
        "identifier would be wasted context on every row of every listing"
    ),
    "status_category": (
        "MCP only. An agent decides by the status category, not by its name, and "
        "without it every decision would cost a second call into the catalog"
    ),
    "description_truncated": (
        "MCP only. Tools cap the size of text they return, and the agent has to know "
        "it read only part of the description"
    ),
    "description_length": "MCP only. Full length of a truncated description, next to the flag",
}


async def test_mcp_and_rest_name_the_fields_of_an_issue_the_same(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Представления задачи в REST и в MCP повторяют имена полей — без общего кода.

    `api` и `mcp` друг от друга не зависят намеренно, поэтому переименование поля в
    схеме REST **не** долетает до MCP автоматически: агент продолжает получать старое
    имя, и заметить это можно только по несделанной работе. Отсюда и тест — он
    единственное место, где два слоя сверяются (выявлено в задаче 16).
    """
    from app.api.schemas.issues import IssueRead
    from app.mcp import views
    from app.services import issues as issues_service

    await demo_service.seed_demo(db_session, owner=owner)
    issue = await issues_service.get_issue_by_key(db_session, f"{demo_service.DEV_QUEUE_KEY}-2")

    rest = set(IssueRead.of(issue).model_dump())
    mcp = set(views.issue(issue, text_limit=10_000))

    unexplained = (rest ^ mcp) - set(KNOWN_LAYER_DIFFERENCES)
    assert not unexplained, (
        f"REST and MCP disagree on issue field names: {sorted(unexplained)}. "
        "Rename it in both layers, or document the difference in KNOWN_LAYER_DIFFERENCES"
    )


async def test_mcp_and_rest_name_the_fields_of_a_changelog_entry_the_same(
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """То же для истории изменений: тип события зовётся `event_type` в обоих слоях."""
    from app.api.schemas.events import ChangelogEntryRead
    from app.mcp import views
    from app.services import events as events_service
    from app.services import issues as issues_service

    await demo_service.seed_demo(db_session, owner=owner)
    issue = await issues_service.get_issue_by_key(db_session, f"{demo_service.DEV_QUEUE_KEY}-2")
    page = await events_service.list_changelog(db_session, issue, initiator=owner, limit=1)
    entry = page.items[0]

    rest = set(ChangelogEntryRead.of(entry, issue_key=issue.key).model_dump())
    mcp = set(views.changelog_entry(entry))

    # У записи MCP нет ни `id`, ни ключа задачи: страница истории всегда про одну
    # задачу, и агент запрашивает её сам — повторять ключ в каждой строке значит
    # тратить контекст на известное.
    assert mcp <= rest, sorted(mcp - rest)
    assert rest - mcp == {"id", "issue"}, sorted(rest - mcp)
