"""Единый формат ошибки: доменное исключение превращается в ответ с кодом."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError, ConflictError, NotFoundError


class SampleNotFound(NotFoundError):
    """Наследник из предметной области: проверяем, что схема работает для них.

    Класс намеренно свой, а не взятый из `app/domain/errors.py`: проверяется механика
    оболочки — код, статус и подробности доходят до клиента, — а не конкретная ошибка
    трекера. Доменные ошибки сверяются со справочником в `test_api_contract.py`.
    """

    code = "sample_not_found"
    message = "Sample TRK-123 not found"


@pytest.fixture
def error_app(app: FastAPI) -> FastAPI:
    """Приложение с маршрутами, которые падают разными способами."""

    @app.get("/boom/domain")
    async def _domain() -> None:
        raise SampleNotFound(details={"key": "TRK-123"})

    @app.get("/boom/conflict")
    async def _conflict() -> None:
        raise ConflictError("Sample version is outdated")

    @app.get("/boom/custom")
    async def _custom() -> None:
        raise AppError("Something went wrong", code="custom_error", status_code=418)

    @app.get("/boom/validation")
    async def _validation(limit: int) -> dict[str, int]:
        return {"limit": limit}

    return app


@pytest.fixture
async def error_client(error_app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=error_app)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as http_client:
        yield http_client


async def test_domain_error_keeps_code_and_details(error_client: AsyncClient) -> None:
    response = await error_client.get("/boom/domain")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "sample_not_found",
            "message": "Sample TRK-123 not found",
            "details": {"key": "TRK-123"},
        }
    }


async def test_conflict_error_uses_base_code(error_client: AsyncClient) -> None:
    response = await error_client.get("/boom/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert response.json()["error"]["message"] == "Sample version is outdated"


async def test_error_fields_can_be_overridden_per_instance(error_client: AsyncClient) -> None:
    response = await error_client.get("/boom/custom")

    assert response.status_code == 418
    assert response.json()["error"]["code"] == "custom_error"


async def test_unknown_route_uses_the_same_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nothing-here")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Resource not found",
        "details": {},
    }


async def test_request_validation_error_is_wrapped(error_client: AsyncClient) -> None:
    """Ошибка схемы Pydantic отдаётся в общем конверте, а не в формате FastAPI по умолчанию."""
    response = await error_client.get("/boom/validation", params={"limit": "not-a-number"})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]["errors"], "parse details must reach the client"
