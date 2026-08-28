"""Планировщик автодействий: будит правила, которым пришло время.

Запуск: `python -m app.scheduler`. Отдельный сервис Compose в обоих контурах.

## Он обязан быть в единственном экземпляре

Две реплики выполнят каждое автодействие дважды: два комментария, два снятых
исполнителя, две волны событий. Поэтому в Compose у сервиса одна реплика, и это не
рекомендация, а требование — в отличие от воркера событий, который масштабируется
свободно (там строки разводит `FOR UPDATE SKIP LOCKED` в самой очереди).

Страховка от ошибки развёртывания всё же стоит: строка правила берётся тем же
`FOR UPDATE SKIP LOCKED`, поэтому второй экземпляр пройдёт мимо занятой строки, а не
выполнит то же правило второй раз. На неё нельзя полагаться как на замену единственности
— окно между тиками она не закрывает, — но лишней она не бывает.

## Транзакция на правило, а не на тик

Каждое автодействие идёт в своей транзакции: одно правило может перебрать двести задач,
и держать всё это в одной транзакции с остальными правилами значило бы, что сбой на
последнем откатывает работу первых. Границы транзакции и повторяемости здесь совпадают
намеренно: правило, чья транзакция откатилась, не сдвинуло своё расписание и будет
взято снова.

## Остальное устроено как у воркера событий

Сбой круга не убивает процесс (база может быть ещё не мигрирована — миграции идут
отдельным шагом), `SIGTERM` проверяется между правилами, а не посреди правила, команда в
Compose задана exec-формой, чтобы сигнал дошёл до Python.
"""

import asyncio
import contextlib
import signal
from datetime import UTC, datetime

from app.automation import engine
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, session_scope
from app.services import automation as automation_service

logger = get_logger("scheduler")

#: Пауза после сбоя круга. Отдельная от интервала тика и заметно длиннее: при
#: недоступной базе опрос с обычной частотой залил бы лог трассировками, а помочь всё
#: равно не может — ждать приходится не нас.
ERROR_BACKOFF_SECONDS = 5.0


async def tick() -> int:
    """Один круг: найти созревшие автодействия и выполнить каждое своей транзакцией.

    Возвращает число выполненных правил. Ноль — нормальный и самый частый исход:
    расписание у автодействий измеряется часами, а тик идёт раз в полминуты.
    """
    now = datetime.now(UTC)
    async with session_scope() as session:
        keys = await engine.due_rule_keys(session, now=now)

    executed = 0
    for key in keys:
        async with session_scope() as session:
            outcomes = await engine.run_scheduled_rule(session, key, now=now)
        if not outcomes:
            # Правило перехватил кто-то другой или у него не нашлось задач. Первое —
            # аномалия развёртывания, второе — норма, и различить их по одному этому
            # месту нельзя; смотреть надо в журнал срабатываний.
            logger.debug("Automation rule %s produced no runs", key)
            continue
        executed += 1
        logger.info(
            "Automation rule %s ran on %s issues: %s",
            key,
            len(outcomes),
            ", ".join(f"{item.run.issue_key}={item.status.value}" for item in outcomes),
        )
    return executed


async def run(settings: Settings | None = None) -> None:
    """Цикл планировщика: разобрать созревшее, поспать, повторить."""
    settings = settings or get_settings()

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    started = False
    try:
        while not stop.is_set():
            try:
                if not started:
                    # Синхронизация реестра идёт внутри цикла, а не до него: при первом
                    # запуске контура таблиц ещё нет (миграции применяются отдельным
                    # шагом и позже), и падение здесь убило бы процесс насмерть.
                    async with session_scope() as session:
                        created = await automation_service.sync_rules(session)
                    started = True
                    logger.info(
                        "Automation scheduler started; new rules registered: %s",
                        ", ".join(created) or "none",
                    )
                await tick()
            except Exception:
                logger.exception("Automation scheduler cycle failed; retrying")
                await _sleep_until(stop, ERROR_BACKOFF_SECONDS)
                continue
            await _sleep_until(stop, settings.automation_tick_interval)
    finally:
        await dispose_engine()
    logger.info("Automation scheduler stopped")


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Взводит флаг остановки по сигналам контейнера."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            logger.warning("Signal %s is not supported here; shutdown will be abrupt", sig.name)


async def _sleep_until(stop: asyncio.Event, seconds: float) -> None:
    """Пауза, которую прерывает сигнал остановки."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


def main() -> int:
    settings = get_settings()
    configure_logging(debug=settings.debug)
    asyncio.run(run(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
