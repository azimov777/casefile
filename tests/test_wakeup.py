"""Слушатель журнала: штатное закрытие молчит, настоящий обрыв — предупреждает.

asyncpg зовёт колбэк завершения (`add_termination_listener`) на любое закрытие
соединения, в том числе на наше собственное `close()`, — библиотека не различает,
кто закрыл соединение. Раньше `JournalWakeup._on_termination` писал WARNING в обоих
случаях, и штатная остановка процесса (`docker compose restart mcp`, закрытие stdio)
каждый раз печатала предупреждение о «потере связи», которое на самом деле означает
только обрыв — то, ради чего строка и существует (TRK-126).

Эти тесты идут на своём соединении `JournalWakeup`, а не на глобальном
`journal_wakeup`: второй тест обрывает соединение снаружи (`pg_terminate_backend`), и
если бы это был процесс-синглтон, вся остальная лента в прогоне осталась бы без
слушателя.
"""

import asyncio
import logging
from collections.abc import Iterator

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import asyncpg_dsn
from app.db.wakeup import JOURNAL_CHANNEL, JournalWakeup

#: Сколько ждать колбэк завершения после `pg_terminate_backend`: обрыв соединения —
#: событие сети, а не нашего кода, и приходит асинхронно, не в момент вызова.
TERMINATION_TIMEOUT = 5.0


async def _wait_until(predicate, timeout: float = TERMINATION_TIMEOUT) -> None:
    """Ждёт, пока `predicate()` не станет истинным, опрашивая её мелким шагом."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true in time")
        await asyncio.sleep(0.05)


@pytest.fixture(autouse=True)
def wakeup_logger_enabled() -> Iterator[None]:
    """Гарантирует, что логгер `tracker.wakeup` не глушит запись.

    `app/db/migrations/env.py` зовёт `fileConfig` с `disable_existing_loggers=True`
    по умолчанию и выключает уже созданные логгеры — в том числе этот; фикстура
    `engine` гоняет миграции один раз за сессию, и от порядка запуска тестов зависит,
    успел ли кто-то включить логгер обратно (`docs/notes/testing.md`). Тест на
    текст предупреждения не должен зависеть от этой случайности.
    """
    target = logging.getLogger("tracker.wakeup")
    previous = target.disabled
    target.disabled = False
    yield
    target.disabled = previous


async def test_close_does_not_warn_about_lost_connection(
    test_database_url: str,
    engine: AsyncEngine,  # только чтобы тестовая база была создана и мигрирована
    caplog: pytest.LogCaptureFixture,
) -> None:
    wakeup = JournalWakeup(JOURNAL_CHANNEL)
    await wakeup.start(asyncpg_dsn(test_database_url))
    assert wakeup.is_listening, "без слушателя тест ничего не проверяет"

    with caplog.at_level(logging.WARNING, logger="tracker.wakeup"):
        await wakeup.close()
        # asyncpg не зовёт колбэк завершения напрямую — он планирует его через
        # `call_soon` и срабатывает на следующем обороте цикла событий, уже после
        # возврата из `close()` (`docs/notes/journal.md`). Без паузы здесь тест не
        # даёт этому обороту случиться и зеленеет, даже если `close()` только
        # подавляет эффект колбэка на время себя самого, а не снимает подписку —
        # ровно так исходный флаговый вариант чинки прошёл тесты и не сработал
        # вживую при `docker compose restart mcp` (TRK-126).
        await asyncio.sleep(0.1)

    assert "lost its connection" not in caplog.text
    assert not wakeup.is_listening


async def test_external_disconnection_warns_about_lost_connection(
    test_database_url: str,
    engine: AsyncEngine,  # только чтобы тестовая база была создана и мигрирована
    caplog: pytest.LogCaptureFixture,
) -> None:
    dsn = asyncpg_dsn(test_database_url)
    wakeup = JournalWakeup(JOURNAL_CHANNEL)
    await wakeup.start(dsn)
    assert wakeup.is_listening, "без слушателя тест ничего не проверяет"

    # Соединение слушателя закрывает не он сам — сервер убивает его бэкенд по pid,
    # ровно как настоящий обрыв (база упала, администратор оборвал сессию).
    assert wakeup._connection is not None
    backend_pid = await wakeup._connection.fetchval("select pg_backend_pid()")

    killer = await asyncpg.connect(dsn)
    try:
        with caplog.at_level(logging.WARNING, logger="tracker.wakeup"):
            await killer.execute("select pg_terminate_backend($1)", backend_pid)
            await _wait_until(lambda: not wakeup.is_listening)
    finally:
        await killer.close()

    assert "lost its connection" in caplog.text
