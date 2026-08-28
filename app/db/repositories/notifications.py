"""Выборки по подпискам и по инбоксу актора.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Нетривиальных места два. `matching` собирает **все** подписки, которые могут иметь
отношение к одному событию, одним запросом: подписчик вызывается на каждое событие
установки, и пять запросов вместо одного превратились бы в пять запросов на событие.
`claim_for_digest` ищет запись, в которую новое событие можно склеить.
"""

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import Notification, Subscription
from app.db.pagination import Page, paginate
from app.domain.notifications import ROLE_SCOPES, DeliveryChannel, SubscriptionScope


class SubscriptionRepository:
    """Доступ к таблице `notification_subscriptions`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, subscription: Subscription) -> Subscription:
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def flush(self) -> None:
        await self._session.flush()

    async def delete(self, subscription: Subscription) -> None:
        await self._session.delete(subscription)
        await self._session.flush()

    async def get_for_actor(
        self,
        actor_id: uuid.UUID,
        subscription_id: uuid.UUID,
    ) -> Subscription | None:
        """Подписка этого актора. Чужая не находится — она для клиента не существует."""
        statement = select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.actor_id == actor_id,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def find_by_scope(
        self,
        actor_id: uuid.UUID,
        *,
        scope: SubscriptionScope,
        scope_key: str | None,
        channel: DeliveryChannel,
    ) -> Subscription | None:
        """Подписка актора на эту область в этом канале, если она уже есть.

        Проверка дубля идёт до вставки, а не отловом `IntegrityError`: клиенту нужен
        код `subscription_exists` с указанием области, а не «нарушено ограничение
        целостности», по которому непонятно, что чинить.
        """
        statement = select(Subscription).where(
            Subscription.actor_id == actor_id,
            Subscription.scope == scope,
            Subscription.channel == channel,
            Subscription.scope_key.is_(None)
            if scope_key is None
            else Subscription.scope_key == scope_key,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page_for_actor(
        self,
        actor_id: uuid.UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Subscription]:
        statement = select(Subscription).where(Subscription.actor_id == actor_id)
        return await paginate(self._session, statement, Subscription, limit=limit, cursor=cursor)

    async def matching(
        self,
        *,
        actor_ids: Collection[uuid.UUID],
        queue_key: str | None,
        project_keys: Collection[str],
        issue_key: str | None,
    ) -> list[Subscription]:
        """Все подписки, которые могут сработать на одно событие.

        Две половины в одном запросе, и объединять их приходится именно здесь:

        - подписки **причастных** акторов на ролевые области. Они нужны не для того,
          чтобы разрешить уведомление (роли уведомляют и без подписки), а чтобы узнать
          про сужение набора типов и про выключение роли;
        - подписки **кого угодно** на объекты события: очередь, проект, задачу, весь
          поток. Тут актор заранее неизвестен — его и ищем.

        Два запроса вместо одного выглядели бы понятнее и стоили бы вдвое дороже на
        каждом событии установки.

        Причастные приходят идентификаторами, а не ключами из нагрузки: адресат в
        инбоксе хранится ссылкой, поэтому сценарий всё равно обязан перевести ключи в
        строки акторов — и делать это дважды незачем.
        """
        conditions = [Subscription.scope == SubscriptionScope.ALL]
        if queue_key is not None:
            conditions.append(
                and_(
                    Subscription.scope == SubscriptionScope.QUEUE,
                    Subscription.scope_key == queue_key,
                )
            )
        if project_keys:
            conditions.append(
                and_(
                    Subscription.scope == SubscriptionScope.PROJECT,
                    Subscription.scope_key.in_(sorted(project_keys)),
                )
            )
        if issue_key is not None:
            conditions.append(
                and_(
                    Subscription.scope == SubscriptionScope.ISSUE,
                    Subscription.scope_key == issue_key,
                )
            )
        if actor_ids:
            conditions.append(
                and_(
                    Subscription.scope.in_(sorted(ROLE_SCOPES)),
                    Subscription.actor_id.in_(list(actor_ids)),
                )
            )

        statement = select(Subscription).where(or_(*conditions))
        return list((await self._session.scalars(statement)).unique())


class NotificationRepository:
    """Доступ к таблице `notifications`: инбокс, склейка, отметки о прочтении."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: Notification) -> Notification:
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def flush(self) -> None:
        await self._session.flush()

    async def get_for_actor(
        self,
        actor_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> Notification | None:
        statement = select(Notification).where(
            Notification.id == notification_id,
            Notification.actor_id == actor_id,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page_for_actor(
        self,
        actor_id: uuid.UUID,
        *,
        is_read: bool | None = None,
        issue_id: uuid.UUID | None = None,
        event_type: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Notification]:
        """Страница инбокса, от старого к новому — как история задачи и лента обсуждения.

        Порядок хронологический, а не «новые сверху»: агент разбирает ленту подряд и
        отмечает прочитанным то, что обработал, а курсорная пагинация проекта идёт
        ровно по паре `(created_at, id)`.
        """
        statement = select(Notification).where(Notification.actor_id == actor_id)
        if is_read is not None:
            statement = statement.where(Notification.is_read.is_(is_read))
        if issue_id is not None:
            statement = statement.where(Notification.issue_id == issue_id)
        if event_type is not None:
            statement = statement.where(Notification.event_type == event_type)
        return await paginate(self._session, statement, Notification, limit=limit, cursor=cursor)

    async def claim_for_digest(
        self,
        *,
        actor_id: uuid.UUID,
        digest_key: str,
        since: datetime,
    ) -> Notification | None:
        """Непрочитанное уведомление того же адресата с тем же ключом склейки в окне.

        Только непрочитанное, и это принципиально: дописать событие в запись, которую
        человек уже видел, значило бы изменить прочитанное задним числом, ничем этого
        не показав. Прочитанная запись остаётся как есть, а новое событие заводит новую.

        Берётся самая свежая: если склеек накопилось несколько (окно сужали на ходу),
        расти должна последняя, а не первая.
        """
        statement = (
            select(Notification)
            .where(
                Notification.actor_id == actor_id,
                Notification.digest_key == digest_key,
                Notification.is_read.is_(False),
                Notification.created_at >= since,
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(1)
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def existing_ids(
        self,
        actor_id: uuid.UUID,
        notification_ids: Collection[uuid.UUID],
    ) -> set[uuid.UUID]:
        """Какие из перечисленных уведомлений принадлежат этому актору.

        Одним запросом на весь набор: агент отмечает прочитанной страницу целиком, и
        проверка владения по одному идентификатору за раз стоила бы полсотни запросов
        на одну отметку.
        """
        if not notification_ids:
            return set()
        statement = select(Notification.id).where(
            Notification.actor_id == actor_id,
            Notification.id.in_(list(notification_ids)),
        )
        return set((await self._session.scalars(statement)).all())

    async def count_unread(self, actor_id: uuid.UUID) -> int:
        """Сколько непрочитанных в инбоксе актора.

        Счёт честный, а не «больше сотни»: он ложится на частичный индекс по
        непрочитанным, а тот остаётся маленьким — прочитанные из него выбывают. По
        полной таблице такой счёт был бы полным проходом и отдавать его наружу было
        бы нельзя.
        """
        statement = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.actor_id == actor_id, Notification.is_read.is_(False))
        )
        return (await self._session.scalar(statement)) or 0

    async def mark_read(
        self,
        actor_id: uuid.UUID,
        *,
        notification_ids: Sequence[uuid.UUID] | None,
        moment: datetime,
    ) -> int:
        """Отмечает прочитанными перечисленные уведомления или все непрочитанные.

        `None` означает «все»: агент, разобравший ленту целиком, не должен
        перечислять полсотни идентификаторов, которые ему для этого пришлось бы
        собрать отдельным запросом.

        Уже прочитанные не трогаются: `read_at` обязан хранить момент первого
        прочтения, иначе повторный вызов переписал бы историю разбора ленты.
        """
        statement = (
            update(Notification)
            .where(Notification.actor_id == actor_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=moment)
        )
        if notification_ids is not None:
            if not notification_ids:
                return 0
            statement = statement.where(Notification.id.in_(list(notification_ids)))
        # `synchronize_session=False`: уже загруженные объекты сессии останутся со
        # старым значением, поэтому сценарий отдаёт число, а не объекты. Тот же приём,
        # что у массового переноса задач между статусами.
        result = await self._session.execute(statement.execution_options(synchronize_session=False))
        await self._session.flush()
        return result.rowcount or 0
