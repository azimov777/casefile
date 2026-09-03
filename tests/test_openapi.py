"""Схема OpenAPI пригодна для генерации типизированного клиента.

Фронтенд собирает из неё `openapi.ts`, поэтому дефекты схемы — это дефекты контракта:
маршрут без модели ответа приходит на фронт как `unknown`, а нестабильный
`operation_id` ломает клиент при переезде маршрута, хотя контракт не менялся.
"""

import re

import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# Свободная форма допустима только там, где она задокументирована в соглашениях.
# Имя поля целиком — историческое исключение, действующее во всех схемах; `Модель.поле`
# — исключение ровно в одном месте. Новые исключения заводятся только вторым способом:
# «поле с таким именем» разрешает свободную форму и там, где о ней никто не думал.
FREEFORM_SCHEMAS = {
    "details",
}

OPERATION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@pytest.fixture
def schema(app: FastAPI) -> dict:
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


def _operation_ids(schema: dict) -> list[str]:
    """Идентификаторы операций берутся из схемы, а не из `app.routes`.

    С версии FastAPI 0.141 подключённые роутеры не разворачиваются в `app.routes`:
    там лежат объекты `_IncludedRouter`, и отбор по `isinstance(route, APIRoute)`
    возвращает пустой список. Проверка при этом продолжает проходить — на пустом
    множестве, — то есть перестаёт что-либо стеречь. Схема же собирается тем самым
    кодом, который отдаёт `/openapi.json` фронтенду, и врать не может.
    """
    return [
        operation["operationId"]
        for methods in schema["paths"].values()
        for operation in methods.values()
        if "operationId" in operation
    ]


def test_operation_ids_are_unique(schema: dict) -> None:
    """FastAPI уникальности не гарантирует: два обработчика могут получить одно имя."""
    ids = _operation_ids(schema)

    assert ids, "schema exposes no operations at all"
    assert len(ids) == len(set(ids)), f"duplicate operation ids: {sorted(ids)}"


def test_operation_ids_are_readable_snake_case(schema: dict) -> None:
    """Иначе в клиенте появятся имена вида `read_actor_api_v1_actors__actor_key__get`."""
    for operation_id in _operation_ids(schema):
        assert OPERATION_ID_PATTERN.match(operation_id), operation_id


def test_every_route_declares_a_response_model(schema: dict) -> None:
    """Ответ без описанной формы приходит на фронт как `unknown`."""
    missing: list[str] = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            responses = operation.get("responses", {})
            success = [code for code in responses if code.startswith("2")]
            for code in success:
                # 204 не имеет тела по соглашениям — это одно из двух исключений.
                if code == "204":
                    continue
                if "content" not in responses[code]:
                    missing.append(f"{method.upper()} {path} -> {code}")

    assert not missing, f"routes without a response body schema: {missing}"


def test_errors_are_described_with_the_common_envelope(schema: dict) -> None:
    """Фронтенд должен видеть форму ошибки, а не догадываться о ней."""
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in methods.items():
            responses = operation.get("responses", {})
            assert "401" in responses, f"{method.upper()} {path} does not describe 401"
            schema_ref = responses["401"]["content"]["application/json"]["schema"]["$ref"]
            assert schema_ref.endswith("/ErrorResponse")


def test_no_objects_of_unknown_shape(schema: dict) -> None:
    """`Record<string, unknown>` в клиенте обесценивает генерацию целиком."""
    unknown: list[str] = []
    for name, definition in schema["components"]["schemas"].items():
        for field, field_schema in definition.get("properties", {}).items():
            if field in FREEFORM_SCHEMAS or f"{name}.{field}" in FREEFORM_SCHEMAS:
                continue
            if field_schema.get("type") == "object" and "additionalProperties" in field_schema:
                unknown.append(f"{name}.{field}")

    assert not unknown, f"fields of unknown shape: {unknown}"


def test_patch_field_is_not_nullable_when_null_has_no_meaning(schema: dict) -> None:
    """`ActorUpdate` не должен разрешать `null`: сгенерированный клиент обязан это знать."""
    properties = schema["components"]["schemas"]["ActorUpdate"]["properties"]

    assert properties["display_name"] == {
        "type": "string",
        "maxLength": 255,
        "minLength": 1,
        "title": "Display Name",
        "examples": ["Релизный бот"],
    }
    assert properties["is_active"]["type"] == "boolean"
