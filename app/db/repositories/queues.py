"""Выборки, вставки и выдача номеров по очередям."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models.queue import Queue
from app.db.pagination import Page, paginate


class QueueRepository:
    """Доступ к таблице `queues`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key(self, key: str) -> Queue | None:
        """Поиск по уже канонизированному ключу: канонизацию делает домен, не запрос."""
        statement = select(Queue).where(Queue.key == key)
        return (await self._session.scalars(statement)).one_or_none()

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Queue]:
        return await paginate(self._session, select(Queue), Queue, limit=limit, cursor=cursor)

    async def add(self, queue: Queue) -> Queue:
        self._session.add(queue)
        await self._session.flush()
        return queue

    async def allocate_task_number(self, queue: Queue) -> int:
        """Следующий номер задачи в очереди — одним запросом, без гонок.

        Инкремент считает база поверх текущего значения строки: наивное «прочитать и
        записать +1» выдало бы двум параллельным запросам один и тот же номер.
        `SEQUENCE` не блокирует, но живёт вне строки очереди, и его пришлось бы заводить
        на каждую новую очередь отдельной командой DDL.

        Две особенности, обе намеренные и обе неустранимые без отказа от
        транзакционности:

        - выдача сериализует создание задач **в одной очереди** до конца транзакции:
          строка очереди заблокирована `UPDATE` до коммита;
        - откатившаяся транзакция свой номер теряет, и в нумерации остаётся дыра.
          Поэтому номер выдаётся последним, после всех проверок создания задачи.
        """
        statement = (
            update(Queue)
            .where(Queue.id == queue.id)
            .values(last_task_number=Queue.last_task_number + 1)
            .returning(Queue.last_task_number)
        )
        number = await self._session.scalar(
            statement,
            execution_options={"synchronize_session": False},
        )
        if number is None:
            # Строка исчезнуть не может — очередь не удаляется, — но молчаливое `None`
            # уехало бы в ключ задачи и превратилось в `TRK-None`.
            raise RuntimeError(f"Queue {queue.key} disappeared while allocating a task number")

        # Загруженный объект после массового `UPDATE` держит старое значение, и ответ,
        # собранный из него в том же запросе, показал бы счётчик до инкремента.
        # `set_committed_value` правит именно загруженное состояние: обычное
        # присваивание пометило бы атрибут изменённым и добавило второй `UPDATE`.
        set_committed_value(queue, "last_task_number", number)
        return int(number)
