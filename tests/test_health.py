"""Smoke-тест проверки здоровья: маршрут отвечает и подтверждает живую БД."""

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "environment": "local",
        "database": "ok",
    }


async def test_database_connection_is_alive(db_session: AsyncSession) -> None:
    """Фикстура сессии действительно доходит до PostgreSQL, а не до заглушки."""
    result = await db_session.execute(text("SELECT current_database()"))

    assert result.scalar_one().endswith("_test")
