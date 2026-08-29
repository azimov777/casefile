"""Подписки вебхуков и журнал доставок наружу.

Две таблицы, и вторая — очередь заданий, а не отчёт. Подписчик шины кладёт в неё
строку и на этом заканчивает; HTTP-запрос делает отдельный процесс
(`app/webhooks.py`). Разделение не косметическое: воркер событий обрабатывает очередь
по одному событию, и подписчик, ждущий таймаута мёртвого адреса, остановил бы доставку
всем остальным — и уведомлениям, и автоматике.

## Почему повторы вебхука отдельны от повторов события

У шины повтор идёт по **событию** и только по упавшим подписчикам. Если бы вебхук
повторял себя на этом уровне, одно событие уходило бы на живые адреса столько раз,
сколько раз упал мёртвый. Поэтому здесь свой счётчик попыток — по конкретной доставке
на конкретный адрес.

## Почему адрес хранится в доставке, а не только в подписке

Адрес подписки меняют. Журнал обязан отвечать, куда вызов ушёл **тогда**, а не куда
уходит сейчас: разбор инцидента «получатель не получил» начинается именно с этого
вопроса. Та же причина, по которой у уведомления хранится готовый текст, а не ссылка
на событие.

## Почему удаление подписки уносит её журнал

`ON DELETE CASCADE`. Журнал доставок описывает работу конкретного адреса, и в отрыве от
подписки отвечать ему не на что: адреса больше нет, повторить нечего, а строки с
секретом от несуществующего получателя — просто мусор. Это отличается от журнала
срабатываний автоматики, где строка правила намеренно переживает удаление правила из
кода: правило удаляют выкладкой, а подписку — руками и осознанно.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.actor import Actor
from app.domain.webhooks import (
    MAX_NAME_LENGTH,
    MAX_URL_LENGTH,
    DeliveryStatus,
    WebhookScope,
)

#: Совпадает с длиной типа события в outbox: значения одни и те же.
MAX_EVENT_TYPE_LENGTH = 64
MAX_OBJECT_TYPE_LENGTH = 32

#: Ключ объекта события: `TRK-123` у задачи, `TRK-123:<uuid>` у комментария.
MAX_OBJECT_KEY_LENGTH = 128

#: Ключ области: ключ очереди (`TRK`) или проекта (`alpha`). Оба помещаются сюда.
MAX_SCOPE_KEY_LENGTH = 128

#: Секрет подписи: хватает и сгенерированному нами, и заданному вручную.
MAX_SECRET_LENGTH = 256

#: Причина, по которой подписка выключена автоматически. Короткий стабильный код, а не
#: фраза: по нему клиент решает, что показать, и он же ищется в логах.
MAX_DISABLED_REASON_LENGTH = 64


class WebhookSubscription(BaseModel):
    """Адрес, на который уходит поток событий, и всё, что нужно для его доставки.

    Своя модель, а не канал у подписки инбокса. Подписка уведомлений описывает, *что*
    интересует актора; вебхуку нужны ещё адрес, секрет и журнал доставок, которых у неё
    нет и быть не должно. Ролевых областей здесь тоже нет: у адреса нет актора, и
    вопрос «кем я прихожусь этому событию» для него бессмыслен.
    """

    __tablename__ = "webhook_subscriptions"
    __table_args__ = (
        # Имя уникально на всю установку, потому что по нему подписку адресует правило
        # автоматики. Два адреса под одним именем означали бы правило, отправляющее
        # вызов туда, куда сегодня решит порядок строк в выборке.
        UniqueConstraint("name", name="uq_webhook_subscriptions_name"),
        # Основной запрос подписчика шины: «включённые подписки на весь поток, на эту
        # очередь или на эти проекты». Отбор идёт по области и ключу.
        Index("ix_webhook_subscriptions_scope_scope_key", "scope", "scope_key"),
        # Список подписок страницами — общий порядок пагинации проекта.
        Index("ix_webhook_subscriptions_created_at_id", "created_at", "id"),
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_not_negative"),
    )

    #: Человекочитаемое имя. Им подписку адресует правило автоматики (`ctx.webhook`) —
    #: параметры правила настраивают люди, и идентификатор UUID в них нечитаем.
    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)

    url: Mapped[str] = mapped_column(String(MAX_URL_LENGTH), nullable=False)

    #: Секрет подписи хранится **как есть**, а не хешем, — в отличие от токена доступа.
    #: Разница принципиальна: токен мы проверяем (хватает хеша), а подпись доставки
    #: собираем сами, и для HMAC нужен исходный секрет. Отсюда правило: наружу он
    #: отдаётся ровно один раз, в ответе на создание подписки.
    secret: Mapped[str] = mapped_column(String(MAX_SECRET_LENGTH), nullable=False)

    scope: Mapped[WebhookScope] = mapped_column(
        string_enum(WebhookScope, name="webhook_scope", length=16),
        default=WebhookScope.ALL,
        server_default=text(f"'{WebhookScope.ALL.value}'"),
        nullable=False,
    )

    #: Ключ очереди или проекта. NULL у подписки на весь поток. Согласованность стережёт
    #: `validate_subscription`, а не CHECK: правило зависит от области, и ограничение
    #: пришлось бы переписывать миграцией при каждой новой.
    scope_key: Mapped[str | None] = mapped_column(
        String(MAX_SCOPE_KEY_LENGTH),
        default=None,
        nullable=True,
    )

    #: Типы событий, которые уходят на адрес. Пустой список означает «все» — вебхуку
    #: обычно нужен весь поток, и подписка без перечисления обязана работать сразу.
    event_types: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    is_enabled: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    #: Неудачных доставок подряд. Успех обнуляет счётчик, а не уменьшает: подписка,
    #: у которой каждая вторая доставка падает, — это работающий получатель с потерями,
    #: и гасить его нельзя. Гасить надо тот адрес, который не отвечает вообще.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    #: Когда и почему подписка выключена автоматически. NULL у выключенной руками:
    #: различать эти два случая обязательно, иначе «мой вебхук молчит» невозможно
    #: объяснить, не поднимая журнал доставок целиком.
    disabled_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(
        String(MAX_DISABLED_REASON_LENGTH),
        default=None,
        nullable=True,
    )

    # Без `ondelete`: акторов не удаляют, их отключают. Автор подписки остаётся видимым
    # и после того, как ушёл, — иначе разбор «кто это завёл» упирается в NULL.
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    created_by: Mapped[Actor] = relationship(lazy="selectin")


class WebhookDelivery(BaseModel):
    """Задание на доставку и одновременно запись журнала.

    Одна таблица на очередь и на историю, а не две. Разделение означало бы перенос
    строки между ними при завершении — то есть момент, в который доставка не лежит ни
    там, ни там, если процесс умрёт посередине. Здесь же завершение — это смена
    статуса, и потерять строку невозможно.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # Выборка доставщика целиком: «ожидающие, которым пришло время», по порядку.
        Index(
            "ix_webhook_deliveries_status_available_at_created_at",
            "status",
            "available_at",
            "created_at",
        ),
        # Журнал одной подписки страницами — главный вопрос разбора инцидента.
        Index(
            "ix_webhook_deliveries_subscription_id_created_at_id",
            "subscription_id",
            "created_at",
            "id",
        ),
        # Общий журнал страницами: тот же порядок, что у всех коллекций проекта.
        Index("ix_webhook_deliveries_created_at_id", "created_at", "id"),
        # «Куда ушло это событие» — второй вопрос разбора, и предыдущие индексы на него
        # не отвечают: они начинаются с подписки и со времени.
        Index("ix_webhook_deliveries_event_id", "event_id"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Событие шины, из которого собрана доставка. Без внешнего ключа — по той же
    #: причине, что и у уведомления: строка outbox переживает удалённую задачу, но
    #: обратных гарантий нет, а чистка старых событий однажды появится. NULL у вызова,
    #: поставленного правилом автоматики: события шины у него нет вовсе.
    event_id: Mapped[uuid.UUID | None] = mapped_column(default=None, nullable=True)

    event_type: Mapped[str] = mapped_column(String(MAX_EVENT_TYPE_LENGTH), nullable=False)
    object_type: Mapped[str] = mapped_column(String(MAX_OBJECT_TYPE_LENGTH), nullable=False)
    object_key: Mapped[str] = mapped_column(String(MAX_OBJECT_KEY_LENGTH), nullable=False)

    #: Адрес на момент постановки задания: см. шапку модуля.
    url: Mapped[str] = mapped_column(String(MAX_URL_LENGTH), nullable=False)

    #: Готовое тело запроса. Собирается один раз, при постановке, и больше не меняется:
    #: повтор обязан отправить ровно то же, что и первая попытка, иначе получатель,
    #: сравнивающий доставки по идентификатору, увидит два разных содержимого под одним.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    status: Mapped[DeliveryStatus] = mapped_column(
        string_enum(DeliveryStatus, name="webhook_delivery_status", length=16),
        default=DeliveryStatus.PENDING,
        server_default=text(f"'{DeliveryStatus.PENDING.value}'"),
        nullable=False,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    #: Когда доставку можно брать в работу: сразу у новой, после нарастающей паузы у
    #: повторяемой.
    available_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    #: Код ответа последней попытки. NULL означает, что ответа не было вовсе —
    #: таймаут, отказ соединения, неразрешённое имя. Различать это обязательно: «500 от
    #: получателя» и «адрес не отвечает» чинятся в разных местах.
    response_status: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)

    delivered_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)

    # Отметка времени идёт вперёд внутри транзакции — то же отступление от
    # `TimestampsMixin`, что у outbox и инбокса: одно событие кладёт задания сразу на
    # несколько адресов одной транзакцией, и с `now()` все они получили бы одну отметку,
    # а курсорная пагинация выродилась бы в сортировку по случайным UUID.
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    subscription: Mapped[WebhookSubscription] = relationship(lazy="selectin")
