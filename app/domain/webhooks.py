"""Вебхуки: области подписки, полезная нагрузка доставки и её подпись.

Чистый Python: ни ORM, ни HTTP. Здесь живёт то, что обязано быть одинаковым у
подписчика шины, у доставщика и у схем API, — иначе три механики начнут понимать одну
и ту же подписку по-разному.

## Область считается из той же аудитории, что и у инбокса

`audience_of` из `app/domain/notifications.py` уже отвечает на вопрос «к каким объектам
относится событие», разбирая **нагрузку** и не заходя в базу. Вебхуку нужен тот же
ответ, и второй реализации заводить нельзя: два разбора одной нагрузки однажды
истолкуют её по-разному. Поэтому `matches_scope` принимает готовую `EventAudience`, а
не полезную нагрузку.

Ролевых областей у вебхука нет и быть не может. «Я исполнитель» — свойство актора, а у
адреса актора нет: подписка описывает **поток**, а не персональную ленту. Отсюда своё
перечисление на три значения вместо `SubscriptionScope`, у которого их девять.

## Подпись покрывает время, а не только тело

Подписывается строка `<timestamp>.<тело>`, а не одно тело. Подпись только по телу
позволяет переиграть перехваченную доставку через сутки: тело и подпись сходятся, и
получателю нечем отличить повтор от свежего вызова. Со временем внутри подписи
получатель отвергает доставку, пришедшую слишком поздно, — и это единственный способ
дать ему такую возможность, потому что подделать заголовок времени иначе ничего не
мешает.

## Доставка идёт минимум один раз, а не ровно один

Повтор после сетевого таймаута неизбежен: ответ мог потеряться уже после того, как
получатель сделал работу. Поэтому у каждой доставки есть неизменный идентификатор
(`X-Tracker-Delivery`), и получатель обязан распознавать по нему повтор сам. Обещать
«ровно один раз» здесь было бы враньём, которое обнаружится в первый же сетевой сбой.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from app.domain.errors import InvalidWebhookSubscriptionError
from app.domain.event_stream import build_event_view
from app.domain.notifications import KNOWN_EVENT_TYPES, EventAudience

#: Префикс секрета подписи. Как у токена доступа: секрет должен быть узнаваем в логах и
#: в переменных окружения получателя, чтобы его не приняли за что-то безобидное.
SECRET_PREFIX = "whsec_"

#: 32 байта энтропии — 256 бит, столько же, сколько у токена доступа. Медленная функция
#: вывода ключа здесь не нужна и вредна: секрет участвует в HMAC на каждой доставке.
SECRET_ENTROPY_BYTES = 32

#: Границы секрета, заданного вручную. Короткий секрет ослабляет подпись, а длинный
#: HMAC всё равно свернёт до размера блока — смысла принимать килобайт нет.
MIN_SECRET_LENGTH = 16
MAX_SECRET_LENGTH = 256

#: Потолок адреса. 2048 — исторический предел, который держат все прокси и логи; более
#: длинный адрес всё равно не переживёт дорогу до получателя целиком.
MAX_URL_LENGTH = 2048

#: Имя подписки: по нему её адресует правило автоматики (`ctx.webhook`). Ограничение
#: то же, что у ключа правила, — имя пишется в параметры правила и в журнал.
MAX_NAME_LENGTH = 64

#: Схемы, по которым доставку вообще можно отправить.
ALLOWED_SCHEMES = ("http", "https")

#: Заголовки доставки. Имена — часть контракта с получателем: переименование ломает
#: проверку подписи на той стороне так же, как переименование кода ошибки ломает фронт.
DELIVERY_HEADER = "X-Tracker-Delivery"
EVENT_HEADER = "X-Tracker-Event"
TIMESTAMP_HEADER = "X-Tracker-Timestamp"
SIGNATURE_HEADER = "X-Tracker-Signature"

#: Алгоритм в самом значении подписи. Без него смена алгоритма стала бы ломающим
#: изменением без всякого признака: получатель считал бы новую подпись старым способом.
SIGNATURE_ALGORITHM = "sha256"

#: Потолок текста ошибки в журнале доставок. Тот же, что у `outbox_events.last_error`.
MAX_ERROR_LENGTH = 1000

#: Тип «события» у доставки, поставленной правилом автоматики (`ctx.webhook`). Строка в
#: том же пространстве имён, что и `EventType`, но членом его не является намеренно:
#: событием шины она не становится, в outbox не попадает и подписчиков не будит. Тот же
#: приём, что у `DIRECT_EVENT_TYPE` адресного уведомления.
DIRECT_EVENT_TYPE = "webhook.direct"

#: Типы, которые можно перечислить в подписке: словарь шины плюс адресный вызов из
#: правила. Опечатка иначе дала бы подписку, которая молча никогда не срабатывает.
#:
#: Адресный вызов включён в фильтр наравне с остальными намеренно. Подписка, которой
#: нужны только вызовы правил (адрес CI, дёргаемый релизным макросом), выражается как
#: `event_types: ["webhook.direct"]`; без этого такой адрес получал бы весь поток
#: событий установки в придачу.
SUBSCRIBABLE_EVENT_TYPES: frozenset[str] = KNOWN_EVENT_TYPES | {DIRECT_EVENT_TYPE}

#: Вид объекта у адресного вызова, сделанного правилом без задачи (автодействие,
#: работающее с очередью целиком). Колонка `object_key` не пуста никогда: журнал
#: доставок обязан отвечать «по поводу чего», и «по поводу правила X» — законный ответ.
DIRECT_OBJECT_TYPE = "rule"


class WebhookScope(StrEnum):
    """Какой поток событий уходит на адрес.

    Три значения, и ролевых среди них нет: у адреса нет актора, поэтому вопрос «кем я
    прихожусь этому событию» для вебхука не имеет смысла. Подписка описывает поток —
    весь, очереди или проекта.
    """

    #: Весь поток событий установки. Ключа не требует.
    ALL = "all"
    QUEUE = "queue"
    #: Проект и портфель — одна область на оба вида, как и у подписки инбокса: ключ
    #: проекта виден в снимке задачи, и отбирать его можно, не заходя в базу.
    PROJECT = "project"


#: Области, адресующие объект и потому требующие ключа.
TARGET_SCOPES: frozenset[WebhookScope] = frozenset({WebhookScope.QUEUE, WebhookScope.PROJECT})


class DeliveryStatus(StrEnum):
    """Состояние одной доставки.

    Три значения, и `pending` означает и «ещё не пробовали», и «ждём следующей
    попытки»: различать их отдельным статусом нечем — момент следующей попытки лежит в
    `available_at`, а число сделанных в `attempts`, и второй статус лишь дал бы два
    источника правды об одном и том же.
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


def generate_secret() -> str:
    """Новый секрет подписи. Возвращается вызывающему один раз, при создании подписки."""
    return f"{SECRET_PREFIX}{secrets.token_urlsafe(SECRET_ENTROPY_BYTES)}"


def validate_subscription(
    *,
    url: str,
    scope: WebhookScope,
    scope_key: str | None,
    event_types: Iterable[str] | None,
    secret: str | None,
) -> tuple[str, str | None, list[str], str]:
    """Проверяет описание подписки и возвращает канонические адрес, ключ, типы и секрет.

    Четыре правила, и каждое ловит свою молчаливую ошибку:

    - адрес не по HTTP — доставка никогда не уйдёт, а подписка выглядит рабочей;
    - предметная область без ключа отбирает весь поток, а не очередь `TRK`;
    - область без ключа с ключом выглядит настроенной, хотя ключ нигде не читается;
    - неизвестный тип события — опечатка, дающая подписку, которая никогда не
      срабатывает. Отличить такую от исправной, глядя на неё, невозможно.

    Секрет не проверяется на «сложность»: сгенерированный нами и так случаен, а
    заданный вручную обязан совпадать с тем, что уже прошит у получателя, — отвергать
    его за форму значило бы запрещать подключение к существующей системе.
    """
    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise InvalidWebhookSubscriptionError(
            details={
                "field": "url",
                "reason": "unsupported",
                "allowed_schemes": list(ALLOWED_SCHEMES),
            },
        )

    normalized_key = None if scope_key is None else scope_key.strip()
    if scope in TARGET_SCOPES and not normalized_key:
        raise InvalidWebhookSubscriptionError(
            details={
                "field": "scope_key",
                "reason": "required",
                "scope": scope.value,
                "scopes_with_key": sorted(item.value for item in TARGET_SCOPES),
            },
        )
    if scope not in TARGET_SCOPES and normalized_key:
        raise InvalidWebhookSubscriptionError(
            details={"field": "scope_key", "reason": "not_applicable", "scope": scope.value},
        )

    types = sorted({item.strip() for item in event_types or () if item.strip()})
    unknown = [item for item in types if item not in SUBSCRIBABLE_EVENT_TYPES]
    if unknown:
        raise InvalidWebhookSubscriptionError(
            details={"field": "event_types", "reason": "unknown", "unknown": unknown},
        )

    resolved_secret = (secret or "").strip() or generate_secret()
    if not MIN_SECRET_LENGTH <= len(resolved_secret) <= MAX_SECRET_LENGTH:
        raise InvalidWebhookSubscriptionError(
            details={
                "field": "secret",
                "reason": "out_of_range",
                "min_length": MIN_SECRET_LENGTH,
                "max_length": MAX_SECRET_LENGTH,
            },
        )

    return normalized_url, (normalized_key or None), types, resolved_secret


def matches_scope(
    scope: WebhookScope,
    scope_key: str | None,
    audience: EventAudience,
) -> bool:
    """Относится ли событие к области подписки.

    Аудитория считается доменом уведомлений по нагрузке события — второй разбор той же
    нагрузки здесь заводить нельзя.
    """
    if scope is WebhookScope.ALL:
        return True
    if scope is WebhookScope.QUEUE:
        return scope_key is not None and audience.queue_key == scope_key
    return scope_key is not None and scope_key in audience.project_keys


def matches_event_type(subscribed: Iterable[str], event_type: str) -> bool:
    """Проходит ли событие фильтр подписки. Пустой набор означает «все типы».

    Пустой набор — именно «все»: вебхуку и SSE обычно нужен весь поток, и заведение
    подписки в два шага (создать, потом перечислить типы) стало бы обязательным
    обрядом. То же правило, что у подписки инбокса.
    """
    types = tuple(subscribed)
    return not types or event_type in types


def build_payload(
    *,
    delivery_id: str,
    event_id: str | None,
    event_type: str,
    object_type: str,
    object_key: str,
    actor_key: str,
    occurred_at: datetime,
    payload: Mapping[str, Any],
    audience: EventAudience,
) -> dict[str, Any]:
    """Тело доставки: событие и ключевые поля, а не дамп задачи целиком.

    Форма собирается общей функцией (`app/domain/event_stream.py`), той же, которой
    пользуется SSE: одно событие обязано выглядеть одинаково у внешнего подписчика и у
    фронтенда. Снимок задачи со всеми кастомными полями в неё не входит намеренно —
    вебхук уходит на чужую сторону, и объём полезной нагрузки там становится объёмом
    утечки.

    `delivery` не совпадает с `event`: одно событие уходит на несколько адресов, и у
    каждой доставки свой идентификатор. Дедупликацию получатель ведёт по `delivery`,
    порядок восстанавливает по `event.id`.
    """
    return {
        "delivery": delivery_id,
        **build_event_view(
            event_id=event_id,
            event_type=event_type,
            object_type=object_type,
            object_key=object_key,
            actor_key=actor_key,
            occurred_at=occurred_at,
            payload=payload,
            audience=audience,
        ),
    }


def build_direct_payload(
    *,
    delivery_id: str,
    actor_key: str,
    occurred_at: datetime,
    object_type: str,
    object_key: str,
    issue_key: str | None,
    body: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Тело вызова, поставленного правилом автоматики.

    Форма та же, что у доставки из события, и это обязательное свойство: получатель
    разбирает любой вызов одним и тем же кодом. Отличают адресный вызов два поля —
    `event.type` равен `webhook.direct`, а `event.id` пуст, потому что события шины за
    ним нет.
    """
    return {
        "delivery": delivery_id,
        "event": {
            "id": None,
            "type": DIRECT_EVENT_TYPE,
            "actor": actor_key,
            "occurred_at": occurred_at.isoformat(),
        },
        "object": {"type": object_type, "key": object_key},
        "issue": issue_key,
        "queue": None,
        "projects": [],
        "summary": body,
        "details": dict(details or {}),
    }


def signature_base(timestamp: int, body: bytes) -> bytes:
    """Строка, которую покрывает подпись: время и тело через точку.

    Ровно та же сборка обязана быть у получателя, поэтому она вынесена в отдельную
    функцию и описана в документации подписки: собранная «почти так же» строка даёт
    подпись, которая не сходится, и отладить это по коду ответа невозможно.
    """
    return str(timestamp).encode("ascii") + b"." + body


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Подпись тела доставки: `sha256=<hex>`.

    Алгоритм едет в самом значении. Без него смена алгоритма стала бы ломающим
    изменением без единого признака: получатель продолжил бы считать подпись по-старому
    и отвергал бы каждую доставку.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        signature_base(timestamp, body),
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_ALGORITHM}={digest}"


def verify(secret: str, timestamp: int, body: bytes, signature: str) -> bool:
    """Сходится ли подпись. Нужна тестам и получателю на этой же кодовой базе.

    Сравнение — `compare_digest`, а не `==`: обычное сравнение строк выходит из цикла
    на первом несовпавшем символе, и по времени ответа подпись подбирается побайтно.
    """
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


def masked_secret(secret: str) -> str:
    """Секрет в виде, пригодном для показа: только хвост, всё остальное скрыто.

    Полный секрет отдаётся ровно один раз — в ответе на создание подписки. Дальше он
    нужен только для сборки подписи, а в списке подписок его показ означал бы, что
    любой читатель API уносит с собой ключ ко всем будущим доставкам.

    Начало не показывается вовсе, и это не перестраховка. Подставлять сюда `whsec_`
    было бы прямым враньём: секрет, заданный вручную под уже работающего получателя,
    этого префикса не имеет, — а показывать четыре реальных первых символа значит
    отдать четверть короткого секрета. Хвоста хватает ровно на то, ради чего маска и
    нужна: отличить один секрет от другого при ротации.
    """
    tail = secret[-4:] if len(secret) > 4 else ""
    return f"…{tail}" if tail else "…"
