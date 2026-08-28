"""Подписки на события и персональный инбокс актора.

Две таблицы, и обе заполняются **вне** транзакции самого изменения: уведомление
рождается в воркере, из события, которое к этому моменту уже зафиксировано. Этим они
отличаются от журнала изменений и outbox — тем писать в одной транзакции с правкой
обязательно, а этим, наоборот, нельзя: пока подписчик считает адресатов, обработчик
запроса давно ответил клиенту.

## Почему у уведомления хранится готовый текст, а не ссылка на событие

Текст собирается один раз, из нагрузки события, и лежит в колонке. Соблазн хранить
только `event_id` и собирать текст при чтении силён и ошибочен: к моменту чтения задача
успела измениться, и уведомление «задача назначена на вас» прочиталось бы как «задача
назначена на Петра». История обязана показывать то, что произошло, а не то, что стало.

## Почему у уведомления есть и ссылка на задачу, и её ключ

По той же причине, что у журнала срабатываний автоматики: ссылка позволяет отобрать
инбокс по задаче, а копия ключа переживает её удаление. Каскад `SET NULL`, а не
`CASCADE`: запись «TRK-7 назначена на вас» осмысленна и после того, как TRK-7 удалили,
— а вот ссылка на несуществующую строку осмысленной уже не будет.

## Счётчик вместо десяти одинаковых записей

Десять правок одной задачи за минуту дают одну запись со `count = 10`, а не десять
писем. Склейка идёт по паре «адресат + ключ склейки» (`app/domain/notifications.py`,
`digest_key`) и только по **непрочитанным** записям: дописать событие в прочитанное
уведомление значило бы изменить то, что человек уже видел, ничем это не показав.
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
from app.domain.notifications import DeliveryChannel, SubscriptionScope

#: Совпадает с длиной типа события в outbox: значения одни и те же.
MAX_EVENT_TYPE_LENGTH = 64
MAX_OBJECT_TYPE_LENGTH = 32

#: Ключ объекта события: `TRK-123` у задачи, `TRK-123:<uuid>` у комментария и пункта
#: чеклиста. Та же длина, что у `outbox_events.object_key`.
MAX_OBJECT_KEY_LENGTH = 128

#: Ключ склейки — это тип события и ключ объекта через двоеточие, поэтому запас равен
#: сумме их длин с разделителем.
MAX_DIGEST_KEY_LENGTH = MAX_EVENT_TYPE_LENGTH + MAX_OBJECT_KEY_LENGTH + 1

#: Ключ области подписки: ключ очереди (`TRK`), проекта (`alpha`) или задачи
#: (`TRK-123`). Все три помещаются в длину ключа объекта.
MAX_SCOPE_KEY_LENGTH = 128


class Subscription(BaseModel):
    """Правило «актор X хочет получать события типа Y по объектам Z».

    Строка нужна не всегда. Автор, исполнитель, наблюдатели, упомянутые и участники
    проекта уведомляются **без** подписки — правилом из `app/domain/notifications.py`.
    Строка здесь либо расширяет набор (очередь, проект, чужая задача, весь поток), либо
    гасит роль по умолчанию (`is_enabled = false`), либо сужает её набором типов.

    Отсюда следует форма уникальности: одна строка на пару «актор + область» в канале.
    Две строки на одну область означали бы два ответа на вопрос «включено ли», и
    выигрывал бы прочитанный первым.
    """

    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        # `NULLS NOT DISTINCT` обязателен: у ролевых областей `scope_key` пуст, и без
        # него PostgreSQL считал бы такие строки различными — «я исполнитель» можно
        # было бы завести сколько угодно раз. Тот же приём, что у ключа записи
        # справочника (`app/db/models/catalog.py`).
        UniqueConstraint(
            "actor_id",
            "scope",
            "scope_key",
            "channel",
            name="uq_notification_subscriptions_actor_id_scope_scope_key_channel",
            postgresql_nulls_not_distinct=True,
        ),
        # Основной запрос подписчика: «подписки этих акторов и подписки на эти
        # объекты». Отбор идёт по области и ключу, поэтому индекс начинается с них.
        Index("ix_notification_subscriptions_scope_scope_key", "scope", "scope_key"),
        # «Мои подписки» страницами — общий порядок пагинации проекта.
        Index(
            "ix_notification_subscriptions_actor_id_created_at_id",
            "actor_id",
            "created_at",
            "id",
        ),
    )

    # Без `ondelete`: акторов не удаляют, их отключают. Подписка отключённого актора
    # остаётся видимой — иначе после возврата актора в строй её пришлось бы заводить
    # заново, не понимая, куда делась прежняя.
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    scope: Mapped[SubscriptionScope] = mapped_column(
        string_enum(SubscriptionScope, name="subscription_scope", length=16),
        nullable=False,
    )

    #: Ключ объекта области: очередь, проект или задача. NULL у ролевых областей и у
    #: подписки на весь поток — там адресовать нечего. Согласованность стережёт
    #: `validate_subscription`, а не ограничение в схеме: правило зависит от области, и
    #: CHECK пришлось бы переписывать миграцией при каждой новой области.
    scope_key: Mapped[str | None] = mapped_column(
        String(MAX_SCOPE_KEY_LENGTH),
        default=None,
        nullable=True,
    )

    #: Типы событий, которые интересуют. Пустой список означает «все»: подписка без
    #: перечисления обязана работать сразу, иначе её заведение стало бы обрядом из двух
    #: шагов.
    event_types: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    channel: Mapped[DeliveryChannel] = mapped_column(
        string_enum(DeliveryChannel, name="notification_channel", length=16),
        default=DeliveryChannel.INBOX,
        server_default=text(f"'{DeliveryChannel.INBOX.value}'"),
        nullable=False,
    )

    #: Включена ли. Выключенная строка на ролевой области — это способ **отказаться**
    #: от уведомлений по умолчанию, а не мусор: удалять её нельзя, иначе роль снова
    #: начнёт уведомлять правилом по умолчанию.
    is_enabled: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    #: Уведомлять ли о собственных действиях. По умолчанию нет: иначе агент, обновивший
    #: задачу, немедленно разбудит сам себя своим же изменением.
    notify_own_actions: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    # Ключ актора нужен подписчику на каждое событие, а `selectin` берёт всех акторов
    # выборки одним запросом и переиспользует уже загруженных.
    actor: Mapped[Actor] = relationship(lazy="selectin")


class Notification(BaseModel):
    """Запись персональной ленты: что произошло, по какому объекту и прочитано ли.

    Несёт и текст, и идентификаторы. Текст — человеку и в лог, идентификаторы
    (`event_type`, `issue_key`, `details`) — агенту: по ним он принимает решения
    программно, а не разбором строки, которую завтра перепишут.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Главный запрос инбокса: «мои непрочитанные, по порядку». Частичный индекс, а
        # не полный: прочитанные копятся вечно и в этот вопрос никогда не попадают, а
        # индекс по ним пришлось бы обновлять на каждой отметке о прочтении.
        Index(
            "ix_notifications_actor_id_created_at_id_unread",
            "actor_id",
            "created_at",
            "id",
            postgresql_where=text("NOT is_read"),
        ),
        # История целиком — второй по частоте вопрос, и предыдущий индекс на него не
        # отвечает: он не видит прочитанных.
        Index("ix_notifications_actor_id_created_at_id", "actor_id", "created_at", "id"),
        # Поиск записи для склейки: «непрочитанное уведомление этого актора с таким же
        # ключом склейки». Тоже частичный — склейка идёт только по непрочитанным.
        Index(
            "ix_notifications_actor_id_digest_key",
            "actor_id",
            "digest_key",
            postgresql_where=text("NOT is_read"),
        ),
        # «Что приходило по этой задаче» — вопрос разбора последствий.
        Index("ix_notifications_issue_id", "issue_id"),
        CheckConstraint("count >= 1", name="count_is_positive"),
    )

    # Без `ondelete`: акторов не удаляют. Инбокс отключённого актора остаётся читаемым.
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    event_type: Mapped[str] = mapped_column(String(MAX_EVENT_TYPE_LENGTH), nullable=False)

    #: Событие, из которого собрано уведомление; при склейке — последнее из них.
    #: Без внешнего ключа, по той же причине, по которой его нет у журнала срабатываний
    #: автоматики: строка outbox переживает удалённую задачу, но обратных гарантий нет,
    #: а чистка старых событий однажды появится.
    event_id: Mapped[uuid.UUID | None] = mapped_column(default=None, nullable=True)

    object_type: Mapped[str] = mapped_column(String(MAX_OBJECT_TYPE_LENGTH), nullable=False)
    object_key: Mapped[str] = mapped_column(String(MAX_OBJECT_KEY_LENGTH), nullable=False)

    #: Задача, к которой относится уведомление. NULL у событий проекта, портфеля, доски
    #: и у массового переноса статусов — задачи у них нет вовсе, а не «не нашлась».
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"),
        default=None,
        nullable=True,
    )
    issue_key: Mapped[str | None] = mapped_column(
        String(MAX_OBJECT_KEY_LENGTH),
        default=None,
        nullable=True,
    )

    #: Ключ склейки повторов. Считается доменом из типа события и ключа объекта.
    digest_key: Mapped[str] = mapped_column(String(MAX_DIGEST_KEY_LENGTH), nullable=False)

    #: Готовый текст. Пересобирать его при чтении нельзя — см. шапку модуля.
    body: Mapped[str] = mapped_column(Text, nullable=False)

    #: Идентификаторы для программных решений агента: ключ задачи, статус, исполнитель,
    #: список изменённых полей. Свободная форма здесь законна по той же причине, что у
    #: `values` задачи: набор зависит от типа события и типом не описывается.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    #: Сколько событий склеено в эту запись. Единица у обычного уведомления.
    count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )

    is_read: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)

    # Отметка времени идёт вперёд внутри транзакции — то же отступление от
    # `TimestampsMixin`, что у журнала изменений, outbox и журнала срабатываний.
    # Событие с десятком адресатов кладёт в инбокс десяток строк одной транзакцией: с
    # `now()` все они получили бы одну отметку, и курсорная пагинация по паре
    # `(created_at, id)` выродилась бы в сортировку по случайным UUID.
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    actor: Mapped[Actor] = relationship(lazy="selectin")
