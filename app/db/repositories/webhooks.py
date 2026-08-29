"""Выборки по подпискам вебхуков и по журналу доставок.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Нетривиальных места два. `matching` собирает подписки, которые могут иметь отношение к
одному событию, **одним** запросом: подписчик вызывается на каждое событие установки, и
три запроса вместо одного превратились бы в три запроса на событие. `claim_next` берёт
задание доставщиком через `FOR UPDATE SKIP LOCKED` — тот же приём, что у очереди
событий, и по тем же причинам.
"""

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.db.pagination import Page, paginate
from app.domain.webhooks import DeliveryStatus, WebhookScope


class WebhookSubscriptionRepository:
    """Доступ к таблице `webhook_subscriptions`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, subscription: WebhookSubscription) -> WebhookSubscription:
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def flush(self) -> None:
        await self._session.flush()

    async def delete(self, subscription: WebhookSubscription) -> None:
        await self._session.delete(subscription)
        await self._session.flush()

    async def get(self, subscription_id: uuid.UUID) -> WebhookSubscription | None:
        statement = select(WebhookSubscription).where(WebhookSubscription.id == subscription_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def find_by_name(self, name: str) -> WebhookSubscription | None:
        """Подписка по имени: так её адресует правило автоматики.

        Проверка дубля идёт до вставки, а не отловом `IntegrityError`: клиенту нужен код
        `webhook_subscription_name_taken`, а не «нарушено ограничение целостности», по
        которому непонятно, что чинить.
        """
        statement = select(WebhookSubscription).where(WebhookSubscription.name == name)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        is_enabled: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[WebhookSubscription]:
        statement = select(WebhookSubscription)
        if is_enabled is not None:
            statement = statement.where(WebhookSubscription.is_enabled.is_(is_enabled))
        return await paginate(
            self._session,
            statement,
            WebhookSubscription,
            limit=limit,
            cursor=cursor,
        )

    async def matching(
        self,
        *,
        queue_key: str | None,
        project_keys: Collection[str],
    ) -> list[WebhookSubscription]:
        """Включённые подписки, к области которых может относиться событие.

        Отбор по области идёт в SQL, отбор по типу события — в сценарии: типы лежат в
        JSONB списком, и условие «пустой список или содержит значение» читается в Python
        втрое понятнее, чем в выражении над JSONB, а подписок на одно событие единицы.

        Выключенные не попадают в выборку вовсе. Ставить задание выключенной подписке
        значило бы копить работу, которую никто не заберёт: доставщик её пропустит, а
        журнал заполнится строками, объясняющими не сбой, а настройку.
        """
        conditions = [WebhookSubscription.scope == WebhookScope.ALL]
        if queue_key is not None:
            conditions.append(
                and_(
                    WebhookSubscription.scope == WebhookScope.QUEUE,
                    WebhookSubscription.scope_key == queue_key,
                )
            )
        if project_keys:
            conditions.append(
                and_(
                    WebhookSubscription.scope == WebhookScope.PROJECT,
                    WebhookSubscription.scope_key.in_(sorted(project_keys)),
                )
            )

        statement = select(WebhookSubscription).where(
            WebhookSubscription.is_enabled.is_(True),
            or_(*conditions),
        )
        return list((await self._session.scalars(statement)).unique())


class WebhookDeliveryRepository:
    """Очередь заданий на доставку и журнал их исходов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, delivery: WebhookDelivery) -> WebhookDelivery:
        self._session.add(delivery)
        await self._session.flush()
        return delivery

    async def add_all(self, deliveries: list[WebhookDelivery]) -> list[WebhookDelivery]:
        """Пачкой: одно событие уходит сразу на все подходящие адреса."""
        if not deliveries:
            return []
        self._session.add_all(deliveries)
        await self._session.flush()
        return deliveries

    async def flush(self) -> None:
        await self._session.flush()

    async def get(self, delivery_id: uuid.UUID) -> WebhookDelivery | None:
        statement = select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        subscription_id: uuid.UUID | None = None,
        status: DeliveryStatus | None = None,
        event_type: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[WebhookDelivery]:
        """Журнал страницами, от старого к новому — как все коллекции проекта."""
        statement = select(WebhookDelivery)
        if subscription_id is not None:
            statement = statement.where(WebhookDelivery.subscription_id == subscription_id)
        if status is not None:
            statement = statement.where(WebhookDelivery.status == status)
        if event_type is not None:
            statement = statement.where(WebhookDelivery.event_type == event_type)
        return await paginate(
            self._session,
            statement,
            WebhookDelivery,
            limit=limit,
            cursor=cursor,
        )

    async def claim_next(self, *, now: datetime) -> WebhookDelivery | None:
        """Берёт в работу одно задание, блокируя его строку до конца транзакции.

        `FOR UPDATE SKIP LOCKED` — то же, что у очереди событий, и обе половины важны по
        тем же причинам. `FOR UPDATE` возвращает задание в очередь, если процесс убьют
        посреди отправки; `SKIP LOCKED` разводит две реплики доставщика по разным
        строкам вместо того, чтобы выстроить их друг за другом.

        Важное следствие: строка держится заблокированной **всё время HTTP-запроса**,
        то есть до таймаута включительно. Поэтому таймаут обязан быть коротким — иначе
        мёртвый адрес держит открытую транзакцию минутами.
        """
        statement = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == DeliveryStatus.PENDING,
                WebhookDelivery.available_at <= now,
            )
            .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(statement)).unique().one_or_none()
