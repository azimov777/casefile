"""Подключение к PostgreSQL: движок, фабрика сессий и способы её получить.

Движок создаётся лениво и живёт один на процесс: пул соединений нельзя создавать
на каждый запрос. Тесты движок не трогают — они подменяют зависимость `get_session`.

Граница транзакции описана ровно один раз — в `session_scope`. `get_session` это та же
граница, поданная как зависимость FastAPI. Расходиться двум путям некуда: HTTP-запрос,
воркер outbox и скрипт фиксируют изменения одним и тем же кодом.

Правило простое: вызывающий код завершился без исключения — коммит, вылетело исключение —
откат. Сценарий в `services` может коммитить и сам, если ему нужна промежуточная фиксация,
но обязанности помнить про финальный коммит у него нет.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(url: str | None = None) -> AsyncEngine:
    """Создаёт новый движок. Отдельная функция — чтобы тесты могли поднять свой."""
    settings = get_settings()
    return create_async_engine(
        url or str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    """Движок приложения, единый на процесс."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий приложения."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def dispose_engine() -> None:
    """Закрывает пул соединений. Вызывается при остановке приложения."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия с транзакцией: единственное место, где живёт граница фиксации изменений.

    Используется напрямую воркерами outbox, планировщиком автодействий и скриптами;
    HTTP-запросы получают её через `get_session`. Менять поведение транзакции нужно
    здесь — второго такого места в проекте нет.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: тот же `session_scope`, поданный как зависимость.

    Обработчик отработал без исключения — коммит; вылетело любое исключение, включая
    доменное, — откат. Одна и та же функция сервиса, вызванная из REST, из MCP и из
    воркера, фиксируется одинаково, потому что фиксирует её один и тот же код.
    """
    async with session_scope() as session:
        yield session
