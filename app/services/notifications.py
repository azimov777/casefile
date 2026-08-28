"""Сценарии уведомлений: раскладка события по инбоксам, чтение ленты, подписки, ожидание.

## Кто получит событие

Считается в три шага, и каждый отвечает за своё.

1. **Аудитория** — кто причастен к событию и к каким объектам оно относится. Считает
   домен, из полезной нагрузки события и ничего больше (`app/domain/notifications.py`).
2. **Подписки** — одним запросом достаются подписки причастных на ролевые области и
   подписки кого угодно на объекты события.
3. **Решение** — по каждому кандидату: роль по умолчанию уведомляет, если её не
   выключили подпиской; область из подписки уведомляет, если подписка включена; тип
   события обязан пройти фильтр подписки, если тот задан.

## Кого не уведомляем никогда

Системного актора. Правила автоматики выполняются от его имени, и он же оказывается
инициатором цепочек — без этого отсечения его инбокс собрал бы копию всего потока
событий установки. Это не настройка: инбокс системного актора никто не читает.

Инициатора события — по умолчанию. Иначе агент, обновивший задачу, немедленно разбудит
сам себя своим же изменением. Отключается подпиской (`notify_own_actions`), потому что
человеку, ведущему задачу с двух устройств, это как раз бывает нужно.

Важное следствие, которое легко сломать: комментарий автоматики приходит обычным
`comment.created` от системного актора. Правило «не уведомлять о собственных действиях»
глушит его **только самому системному актору** — а он и так исключён. Всем остальным
сообщение доходит, и это главный способ, которым автоматика разговаривает с человеком.

## Транзакция

Сценарии не фиксируют: границу держит вход в приложение. Подписчик шины работает внутри
вложенной транзакции воркера, и его падение откатывает только его собственные записи.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.notification import Notification, Subscription
from app.db.pagination import Page
from app.db.repositories import (
    ActorRepository,
    NotificationRepository,
    SubscriptionRepository,
)
from app.db.wakeup import hub
from app.db.wakeup import notify as wake_up
from app.domain.actors import SYSTEM_ACTOR_KEY
from app.domain.errors import (
    InvalidWaitTimeoutError,
    NotificationNotFoundError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from app.domain.notifications import (
    DEFAULT_NOTIFY_OWN_ACTIONS,
    DEFAULT_ROLE_SCOPES,
    DIRECT_EVENT_TYPE,
    ROLE_SCOPES,
    SCOPE_PRIORITY,
    DeliveryChannel,
    EventAudience,
    NotificationSummary,
    SubscriptionScope,
    audience_of,
    describe,
    digest_key,
    matches_event_type,
    object_type_of,
    validate_subscription,
)
from app.services.event_bus import EventEnvelope
from app.services.permissions import ensure_allowed

logger = get_logger("notifications")


@dataclass(frozen=True, slots=True)
class InboxWait:
    """Итог ожидания: что пришло, сколько ждали и дождались ли.

    `timed_out` — не ошибка, а нормальный исход: клиент MCP обязан отличать «ничего не
    пришло за отведённое время» от сбоя, и по коду ответа этого не понять — он в обоих
    случаях успешный.
    """

    notifications: list[Notification] = field(default_factory=list)
    waited: float = 0.0
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class _Recipient:
    """Кандидат в адресаты: актор, чем он причастен и какая подписка это разрешила."""

    actor: Actor
    scope: SubscriptionScope
    subscription: Subscription | None


# --- Раскладка события по инбоксам --------------------------------------------------


async def dispatch_event(session: AsyncSession, event: EventEnvelope) -> list[Notification]:
    """Раскладывает одно событие по инбоксам подписчиков.

    Зовётся подписчиком шины из воркера. Возвращает созданные и дополненные записи —
    тестам и логу; вызывающему коду результат не нужен.

    Массовый перенос задач между статусами (`status.issues_moved`) приходит **одним**
    событием на всю операцию, и разворачивать его обратно в уведомление на каждую
    задачу нельзя: ради этого схлопывания оно и делалось. Отдельной ветки для него
    здесь нет и не нужно — у события просто нет задачи, а ключи перенесённых лежат в
    подробностях уведомления.
    """
    audience = audience_of(event.event_type, event.payload)
    recipients = await _resolve_recipients(
        session,
        audience=audience,
        event_type=event.event_type,
        initiator_key=event.actor_key,
    )
    if not recipients:
        return []

    summary = describe(event.event_type, event.payload)
    created = [
        await _store(
            session,
            actor=recipient.actor,
            event_type=event.event_type,
            event_id=event.id,
            object_type=event.object_type,
            object_key=event.object_key,
            issue_key=audience.issue_key,
            issue_id=_as_uuid(audience.issue_id),
            summary=summary,
            reason=recipient.scope,
            merge=True,
        )
        for recipient in recipients
    ]
    await wake_up(session, [recipient.actor.key for recipient in recipients])
    return created


async def notify_actor(
    session: AsyncSession,
    *,
    actor: Actor,
    body: str,
    details: dict[str, object] | None = None,
    issue: Issue | None = None,
) -> Notification | None:
    """Кладёт уведомление в инбокс адресно, минуя подписки.

    Нужна правилу автоматики: «предупредить исполнителя, что дедлайн завтра» — это
    адресное сообщение, а не следствие изменения, и подписки к нему отношения не имеют.
    Свою механику адресации правило не строит — оно называет актора, а всё остальное
    делает этот сценарий.

    Возвращает `None`, если адресат — системный актор: его инбокс никто не читает, и
    записать туда сообщение значило бы потерять его молча. Вызывающий код обязан
    показать этот исход (правило пишет его в журнал срабатываний).
    """
    if actor.key == SYSTEM_ACTOR_KEY:
        return None

    summary = NotificationSummary(body=body, details=dict(details or {}))
    notification = await _store(
        session,
        actor=actor,
        event_type=DIRECT_EVENT_TYPE,
        event_id=None,
        object_type=object_type_of(DIRECT_EVENT_TYPE),
        object_key="-" if issue is None else issue.key,
        issue_key=None if issue is None else issue.key,
        issue_id=None if issue is None else issue.id,
        summary=summary,
        reason=None,
        # Адресные сообщения не склеиваются между собой, и это не мелочь. У них общий
        # ключ склейки (тип «событие» один, задача часто та же), но содержание разное:
        # «дедлайн завтра» и «правило вернуло задачу в бэклог» — два разных сообщения,
        # и склейка оставила бы от них одно, потеряв второе молча.
        merge=False,
    )
    await wake_up(session, [actor.key])
    return notification


# --- Чтение инбокса -----------------------------------------------------------------


async def list_notifications(
    session: AsyncSession,
    *,
    initiator: Actor,
    is_read: bool | None = None,
    issue: Issue | None = None,
    event_type: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Notification]:
    """Страница инбокса текущего актора, от старого к новому.

    Чужой инбокс не читается вовсе — ни владельцем, ни агентом. В v1 ролевой модели
    нет, и соблазн разрешить «посмотреть чужие уведомления» велик; но лента — это
    рабочая очередь конкретного актора, и вычитать её со стороны означало бы отмечать
    прочитанным то, чего адресат не видел.
    """
    ensure_allowed(initiator, "notification.list")
    return await NotificationRepository(session).list_page_for_actor(
        initiator.id,
        is_read=is_read,
        issue_id=None if issue is None else issue.id,
        event_type=event_type,
        limit=limit,
        cursor=cursor,
    )


async def count_unread(session: AsyncSession, *, initiator: Actor) -> int:
    """Сколько непрочитанных в инбоксе текущего актора."""
    ensure_allowed(initiator, "notification.list")
    return await NotificationRepository(session).count_unread(initiator.id)


async def mark_read(
    session: AsyncSession,
    *,
    initiator: Actor,
    notification_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Отмечает прочитанными перечисленные уведомления или весь инбокс.

    `None` означает «все непрочитанные». Отмечать по одному агент, разобравший ленту
    целиком, не должен: идентификаторы ему пришлось бы собирать отдельным запросом
    ровно для того, чтобы отдать их обратно.

    Возвращает число фактически отмеченных. Уже прочитанные в него не попадают, и
    повторный вызов отвечает нулём — это не ошибка: клиент, не получивший ответ и
    повторивший запрос, не должен получать отказ на выполненное действие.
    """
    ensure_allowed(initiator, "notification.read")
    if notification_ids is not None:
        # Чужой идентификатор в списке — не «отметить чужое», а `not_found`: клиент
        # обязан узнать, что промахнулся, а не получить успех, ничего не отметив.
        await _ensure_own(session, initiator, notification_ids)
    return await NotificationRepository(session).mark_read(
        initiator.id,
        notification_ids=notification_ids,
        moment=datetime.now(UTC),
    )


# --- Ожидание -----------------------------------------------------------------------


async def wait_for_notifications(
    session: AsyncSession,
    *,
    initiator: Actor,
    timeout: float | None = None,
    limit: int | None = None,
) -> InboxWait:
    """Ждёт непрочитанных уведомлений и возвращает их, как только они появились.

    Основа инструмента ожидания в MCP. Три уровня оповещения описаны в
    `app/db/wakeup.py`; здесь — цикл, который ими пользуется:

    1. зарегистрироваться ожидающим **до** первой проверки, иначе уведомление,
       появившееся между проверкой и подпиской, никого не разбудит;
    2. проверить инбокс — возможно, ждать уже нечего;
    3. заснуть до оповещения или до контрольного опроса, что раньше.

    Транзакция на время сна закрывается, и это обязательно. Ожидание длится десятки
    секунд, а соединение из пула всё это время держало бы открытый снимок: пять
    ждущих агентов исчерпали бы пул, и остальной API встал бы. Терять при этом нечего
    — сценарий только читает.

    Пустой ответ по таймауту — не ошибка. Отличить «ничего не пришло» от сбоя клиент
    обязан по полю `timed_out`, а не по коду ответа, который в обоих случаях успешен.
    """
    ensure_allowed(initiator, "notification.wait")
    settings = get_settings()
    deadline_seconds = _resolve_timeout(timeout, settings.notification_wait_max_timeout)
    repository = NotificationRepository(session)

    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + deadline_seconds

    if not hub.is_listening:
        # Не предупредить нельзя: без слушателя ожидание работает контрольным опросом,
        # и «уведомления приходят с задержкой в две секунды» иначе объяснить нечем.
        logger.debug("Inbox wait runs without the PostgreSQL listener; polling instead")

    async with hub.waiting_for(initiator.key) as woken:
        while True:
            page = await repository.list_page_for_actor(
                initiator.id,
                is_read=False,
                limit=limit,
            )
            if page.items:
                return InboxWait(
                    notifications=page.items,
                    waited=loop.time() - started,
                    timed_out=False,
                )

            remaining = deadline - loop.time()
            if remaining <= 0:
                return InboxWait(waited=loop.time() - started, timed_out=True)

            # Соединение отпускается на время сна. `commit`, а не `rollback`: сценарий
            # ничего не менял, но откат в середине запроса выглядел бы как отмена
            # чего-то, чего не было.
            await session.commit()
            woken.clear()
            # Истёкшая пауза — это не сбой, а наступивший контрольный опрос: цикл
            # перечитает инбокс и решит сам, ждать ли дальше.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    woken.wait(),
                    timeout=min(remaining, settings.notification_wait_poll_interval),
                )


# --- Подписки -----------------------------------------------------------------------


async def list_subscriptions(
    session: AsyncSession,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Subscription]:
    """Подписки текущего актора.

    Ролей по умолчанию (автор, исполнитель, наблюдатель, упомянутый, участник) в этом
    списке нет, пока их не тронули: они работают правилом, а не строкой. Пустой список
    означает «всё по умолчанию», а не «мне ничего не приходит».
    """
    ensure_allowed(initiator, "subscription.list")
    return await SubscriptionRepository(session).list_page_for_actor(
        initiator.id,
        limit=limit,
        cursor=cursor,
    )


async def get_subscription(
    session: AsyncSession,
    subscription_id: uuid.UUID,
    *,
    initiator: Actor,
) -> Subscription:
    """Подписка текущего актора или `subscription_not_found`."""
    subscription = await SubscriptionRepository(session).get_for_actor(
        initiator.id,
        subscription_id,
    )
    if subscription is None:
        raise SubscriptionNotFoundError(details={"subscription": str(subscription_id)})
    return subscription


async def create_subscription(
    session: AsyncSession,
    *,
    initiator: Actor,
    scope: SubscriptionScope,
    scope_key: str | None = None,
    event_types: Iterable[str] | None = None,
    channel: DeliveryChannel = DeliveryChannel.INBOX,
    is_enabled: bool = True,
    notify_own_actions: bool = DEFAULT_NOTIFY_OWN_ACTIONS,
) -> Subscription:
    """Заводит подписку текущего актора.

    Подписка на **свою** ролевую область с `is_enabled = false` — это отказ от
    уведомлений по умолчанию, а не бессмысленная строка: правило по умолчанию иначе
    отключить нечем.
    """
    ensure_allowed(initiator, "subscription.create")
    normalized_key, types = validate_subscription(scope, scope_key, event_types)

    repository = SubscriptionRepository(session)
    # Проверка до вставки, а не отлов `IntegrityError`: клиенту нужен код
    # `subscription_exists` с указанием области, а не «нарушено ограничение».
    existing = await repository.find_by_scope(
        initiator.id,
        scope=scope,
        scope_key=normalized_key,
        channel=channel,
    )
    if existing is not None:
        raise SubscriptionExistsError(
            details={
                "subscription": str(existing.id),
                "scope": scope.value,
                "scope_key": normalized_key,
                "channel": channel.value,
            },
        )

    subscription = Subscription(
        actor_id=initiator.id,
        scope=scope,
        scope_key=normalized_key,
        event_types=types,
        channel=channel,
        is_enabled=is_enabled,
        notify_own_actions=notify_own_actions,
    )
    return await repository.add(subscription)


async def update_subscription(
    session: AsyncSession,
    subscription: Subscription,
    *,
    initiator: Actor,
    event_types: Iterable[str] | None = None,
    is_enabled: bool | None = None,
    notify_own_actions: bool | None = None,
) -> Subscription:
    """Меняет набор типов, включённость и правило о собственных действиях.

    Область и её ключ не меняются: «подписка на очередь TRK» и «подписка на проект
    alpha» — разные подписки, а не одна с другим значением поля. Переезд области
    означал бы, что идентификатор подписки перестал что-либо значить.
    """
    ensure_allowed(initiator, "subscription.update", target=subscription)
    if event_types is not None:
        _, types = validate_subscription(subscription.scope, subscription.scope_key, event_types)
        # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации
        # внутри значения, и UPDATE просто не уйдёт.
        subscription.event_types = types
    if is_enabled is not None:
        subscription.is_enabled = is_enabled
    if notify_own_actions is not None:
        subscription.notify_own_actions = notify_own_actions
    await SubscriptionRepository(session).flush()
    return subscription


async def delete_subscription(
    session: AsyncSession,
    subscription: Subscription,
    *,
    initiator: Actor,
) -> None:
    """Удаляет подписку.

    Удаление выключенной подписки на ролевую область **возвращает** уведомления по
    умолчанию — строки, которая их гасила, больше нет. Это неочевидно, поэтому
    названо: чтобы перестать получать события своих задач, подписку надо держать
    выключенной, а не удалять.
    """
    ensure_allowed(initiator, "subscription.delete", target=subscription)
    await SubscriptionRepository(session).delete(subscription)


# --- Внутреннее ---------------------------------------------------------------------


async def _resolve_recipients(
    session: AsyncSession,
    *,
    audience: EventAudience,
    event_type: str,
    initiator_key: str,
) -> list[_Recipient]:
    """Кто получит это событие: роли по умолчанию плюс подписки, минус исключения."""
    candidates = await ActorRepository(session).list_by_keys(set(audience.roles))
    by_key = {actor.key: actor for actor in candidates}

    subscriptions = await SubscriptionRepository(session).matching(
        actor_ids=[actor.id for actor in candidates],
        queue_key=audience.queue_key,
        project_keys=audience.project_keys,
        issue_key=audience.issue_key,
    )
    by_actor_scope: dict[tuple[uuid.UUID, SubscriptionScope], Subscription] = {
        (item.actor_id, item.scope): item for item in subscriptions
    }

    chosen: dict[str, _Recipient] = {}

    # Роли: уведомляют без подписки, если подписка их не выключила. Перебор идёт от
    # самой адресной роли к самой общей, потому что в уведомлении причина записывается
    # одна: реплика «@bob, посмотри» по его же задаче обязана прийти упоминанием, а не
    # «изменилось что-то у исполнителя».
    for actor_key, roles in audience.roles.items():
        actor = by_key.get(actor_key)
        if actor is None:
            continue
        for scope in (item for item in SCOPE_PRIORITY if item in roles):
            subscription = by_actor_scope.get((actor.id, scope))
            if subscription is None:
                if scope not in DEFAULT_ROLE_SCOPES:
                    continue
            elif not subscription.is_enabled or not matches_event_type(
                subscription.event_types, event_type
            ):
                continue
            chosen.setdefault(actor_key, _Recipient(actor, scope, subscription))

    # Области: уведомляют только по включённой подписке.
    for subscription in subscriptions:
        if subscription.scope in ROLE_SCOPES:
            continue
        if not subscription.is_enabled:
            continue
        if not matches_event_type(subscription.event_types, event_type):
            continue
        chosen.setdefault(
            subscription.actor.key,
            _Recipient(subscription.actor, subscription.scope, subscription),
        )

    return [
        recipient
        for actor_key, recipient in chosen.items()
        if _should_deliver(actor_key, recipient, initiator_key=initiator_key)
    ]


def _should_deliver(actor_key: str, recipient: _Recipient, *, initiator_key: str) -> bool:
    """Последний фильтр: системный актор и собственные действия.

    Системный актор отсекается всегда и без настройки. Правила выполняются от его
    имени, и он же оказывается инициатором цепочек — его инбокс собрал бы копию всего
    потока событий установки, а читать эту копию некому.

    Собственные действия отсекаются по умолчанию и включаются подпиской. Умолчание
    именно такое, потому что иначе агент, обновивший задачу, немедленно разбудит сам
    себя своим же изменением — и это первое, что ломается на живом потоке.
    """
    if actor_key == SYSTEM_ACTOR_KEY:
        return False
    if actor_key != initiator_key:
        return True
    subscription = recipient.subscription
    if subscription is None:
        return DEFAULT_NOTIFY_OWN_ACTIONS
    return subscription.notify_own_actions


async def _store(
    session: AsyncSession,
    *,
    actor: Actor,
    event_type: str,
    event_id: uuid.UUID | None,
    object_type: str,
    object_key: str,
    issue_key: str | None,
    issue_id: uuid.UUID | None,
    summary: NotificationSummary,
    reason: SubscriptionScope | None,
    merge: bool,
) -> Notification:
    """Кладёт запись в инбокс или дополняет ту, в которую она склеивается.

    Склейка идёт по паре «адресат + ключ склейки» среди **непрочитанных** записей,
    попавших в окно (`notification_digest_window`). Текст при этом заменяется на
    свежий, а не дописывается: десять правок задачи за минуту должны читаться как
    последнее состояние со счётчиком, а не как простыня из десяти строк.

    `created_at` склейка не двигает намеренно. По нему идёт курсорная пагинация, и
    запись, перепрыгнувшая в конец ленты, провалилась бы мимо клиента, который её
    страницу уже прочитал.
    """
    repository = NotificationRepository(session)
    key = digest_key(event_type, object_key)
    window = get_settings().notification_digest_window

    if merge and window > 0:
        existing = await repository.claim_for_digest(
            actor_id=actor.id,
            digest_key=key,
            since=datetime.now(UTC) - timedelta(seconds=window),
        )
        if existing is not None:
            existing.count += 1
            existing.body = summary.body
            existing.details = dict(summary.details) | {"merged": existing.count}
            existing.event_id = event_id
            await repository.flush()
            return existing

    notification = Notification(
        actor_id=actor.id,
        event_type=event_type,
        event_id=event_id,
        object_type=object_type,
        object_key=object_key,
        issue_id=issue_id,
        issue_key=issue_key,
        digest_key=key,
        body=summary.body,
        details=dict(summary.details) | ({} if reason is None else {"scope": reason.value}),
    )
    return await repository.add(notification)


async def _ensure_own(
    session: AsyncSession,
    actor: Actor,
    notification_ids: Sequence[uuid.UUID],
) -> None:
    """Все ли перечисленные уведомления принадлежат этому актору.

    Одним запросом на весь список, а не по запросу на идентификатор: агент отмечает
    прочитанной страницу целиком, и полсотни запросов ради проверки владения были бы
    дороже самой отметки.

    Чужой идентификатор — `notification_not_found`, а не молчаливый пропуск: клиент
    обязан узнать, что промахнулся, а не получить успех, ничего не отметив.
    """
    requested = set(notification_ids)
    if not requested:
        return
    known = await NotificationRepository(session).existing_ids(actor.id, requested)
    missing = sorted(str(item) for item in requested - known)
    if missing:
        raise NotificationNotFoundError(details={"notifications": missing})


def _resolve_timeout(timeout: float | None, maximum: float) -> float:
    """Проверяет запрошенное время ожидания.

    Выход за потолок — ошибка, а не тихое срезание: клиент, попросивший ждать десять
    минут и получивший пустой ответ через минуту, решит, что уведомлений не было. То
    же правило, что у размера страницы (`app/db/pagination.py`).
    """
    if timeout is None:
        return min(get_settings().notification_wait_timeout, maximum)
    if timeout <= 0 or timeout > maximum:
        raise InvalidWaitTimeoutError(details={"timeout": timeout, "min": 0, "max": maximum})
    return timeout


def _as_uuid(value: str | None) -> uuid.UUID | None:
    """Идентификатор из нагрузки события: там он строкой, в колонке — UUID."""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
