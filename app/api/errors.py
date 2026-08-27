"""Превращение исключений в единый формат ответа.

Единственная точка, где доменный код ошибки встречается с HTTP-статусом. Сервисы и
домен бросают наследников `AppError` и про этот модуль не знают.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger("api.errors")

_KNOWN_STATUSES = {status.value for status in HTTPStatus}

# Коды и сообщения для ошибок, которые приходят не из домена, а от транспорта:
# несуществующий маршрут, неподдерживаемый метод. Домен сюда ничего не добавляет —
# у его исключений код и сообщение свои.
_HTTP_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
}

_HTTP_MESSAGES: dict[int, str] = {
    400: "Bad request",
    401: "Authentication required",
    403: "Action is not allowed",
    404: "Resource not found",
    405: "Method not allowed",
    409: "State conflict",
    422: "Request validation failed",
    429: "Too many requests",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Собирает ответ в формате `{"error": {"code", "message", "details"}}`."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """Доменная ошибка: код и статус берутся из самого исключения."""
    assert isinstance(exc, AppError)
    if exc.status_code >= 500:
        logger.exception("Application error at %s %s", request.method, request.url.path)
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Тело или параметры запроса не сошлись со схемой Pydantic."""
    assert isinstance(exc, RequestValidationError)
    return error_response(
        422,
        "validation_error",
        _HTTP_MESSAGES[422],
        {"errors": jsonable_encoder(exc.errors())},
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """`HTTPException` из FastAPI и Starlette — в том числе 404 несуществующего маршрута."""
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    fallback = _HTTP_MESSAGES.get(exc.status_code, "Request error")
    # Starlette подставляет стандартную фразу статуса, когда detail не задан явно.
    # Своё сообщение уважаем, стандартное — заменяем на сообщение проекта.
    known = exc.status_code in _KNOWN_STATUSES
    standard_phrase = HTTPStatus(exc.status_code).phrase if known else None
    is_custom_detail = isinstance(exc.detail, str) and exc.detail != standard_phrase
    detail = exc.detail if is_custom_detail else fallback
    return error_response(exc.status_code, code, detail)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Всё, что не предусмотрено: наружу уходит код без подробностей, подробности — в лог."""
    logger.exception("Unhandled error at %s %s", request.method, request.url.path)
    return error_response(500, "internal_error", "Internal server error")


def register_exception_handlers(app: FastAPI) -> None:
    """Подключает обработчики к приложению. Порядок значения не имеет: диспетчер по типу."""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
