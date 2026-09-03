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

from app.api.contract import (
    BODYLESS_STATUS_CODES,
    ENVELOPE_EXEMPT,
    declared_error_classes,
    error_catalog,
    render_error_catalog,
)
from app.db.models.participant import Participant
from app.db.models.queue import Queue

#: Значение-затычка для развёртки без токена: до параметров дело не доходит, потому что
#: зависимость аутентификации отказывает раньше. UUID, а не «x», чтобы параметры типа
#: UUID тоже разбирались — иначе часть маршрутов ответила бы `422` вместо `401`, и
#: развёртка проверяла бы не то.
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

#: Маршруты, которые нельзя дёрнуть обычным запросом в развёртке с токеном.
#: Каждый — с причиной; молча пропускать здесь нечего. Пусто, пока такого маршрута нет:
#: поток ленты (задача 26) попадёт сюда вместе со своей причиной.
UNCALLABLE: dict[tuple[str, str], str] = {}

#: Параметры запроса, которые развёртка обязана подставить, чтобы не держать прогон
#: (например, нулевой таймаут ожидания). Пусто, пока ждущих маршрутов нет.
QUERY_OVERRIDES: dict[str, dict[str, Any]] = {}


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

    # Порог, а не точное число: развёртка обязана падать, когда роутеры перестали
    # подключаться вовсе, и не обязана — когда добавился очередной маршрут.
    assert checked >= _api_operations(schema), f"the sweep covered only {checked} operations"


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

    assert checked >= 3, f"the sweep covered only {checked} readable routes"


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
async def sample(owner: Participant, queue: Queue) -> dict[str, str]:
    """Настоящие значения для каждого параметра пути.

    Значения настоящие, а не выдуманные: развёртка с токеном обязана получать `200`, и
    подставленный от балды ключ дал бы `404`, то есть проверял бы обработку ошибки
    вместо формы успешного ответа.
    """
    return {
        "participant_name": owner.name,
        "queue_key": queue.key,
        # Параметр, который встречается только у изменяющего маршрута: развёртка с
        # токеном ходит лишь по `GET`, но подстановка обязана знать их все — иначе
        # новый `GET` с таким параметром упал бы не с внятным сообщением, а с KeyError.
        "token_id": str(uuid.uuid4()),
    }


def _api_operations(schema: dict[str, Any]) -> int:
    """Сколько операций объявлено под `/api/v1` — ожидаемый охват развёртки без токена."""
    return sum(1 for _, path, _ in operations(schema) if path.startswith("/api/v1"))


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
