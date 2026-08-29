"""Проверка здоровья сервиса.

Живёт вне префикса `/api/v1`: это эндпоинт для docker и мониторинга, а не часть
версионируемого контракта с фронтендом.
"""

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import SessionDep
from app.api.schemas.common import ErrorResponse
from app.api.schemas.health import HealthResponse
from app.core.config import get_settings
from app.db.session import DatabaseUnavailableError

router = APIRouter(tags=["service"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    responses={503: {"model": ErrorResponse, "description": "Database is unavailable"}},
)
async def health(session: SessionDep) -> HealthResponse:
    """Отвечает `ok`, только если соединение с БД действительно живое."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DatabaseUnavailableError(details={"reason": type(exc).__name__}) from exc

    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
        database="ok",
    )
