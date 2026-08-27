"""Окружение Alembic: асинхронный движок и метаданные проекта.

Адрес БД берётся из настроек приложения, но его можно переопределить
(`alembic -x database_url=...` или `config.set_main_option`) — этим пользуются тесты,
которые применяют миграции к отдельной тестовой базе.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

# Импорт наполняет Base.metadata: модели, не импортированные здесь, автогенерация не увидит.
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Адрес БД для миграций: -x database_url, затем alembic.ini, затем настройки приложения."""
    from_cli = context.get_x_argument(as_dictionary=True).get("database_url")
    if from_cli:
        return from_cli
    from_ini = config.get_main_option("sqlalchemy.url", default=None)
    if from_ini:
        return from_ini
    return str(get_settings().database_url)


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к базе (`alembic upgrade head --sql`)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Синхронная часть: Alembic работает с обычным Connection внутри run_sync."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Подключение через asyncpg. NullPool: процесс миграций живёт один прогон."""
    config.set_main_option("sqlalchemy.url", get_database_url())
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
