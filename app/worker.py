"""Воркер шины событий: разбирает outbox и раздаёт события подписчикам.

Запуск: `python -m app.worker`. Отдельный сервис Compose в обоих контурах.

## Почему это отдельный процесс, а не поток внутри веб-сервера

Поток внутри API размножился бы вместе с репликами: три реплики — три воркера,
и каждое событие обработано трижды. Уведомление пришло бы три раза, вебхук ушёл бы три
раза, правило автоматики сработало бы три раза. Отдельный сервис масштабируется
отдельно от API, а если реплик воркера всё-таки станет несколько, их разведёт
`FOR UPDATE SKIP LOCKED` в `claim_next`.

## Как воркер переживает перезапуск

Каждое событие обрабатывается в собственной транзакции: захват строки, рассылка
подписчикам и отметка о результате — одно целое. Процесс, убитый посреди обработки,
откатывает транзакцию, снимает блокировку строки, и событие снова становится
необработанным. Потерять его нельзя, обработать дважды — тоже: подписчики, успевшие
отработать, перечислены в `delivered_to`, и повтор идёт только по оставшимся.

## Сбой круга не убивает процесс

Воркер обязан жить неделями, поэтому исключение внутри цикла — повод подождать и
попробовать снова, а не завершиться. Причины временные и типичные: при первом запуске
контура таблиц ещё нет (миграции применяются отдельным шагом), базу могут
перезапустить, соединение — оборваться. Ошибка при этом всегда уходит в лог целиком:
молчаливый сбой хуже падения, потому что события копились бы без объяснения.

Проверить это стоит руками, а не тестом: поднятый с нуля контур стартует воркер до
миграций, и первые секунды он работает на базе без своих таблиц. Ровно так дефект и
нашёлся.

## Остановка по сигналу

`SIGTERM` от `docker stop` только взводит флаг. Цикл проверяет его **между** событиями,
поэтому текущее событие всегда доводится до конца и фиксируется, а не бросается
посередине. Границы транзакции и прерываемости здесь совпадают намеренно.

Команда в Compose задана exec-формой, поэтому Python — первый процесс контейнера и
получает сигнал сам. Обёртка `sh -c` его бы проглотила, и остановка каждый раз
доходила бы до `SIGKILL`.
"""

import asyncio
import contextlib
import signal

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, session_scope
from app.services import automation as automation_service
from app.services import events as events_service
from app.services.event_bus import load_subscribers

logger = get_logger("worker")

#: Пауза после сбоя цикла. Отдельная от `outbox_poll_interval` и заметно длиннее:
#: при недоступной базе опрос раз в секунду залил бы лог трассировками, а помочь всё
#: равно не может — ждать приходится не нас.
ERROR_BACKOFF_SECONDS = 5.0


async def process_one_event() -> bool:
    """Обрабатывает одно событие в отдельной транзакции. `False` — обрабатывать нечего.

    Транзакция на событие, а не на пачку: падение на третьем событии не должно
    откатывать обработку первых двух, а подписчик, отработавший по первому, не должен
    делать это заново.
    """
    async with session_scope() as session:
        processed = await events_service.process_next_event(session)

    if processed is None:
        return False

    if processed.outcome.failed:
        logger.warning(
            "Event %s (%s) not delivered to %s; attempt %s, status %s",
            processed.envelope.id,
            processed.envelope.event_type,
            ", ".join(failure.name for failure in processed.outcome.failures),
            processed.attempts,
            processed.status.value,
        )
    else:
        logger.debug(
            "Event %s (%s) delivered to %s",
            processed.envelope.id,
            processed.envelope.event_type,
            ", ".join(processed.outcome.delivered) or "nobody",
        )
    return True


async def drain(stop: asyncio.Event) -> int:
    """Обрабатывает события, пока они есть или пока не попросили остановиться."""
    processed = 0
    while not stop.is_set():
        if not await process_one_event():
            break
        processed += 1
    return processed


async def run(settings: Settings | None = None) -> None:
    """Цикл воркера: разгрести очередь, поспать, повторить."""
    settings = settings or get_settings()
    subscribers = load_subscribers()
    logger.info(
        "Events worker started; subscribers: %s",
        ", ".join(subscribers) or "none registered",
    )

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    synchronised = False
    try:
        while not stop.is_set():
            try:
                if not synchronised:
                    # Реестр правил автоматики синхронизируется внутри цикла, а не до
                    # него, по той же причине, по которой цикл переживает сбой: при
                    # первом запуске контура таблиц ещё нет, и падение здесь убило бы
                    # процесс насмерть. Повторяется до первого успеха.
                    async with session_scope() as session:
                        await automation_service.sync_rules(session)
                    synchronised = True
                idle = await drain(stop) == 0
            except Exception:
                # Сбой одного круга не должен убивать процесс, который обязан жить
                # неделями. Базы может не быть вовсе (первый запуск контура: миграции
                # применяются отдельным шагом и позже), её могут перезапустить,
                # соединение может оборваться — всё это временно и лечится ожиданием.
                # Ошибка при этом уходит в лог целиком: молчаливый сбой был бы хуже
                # падения, потому что события копились бы, а причина осталась бы
                # неизвестной. Незафиксированная транзакция откатывается сама, и
                # событие, на котором сбой случился, остаётся необработанным.
                logger.exception("Events worker cycle failed; retrying")
                await _sleep_until(stop, ERROR_BACKOFF_SECONDS)
                continue
            if idle:
                await _sleep_until(stop, settings.outbox_poll_interval)
    finally:
        await dispose_engine()
    logger.info("Events worker stopped")


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Взводит флаг остановки по сигналам контейнера."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Обработчики сигналов есть не на всякой платформе (Windows). Молчать об
            # этом нельзя: там остановка пойдёт жёстко, и понять почему по пустому
            # логу невозможно.
            logger.warning("Signal %s is not supported here; shutdown will be abrupt", sig.name)


async def _sleep_until(stop: asyncio.Event, seconds: float) -> None:
    """Пауза, которую прерывает сигнал остановки.

    Обычный `sleep` заставил бы контейнер ждать конца паузы на каждой остановке —
    сначала лишние секунды, потом `SIGKILL`, если пауза окажется длиннее отведённого
    Docker времени.
    """
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


def main() -> int:
    settings = get_settings()
    configure_logging(debug=settings.debug)
    asyncio.run(run(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
