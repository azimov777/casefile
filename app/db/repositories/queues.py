"""Выборки и вставки по очередям и их привязкам к типам задач.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
`flush` вызывать можно — он отправляет запрос, не фиксируя транзакцию.
"""

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models.catalog import IssueType
from app.db.models.queue import Queue, QueueIssueType
from app.db.pagination import Page, paginate


class QueueRepository:
    """Доступ к таблицам `queues` и `queue_issue_types`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, queue_id: uuid.UUID) -> Queue | None:
        return await self._session.get(Queue, queue_id)

    async def get_by_key(self, key: str) -> Queue | None:
        statement = select(Queue).where(Queue.key == key)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        is_archived: bool | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> Page[Queue]:
        statement = select(Queue)
        if is_archived is not None:
            statement = statement.where(Queue.is_archived.is_(is_archived))
        if owner_id is not None:
            statement = statement.where(Queue.owner_id == owner_id)
        return await paginate(self._session, statement, Queue, limit=limit, cursor=cursor)

    async def add(self, queue: Queue) -> Queue:
        self._session.add(queue)
        await self._session.flush()
        return queue

    async def delete(self, queue: Queue) -> None:
        await self._session.delete(queue)
        await self._session.flush()

    async def allocate_issue_number(self, queue: Queue) -> int:
        """Выдаёт следующий номер задачи в очереди. Одним запросом и без гонок.

        `UPDATE ... SET last_issue_number = last_issue_number + 1 RETURNING` — вся суть
        здесь. Инкремент считает база поверх текущего значения строки, а не приложение
        поверх прочитанного, поэтому два параллельных запроса не могут получить один
        номер: второй ждёт на блокировке строки и увидит уже увеличенное значение.

        Плата за отсутствие дыр — сериализация: пока транзакция, взявшая номер, не
        завершилась, остальные создатели задач в этой очереди ждут её. Это осознанный
        выбор в пользу нумерации без пропусков; последовательность (`SEQUENCE`) не
        блокировала бы, но выдавала бы дыры при любом откате и параллельной работе.

        Дыра всё же возможна ровно в одном случае: транзакция взяла номер и
        откатилась. Номер при этом теряется. Убрать этот случай нельзя, не отказавшись
        от транзакционности вовсе, поэтому он назван прямо, а не спрятан.

        `set_committed_value` в конце — не украшение: без него загруженный объект
        очереди остался бы со старым значением счётчика, и код, прочитавший
        `queue.last_issue_number` после выдачи номера, получил бы устаревшее число.
        Обычное присваивание вместо него пометило бы объект грязным и добавило второй
        UPDATE тем же значением.
        """
        statement = (
            update(Queue)
            .where(Queue.id == queue.id)
            .values(last_issue_number=Queue.last_issue_number + 1)
            .returning(Queue.last_issue_number)
            .execution_options(synchronize_session=False)
        )
        number = await self._session.scalar(statement)
        if number is None:
            return 0
        set_committed_value(queue, "last_issue_number", number)
        return int(number)

    async def list_issue_types(
        self, queue_id: uuid.UUID, *, active_only: bool = False
    ) -> list[IssueType]:
        """Типы задач, разрешённые в очереди.

        Порядок — порядок самого справочника, а не порядок привязки к очереди. Так же
        упорядочены статусы и резолюции, и одинаковый тип во всех очередях стоит на
        одном и том же месте. Порядок привязки для этого не годится ещё и технически:
        привязки, созданные в одной транзакции, получают одинаковый `created_at`, и
        сортировка по нему вырождается в сортировку по случайным UUID.
        """
        statement = (
            select(IssueType)
            .join(QueueIssueType, QueueIssueType.issue_type_id == IssueType.id)
            .where(QueueIssueType.queue_id == queue_id)
            .order_by(IssueType.created_at, IssueType.id)
        )
        if active_only:
            statement = statement.where(IssueType.is_active.is_(True))
        return list((await self._session.scalars(statement)).unique())

    async def has_issue_type(self, queue_id: uuid.UUID, issue_type_id: uuid.UUID) -> bool:
        statement = select(QueueIssueType.id).where(
            QueueIssueType.queue_id == queue_id,
            QueueIssueType.issue_type_id == issue_type_id,
        )
        return await self._session.scalar(statement) is not None

    async def get_issue_type_binding(
        self,
        queue_id: uuid.UUID,
        issue_type_id: uuid.UUID,
    ) -> QueueIssueType | None:
        statement = select(QueueIssueType).where(
            QueueIssueType.queue_id == queue_id,
            QueueIssueType.issue_type_id == issue_type_id,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def bind_issue_type(
        self,
        queue_id: uuid.UUID,
        issue_type_id: uuid.UUID,
        workflow_id: uuid.UUID,
    ) -> QueueIssueType:
        binding = QueueIssueType(
            queue_id=queue_id,
            issue_type_id=issue_type_id,
            workflow_id=workflow_id,
        )
        self._session.add(binding)
        await self._session.flush()
        return binding

    async def unbind_issue_types(
        self, queue_id: uuid.UUID, issue_type_ids: list[uuid.UUID]
    ) -> None:
        if not issue_type_ids:
            return
        statement = delete(QueueIssueType).where(
            QueueIssueType.queue_id == queue_id,
            QueueIssueType.issue_type_id.in_(issue_type_ids),
        )
        await self._session.execute(statement)
        await self._session.flush()

    async def keys_with_default_status(self, status_id: uuid.UUID) -> list[str]:
        """Ключи очередей, у которых этот статус выбран по умолчанию."""
        statement = (
            select(Queue.key).where(Queue.default_status_id == status_id).order_by(Queue.key)
        )
        return list(await self._session.scalars(statement))

    async def keys_with_default_issue_type(self, issue_type_id: uuid.UUID) -> list[str]:
        """Ключи очередей, у которых этот тип задачи выбран по умолчанию."""
        statement = (
            select(Queue.key)
            .where(Queue.default_issue_type_id == issue_type_id)
            .order_by(Queue.key)
        )
        return list(await self._session.scalars(statement))

    async def keys_using_issue_type(self, issue_type_id: uuid.UUID) -> list[str]:
        """Ключи очередей, в которых тип задачи разрешён."""
        statement = (
            select(Queue.key)
            .join(QueueIssueType, QueueIssueType.queue_id == Queue.id)
            .where(QueueIssueType.issue_type_id == issue_type_id)
            .order_by(Queue.key)
        )
        return list(await self._session.scalars(statement))
