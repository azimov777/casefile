"""Сценарии вебхуков: подписки, постановка заданий, доставка, журнал.

## Подписчик шины ничего не отправляет

`dispatch_event` только **ставит задания** — по строке на каждый подходящий адрес. HTTP
делает отдельный процесс (`app/webhooks.py`). Разделение обязательно: воркер событий
обрабатывает очередь по одному событию, и подписчик, ждущий таймаута мёртвого адреса,
остановил бы доставку всем остальным подписчикам — и уведомлениям, и автоматике.

## Повторы здесь свои, и это не дубль повторов шины

Шина повторяет **событие** и только по упавшим подписчикам. Вебхук повторяет
**доставку** по конкретному адресу. Если бы вебхук пользовался повторами шины, одно
событие ушло бы на живые адреса столько раз, сколько раз упал мёртвый.

## Мёртвый адрес отключается сам

Счётчик неудач подряд живёт на подписке и растёт на каждой **неудачной попытке**, а не
на исчерпавшей попытки доставке: порог в десяток запросов подряд гасит молчащий адрес
за минуты, а не за час. Любая успешная доставка обнуляет счётчик — получатель, теряющий
каждую вторую доставку, работает, и гасить его нельзя.

Отключение заодно гасит **ожидающие** задания этой подписки. Оставить их значило бы
продолжать жечь таймауты доставщика на адресе, который только что признали мёртвым.

## Транзакция

Сценарии не фиксируют: границу держит вход в приложение. Подписчик шины работает внутри
вложенной транзакции воркера, доставщик — внутри своей `session_scope`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.sentinels import UNSET, UnsetType, is_set
from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.db.pagination import Page
from app.db.repositories import (
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)
from app.domain.errors import (
    WebhookDeliveryNotFoundError,
    WebhookDeliveryNotRetryableError,
    WebhookSubscriptionDisabledError,
    WebhookSubscriptionNameTakenError,
    WebhookSubscriptionNotFoundError,
)
from app.domain.notifications import audience_of
from app.domain.webhooks import (
    DELIVERY_HEADER,
    DIRECT_EVENT_TYPE,
    DIRECT_OBJECT_TYPE,
    EVENT_HEADER,
    MAX_ERROR_LENGTH,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    DeliveryStatus,
    WebhookScope,
    build_direct_payload,
    build_payload,
    matches_event_type,
    sign,
    validate_subscription,
)
from app.services.event_bus import EventEnvelope
from app.services.events import RetryPolicy
from app.services.permissions import ensure_allowed

logger = get_logger("webhooks")

#: Причина автоматического отключения подписки. Стабильный код, а не фраза: по нему
#: клиент решает, что показать, и он же ищется в логах.
DISABLED_BY_FAILURES = "delivery_failures"

#: Причина, по которой ожидающее задание погашено вместе с подпиской.
CANCELLED_BY_DISABLE = "subscription disabled after consecutive failures"

#: Транспорт доставки: адрес, заголовки и байты тела на входе, исход попытки на выходе.
#: Передаётся сценарию параметром, а не берётся импортом, чтобы слой сценариев не знал
#: про HTTP-клиент, а тест обходился без сети.
type DeliverySender = Callable[[str, dict[str, str], bytes], Awaitable["DeliveryAttempt"]]


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """Итог одной попытки отправки: ответ получателя или причина, по которой его нет.

    `response_status is None` означает, что ответа не было вовсе — таймаут, отказ
    соединения, неразрешённое имя. Различать это обязательно: «500 от получателя» и
    «адрес не отвечает» чинятся в разных местах.
    """

    ok: bool
    response_status: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedDelivery:
    """Итог обработки одного задания: что отправляли и чем кончилось."""

    delivery: WebhookDelivery
    attempt: DeliveryAttempt
    status: DeliveryStatus
    attempts: int


@dataclass(frozen=True, slots=True)
class DirectDelivery:
    """Итог адресного вызова из правила: задание либо причина, по которой его нет.

    Пропуск — не ошибка и не молчание. Подписка, выключенная или сузившая набор типов,
    настроена так осознанно, и правило из-за чужой настройки падать не должно; но и
    потеряться вызов не имеет права — причина уезжает в журнал срабатываний.
    """

    delivery: WebhookDelivery | None = None
    skipped: str | None = None


def retry_policy() -> RetryPolicy:
    """Политика повторов доставки. Арифметика общая с шиной, настройки свои.

    Общая арифметика — чтобы «пауза удваивается и упирается в потолок» имело в проекте
    один смысл. Свои настройки — потому что уровни разные: шина повторяет событие,
    вебхук повторяет доставку по конкретному адресу.
    """
    settings = get_settings()
    return RetryPolicy(
        max_attempts=settings.webhook_max_attempts,
        base_delay=timedelta(seconds=settings.webhook_retry_delay),
        max_delay=timedelta(seconds=settings.webhook_max_retry_delay),
    )


# --- Подписки -----------------------------------------------------------------------


async def list_subscriptions(
    session: AsyncSession,
    *,
    initiator: Actor,
    is_enabled: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[WebhookSubscription]:
    """Подписки установки страницами.

    Подписки общие, а не персональные, в отличие от инбокса: вебхук — канал установки
    наружу, и адрес, заведённый одним администратором, обязан быть виден другому.
    """
    ensure_allowed(initiator, "webhook.list")
    return await WebhookSubscriptionRepository(session).list_page(
        is_enabled=is_enabled,
        limit=limit,
        cursor=cursor,
    )


async def get_subscription(
    session: AsyncSession,
    subscription_id: uuid.UUID,
    *,
    initiator: Actor,
) -> WebhookSubscription:
    ensure_allowed(initiator, "webhook.read")
    subscription = await WebhookSubscriptionRepository(session).get(subscription_id)
    if subscription is None:
        raise WebhookSubscriptionNotFoundError(details={"subscription": str(subscription_id)})
    return subscription


async def get_subscription_by_name(
    session: AsyncSession,
    name: str,
    *,
    initiator: Actor,
) -> WebhookSubscription:
    """Подписка по имени: так её адресует правило автоматики."""
    ensure_allowed(initiator, "webhook.read")
    subscription = await WebhookSubscriptionRepository(session).find_by_name(name.strip())
    if subscription is None:
        raise WebhookSubscriptionNotFoundError(details={"name": name})
    return subscription


async def create_subscription(
    session: AsyncSession,
    *,
    initiator: Actor,
    name: str,
    url: str,
    scope: WebhookScope = WebhookScope.ALL,
    scope_key: str | None = None,
    event_types: list[str] | None = None,
    secret: str | None = None,
    is_enabled: bool = True,
) -> WebhookSubscription:
    """Заводит подписку. Секрет генерируется, если его не задали.

    Возвращённый объект несёт секрет в открытом виде — единственный раз за его жизнь.
    Дальше он нужен только для сборки подписи, и показывать его в списке подписок
    значило бы отдать ключ ко всем будущим доставкам любому читателю API.
    """
    ensure_allowed(initiator, "webhook.create")
    normalized_name = name.strip()
    repository = WebhookSubscriptionRepository(session)
    if await repository.find_by_name(normalized_name) is not None:
        raise WebhookSubscriptionNameTakenError(details={"name": normalized_name})

    normalized_url, normalized_key, types, resolved_secret = validate_subscription(
        url=url,
        scope=scope,
        scope_key=scope_key,
        event_types=event_types,
        secret=secret,
    )
    return await repository.add(
        WebhookSubscription(
            name=normalized_name,
            url=normalized_url,
            secret=resolved_secret,
            scope=scope,
            scope_key=normalized_key,
            event_types=types,
            is_enabled=is_enabled,
            created_by_id=initiator.id,
        )
    )


async def update_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    initiator: Actor,
    url: str | UnsetType = UNSET,
    event_types: list[str] | UnsetType = UNSET,
    secret: str | UnsetType = UNSET,
    is_enabled: bool | UnsetType = UNSET,
) -> WebhookSubscription:
    """Правит подписку. Область и её ключ не меняются — это была бы другая подписка.

    Включение вручную снимает автоматическое отключение целиком: счётчик неудач
    обнуляется, отметка и причина стираются. Иначе подписка, включённая после починки
    адреса, погасла бы на первой же неудаче — счётчик остался бы на пороге.
    """
    ensure_allowed(initiator, "webhook.update", target=subscription)

    normalized_url, _, types, resolved_secret = validate_subscription(
        url=subscription.url if isinstance(url, UnsetType) else url,
        scope=subscription.scope,
        scope_key=subscription.scope_key,
        event_types=subscription.event_types if isinstance(event_types, UnsetType) else event_types,
        # Пустая строка в `secret` означала бы «сгенерировать новый», а тут его не
        # просили менять вовсе: подставляем текущий, чтобы валидатор не выдал третий.
        secret=subscription.secret if isinstance(secret, UnsetType) else secret,
    )

    subscription.url = normalized_url
    subscription.event_types = types
    subscription.secret = resolved_secret
    if is_set(is_enabled):
        subscription.is_enabled = is_enabled
        if is_enabled:
            subscription.consecutive_failures = 0
            subscription.disabled_at = None
            subscription.disabled_reason = None

    await WebhookSubscriptionRepository(session).flush()
    return subscription


async def delete_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    initiator: Actor,
) -> None:
    """Удаляет подписку вместе с её журналом доставок.

    Журнал уходит каскадом намеренно: он описывает работу конкретного адреса, и в
    отрыве от подписки отвечать ему не на что. Нужен след — подписку выключают, а не
    удаляют.
    """
    ensure_allowed(initiator, "webhook.delete", target=subscription)
    await WebhookSubscriptionRepository(session).delete(subscription)


# --- Постановка заданий -------------------------------------------------------------


async def dispatch_event(
    session: AsyncSession,
    event: EventEnvelope,
    *,
    now: datetime | None = None,
) -> list[WebhookDelivery]:
    """Ставит задания на доставку события по всем подходящим адресам.

    Зовётся подписчиком шины из воркера. Аудиторию считает домен уведомлений
    (`audience_of`) — по нагрузке события и без похода в базу; второй реализации
    вопроса «к чему относится событие» в проекте быть не должно.
    """
    moment = now or datetime.now(UTC)
    audience = audience_of(event.event_type, event.payload)
    subscriptions = await WebhookSubscriptionRepository(session).matching(
        queue_key=audience.queue_key,
        project_keys=audience.project_keys,
    )
    targets = [
        subscription
        for subscription in subscriptions
        if matches_event_type(subscription.event_types, event.event_type)
    ]
    if not targets:
        return []

    deliveries = []
    for subscription in targets:
        delivery_id = uuid.uuid4()
        deliveries.append(
            WebhookDelivery(
                id=delivery_id,
                # Связь объектом, а не одним идентификатором: SQLAlchemy заполнит и
                # внешний ключ, и `delivery.subscription`. С голым `subscription_id`
                # обращение к подписке у только что созданной строки уходило бы в
                # ленивую загрузку — а она вне greenlet падает `MissingGreenlet`.
                subscription=subscription,
                event_id=event.id,
                event_type=event.event_type,
                object_type=event.object_type,
                object_key=event.object_key,
                url=subscription.url,
                payload=build_payload(
                    delivery_id=str(delivery_id),
                    event_id=str(event.id),
                    event_type=event.event_type,
                    object_type=event.object_type,
                    object_key=event.object_key,
                    actor_key=event.actor_key,
                    occurred_at=event.created_at,
                    payload=event.payload,
                    audience=audience,
                ),
                available_at=moment,
            )
        )
    return await WebhookDeliveryRepository(session).add_all(deliveries)


async def enqueue_direct(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    initiator: Actor,
    body: str,
    details: dict[str, Any] | None = None,
    issue: Issue | None = None,
    rule_key: str | None = None,
    now: datetime | None = None,
) -> DirectDelivery:
    """Ставит адресный вызов, поставленный правилом автоматики.

    Ровно задание, а не HTTP-запрос. Синхронный вызов внутри правила задержал бы
    обработку события на таймаут мёртвого адреса и уронил бы правило вместе с его
    работой — то самое, от чего доставка и уведена в отдельную таблицу.

    Выключенная подписка и не подходящий фильтр типов дают пропуск, а не ошибку: и то и
    другое — осознанная настройка получателя, и правило из-за неё падать не должно.
    Молчанием пропуск при этом не становится — причина уезжает в журнал срабатываний.
    """
    ensure_allowed(initiator, "webhook.call", target=subscription)
    if not subscription.is_enabled:
        return DirectDelivery(skipped="subscription_disabled")
    if not matches_event_type(subscription.event_types, DIRECT_EVENT_TYPE):
        return DirectDelivery(skipped="event_type_filtered")

    moment = now or datetime.now(UTC)
    delivery_id = uuid.uuid4()
    object_type = "issue" if issue is not None else DIRECT_OBJECT_TYPE
    object_key = issue.key if issue is not None else (rule_key or subscription.name)
    delivery = await WebhookDeliveryRepository(session).add(
        WebhookDelivery(
            id=delivery_id,
            subscription=subscription,
            event_id=None,
            event_type=DIRECT_EVENT_TYPE,
            object_type=object_type,
            object_key=object_key,
            url=subscription.url,
            payload=build_direct_payload(
                delivery_id=str(delivery_id),
                actor_key=initiator.key,
                occurred_at=moment,
                object_type=object_type,
                object_key=object_key,
                issue_key=None if issue is None else issue.key,
                body=body,
                details=details,
            ),
            available_at=moment,
        )
    )
    return DirectDelivery(delivery=delivery)


# --- Журнал доставок ----------------------------------------------------------------


async def list_deliveries(
    session: AsyncSession,
    *,
    initiator: Actor,
    subscription_id: uuid.UUID | None = None,
    status: DeliveryStatus | None = None,
    event_type: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[WebhookDelivery]:
    ensure_allowed(initiator, "webhook.deliveries")
    return await WebhookDeliveryRepository(session).list_page(
        subscription_id=subscription_id,
        status=status,
        event_type=event_type,
        limit=limit,
        cursor=cursor,
    )


async def get_delivery(
    session: AsyncSession,
    delivery_id: uuid.UUID,
    *,
    initiator: Actor,
) -> WebhookDelivery:
    ensure_allowed(initiator, "webhook.deliveries")
    delivery = await WebhookDeliveryRepository(session).get(delivery_id)
    if delivery is None:
        raise WebhookDeliveryNotFoundError(details={"delivery": str(delivery_id)})
    return delivery


async def retry_delivery(
    session: AsyncSession,
    delivery: WebhookDelivery,
    *,
    initiator: Actor,
    now: datetime | None = None,
) -> WebhookDelivery:
    """Ставит завершённую доставку заново — **новой** строкой с новым идентификатором.

    Не возвратом старой строки в очередь, и это принципиально. Идентификатор доставки
    лежит внутри тела и служит получателю признаком повтора: отправив то же тело второй
    раз, мы получили бы вызов, который добросовестный получатель обязан отбросить как
    дубль — то есть ручная переотправка ничего бы не сделала.

    Отсюда правило для получателя, и оно описано в документации подписки: по
    `delivery` отбрасываются автоматические повторы, по `event.id` — ручная
    переотправка, если событие уже обработано.
    """
    ensure_allowed(initiator, "webhook.retry", target=delivery)
    if delivery.status is DeliveryStatus.PENDING:
        raise WebhookDeliveryNotRetryableError(
            details={"delivery": str(delivery.id), "status": delivery.status.value},
        )
    subscription = delivery.subscription
    if not subscription.is_enabled:
        raise WebhookSubscriptionDisabledError(
            details={
                "subscription": str(subscription.id),
                "name": subscription.name,
                "reason": subscription.disabled_reason,
            },
        )

    moment = now or datetime.now(UTC)
    delivery_id = uuid.uuid4()
    payload = dict(delivery.payload)
    payload["delivery"] = str(delivery_id)
    return await WebhookDeliveryRepository(session).add(
        WebhookDelivery(
            id=delivery_id,
            subscription=subscription,
            event_id=delivery.event_id,
            event_type=delivery.event_type,
            object_type=delivery.object_type,
            object_key=delivery.object_key,
            # Адрес берётся из подписки, а не копируется из старой строки: переотправка
            # обычно и делается после того, как адрес починили.
            url=subscription.url,
            payload=payload,
            available_at=moment,
        )
    )


# --- Доставка -----------------------------------------------------------------------


async def process_next_delivery(
    session: AsyncSession,
    *,
    send: DeliverySender,
    policy: RetryPolicy | None = None,
    now: datetime | None = None,
) -> ProcessedDelivery | None:
    """Берёт одно задание, отправляет его и записывает исход. `None` — очередь пуста.

    `send` — транспорт `(url, headers, body) -> DeliveryAttempt`. Он передаётся
    параметром, а не берётся импортом, ровно затем, чтобы этот сценарий тестировался
    без сети: HTTP-клиент живёт в процессе доставщика (`app/webhooks.py`), а здесь
    остаётся решение «повторять, сдаться или погасить подписку».

    Транзакцию функция не фиксирует. Это и есть механизм переживания перезапуска:
    строка задания заблокирована `FOR UPDATE` до конца транзакции, и убитый посреди
    отправки процесс откатывает её целиком — задание снова становится ожидающим.
    """
    moment = now or datetime.now(UTC)
    retry = policy or retry_policy()
    settings = get_settings()

    repository = WebhookDeliveryRepository(session)
    delivery = await repository.claim_next(now=moment)
    if delivery is None:
        return None

    subscription = delivery.subscription
    body, headers = prepare_request(delivery, secret=subscription.secret, timestamp=moment)
    attempt = await send(delivery.url, headers, body)

    delivery.attempts += 1
    delivery.response_status = attempt.response_status

    if attempt.ok:
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = moment
        delivery.last_error = None
        # Успех обнуляет счётчик, а не уменьшает его: получатель, теряющий каждую
        # вторую доставку, работает — гасить надо тот адрес, который молчит подряд.
        subscription.consecutive_failures = 0
    else:
        delivery.last_error = (attempt.error or "delivery failed")[:MAX_ERROR_LENGTH]
        subscription.consecutive_failures += 1
        if delivery.attempts >= retry.max_attempts:
            delivery.status = DeliveryStatus.FAILED
        else:
            delivery.available_at = moment + retry.delay_after(delivery.attempts)
        if subscription.consecutive_failures >= settings.webhook_failure_threshold:
            await disable_subscription(session, subscription, now=moment)

    await repository.flush()
    return ProcessedDelivery(
        delivery=delivery,
        attempt=attempt,
        status=delivery.status,
        attempts=delivery.attempts,
    )


def prepare_request(
    delivery: WebhookDelivery,
    *,
    secret: str,
    timestamp: datetime,
) -> tuple[bytes, dict[str, str]]:
    """Готовые байты тела и заголовки одной попытки.

    Тело сериализуется здесь, а не оставляется клиенту, потому что подпись считается по
    **точным байтам**, которые уйдут в сеть. Позволив HTTP-клиенту сериализовать словарь
    самому, мы получили бы подпись, которая иногда сходится, а иногда нет — в
    зависимости от того, как он расставил пробелы.
    """
    body = json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    moment = int(timestamp.timestamp())
    headers = {
        "Content-Type": "application/json",
        DELIVERY_HEADER: str(delivery.id),
        EVENT_HEADER: delivery.event_type,
        TIMESTAMP_HEADER: str(moment),
        SIGNATURE_HEADER: sign(secret, moment, body),
    }
    return body, headers


async def disable_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    now: datetime | None = None,
    reason: str = DISABLED_BY_FAILURES,
) -> None:
    """Гасит подписку и её ожидающие задания.

    Задания гасятся вместе с подпиской намеренно: оставить их значило бы продолжать
    жечь таймауты доставщика на адресе, который только что признали мёртвым. В журнале
    они остаются со статусом `failed` и причиной — исчезнуть молча им нельзя.
    """
    moment = now or datetime.now(UTC)
    subscription.is_enabled = False
    subscription.disabled_at = moment
    subscription.disabled_reason = reason
    logger.warning(
        "Webhook subscription %s (%s) disabled after %s consecutive failures",
        subscription.name,
        subscription.url,
        subscription.consecutive_failures,
    )
    await session.execute(
        update(WebhookDelivery)
        .where(
            WebhookDelivery.subscription_id == subscription.id,
            WebhookDelivery.status == DeliveryStatus.PENDING,
        )
        .values(status=DeliveryStatus.FAILED, last_error=CANCELLED_BY_DISABLE)
    )
