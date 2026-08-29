"""Доставщик вебхуков: разбирает очередь заданий и делает HTTP-запросы наружу.

Запуск: `python -m app.webhooks`. Отдельный сервис Compose в обоих контурах.

## Почему это отдельный процесс, а не подписчик шины

Воркер событий разбирает очередь **по одному событию** и в одной транзакции с
подписчиками. Отправка HTTP прямо из подписчика означала бы, что мёртвый адрес держит
всю очередь событий на своём таймауте: не доходят уведомления, не срабатывает
автоматика, копится outbox. Поэтому подписчик только кладёт задание в
`webhook_deliveries`, а сеть живёт здесь.

Побочно это решает и повторы. Шина повторяет **событие** по упавшим подписчикам; здесь
повторяется **доставка** по конкретному адресу. Без разделения одно событие уходило бы
на живые адреса столько раз, сколько раз упал мёртвый.

## Реплик может быть несколько

Задания разводит `FOR UPDATE SKIP LOCKED`, как и события. Но строка задания
заблокирована **всё время HTTP-запроса**, включая таймаут, — отсюда требование к
таймауту быть коротким и отсюда же смысл масштабирования: два доставщика полезны ровно
тогда, когда адресов много и часть из них медленная.

## Сбой круга не убивает процесс

Как у воркера: процесс обязан жить неделями, поэтому исключение внутри цикла — повод
подождать и попробовать снова. Непромигрированная база отделена от настоящего сбоя и
пишет строку предупреждения вместо трассировки: при первом запуске контура таблиц ещё
нет, это нормальное состояние старта.

## Остановка по сигналу

`SIGTERM` только взводит флаг, а цикл проверяет его **между** заданиями. Текущая
доставка доводится до конца и фиксируется — брошенная посередине, она откатилась бы и
ушла бы повторно, то есть получатель получил бы её дважды из-за нашей выкладки.
"""

import asyncio
import contextlib
import signal

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, schema_is_missing, session_scope
from app.services import webhooks as webhooks_service
from app.services.webhooks import DeliveryAttempt

logger = get_logger("webhooks.dispatcher")

#: Пауза после сбоя цикла. Отдельная от `webhook_poll_interval` и заметно длиннее: при
#: недоступной базе опрос раз в секунду залил бы лог трассировками, а помочь не может —
#: ждать приходится не нас.
ERROR_BACKOFF_SECONDS = 5.0

#: Потолок текста ошибки транспорта. Сообщение httpx бывает длиной в весь адрес с
#: параметрами и цепочкой причин, а колонке нужна причина, а не дамп.
MAX_TRANSPORT_ERROR_LENGTH = 500


def is_success(status_code: int) -> bool:
    """Считается ли ответ получателя успешной доставкой.

    Любой `2xx`, и ничего кроме. `3xx` — не успех намеренно: переход по перенаправлению
    увёл бы подписанный запрос на адрес, которого нет в подписке, а молча считать
    редирект доставкой значило бы отчитаться об отправке туда, куда мы не отправляли.
    """
    return 200 <= status_code < 300


async def send(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: bytes,
) -> DeliveryAttempt:
    """Одна попытка отправки. Исключение транспорта превращается в исход, а не летит выше.

    Именно здесь проходит граница между «получатель ответил» и «ответа не было»:
    у первого есть код, у второго только причина. Сценарий доставки различает их,
    записывая `response_status`, и по журналу видно, чинить получателя или сеть.
    """
    try:
        response = await client.post(url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        return DeliveryAttempt(
            ok=False,
            response_status=None,
            error=f"{type(exc).__name__}: {exc}"[:MAX_TRANSPORT_ERROR_LENGTH],
        )
    if is_success(response.status_code):
        return DeliveryAttempt(ok=True, response_status=response.status_code)
    return DeliveryAttempt(
        ok=False,
        response_status=response.status_code,
        error=f"HTTP {response.status_code}",
    )


async def process_one_delivery(client: httpx.AsyncClient) -> bool:
    """Обрабатывает одно задание в отдельной транзакции. `False` — обрабатывать нечего.

    Транзакция на задание, а не на пачку: падение на третьем не должно откатывать
    отправленные первые два, а получатель, уже получивший вызов, не должен получить его
    заново из-за соседа.
    """
    async with session_scope() as session:
        processed = await webhooks_service.process_next_delivery(
            session,
            send=lambda url, headers, body: send(client, url, headers, body),
        )

    if processed is None:
        return False

    if processed.attempt.ok:
        logger.debug(
            "Delivery %s (%s) sent to %s, HTTP %s",
            processed.delivery.id,
            processed.delivery.event_type,
            processed.delivery.url,
            processed.attempt.response_status,
        )
    else:
        logger.warning(
            "Delivery %s (%s) to %s failed on attempt %s: %s; status %s",
            processed.delivery.id,
            processed.delivery.event_type,
            processed.delivery.url,
            processed.attempts,
            processed.attempt.error,
            processed.status.value,
        )
    return True


async def drain(client: httpx.AsyncClient, stop: asyncio.Event) -> int:
    """Отправляет задания, пока они есть или пока не попросили остановиться."""
    processed = 0
    while not stop.is_set():
        if not await process_one_delivery(client):
            break
        processed += 1
    return processed


async def run(settings: Settings | None = None) -> None:
    """Цикл доставщика: разгрести очередь, поспать, повторить."""
    settings = settings or get_settings()
    logger.info(
        "Webhook dispatcher started; timeout %ss, up to %s attempts per delivery",
        settings.webhook_timeout,
        settings.webhook_max_attempts,
    )

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    # Один клиент на процесс: он держит пул соединений и переиспользует их между
    # доставками. Клиент на запрос означал бы новое TLS-рукопожатие на каждый вызов —
    # заметная доля времени доставки на защищённый адрес.
    #
    # `follow_redirects` выключен намеренно: переход увёл бы подписанный запрос на
    # адрес, которого нет в подписке, и подпись ушла бы туда, куда её не адресовали.
    async with httpx.AsyncClient(
        timeout=settings.webhook_timeout,
        follow_redirects=False,
    ) as client:
        try:
            while not stop.is_set():
                try:
                    idle = await drain(client, stop) == 0
                except Exception as exc:
                    # Сбой круга не должен убивать процесс, обязанный жить неделями.
                    # Незафиксированная транзакция откатывается сама, и задание, на
                    # котором сбой случился, остаётся ожидающим.
                    if schema_is_missing(exc):
                        logger.warning("Database schema is not migrated yet; retrying")
                    else:
                        logger.exception("Webhook dispatcher cycle failed; retrying")
                    await _sleep_until(stop, ERROR_BACKOFF_SECONDS)
                    continue
                if idle:
                    await _sleep_until(stop, settings.webhook_poll_interval)
        finally:
            await dispose_engine()
    logger.info("Webhook dispatcher stopped")


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Взводит флаг остановки по сигналам контейнера."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Обработчики сигналов есть не на всякой платформе (Windows). Молчать об
            # этом нельзя: там остановка пойдёт жёстко, и понять почему по пустому логу
            # невозможно.
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
