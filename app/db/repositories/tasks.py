"""Выборки и вставки по задачам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
Изменения полей задачи идут через объект в сессии, а не массовыми `UPDATE`: версию
ведёт `version_id_col`, и запрос мимо ORM обошёл бы оптимистичную блокировку.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.task import Task


class TaskRepository:
    """Доступ к таблице `tasks`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def get_by_key(self, key: str) -> Task | None:
        """Поиск по уже канонизированному ключу: канонизацию делает домен, не запрос."""
        statement = select(Task).where(Task.key == key)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_by_keys(self, keys: Sequence[str]) -> dict[str, Task]:
        """Задачи по набору канонизированных ключей, одним запросом.

        Нужен проверке ссылок записи дела: `refs` короткий, но запрос на каждую ссылку
        превратил бы подшивку одной записи в десяток обращений к базе.
        """
        if not keys:
            return {}
        statement = select(Task).where(Task.key.in_(set(keys)))
        return {task.key: task for task in (await self._session.scalars(statement)).unique()}

    async def add(self, task: Task) -> Task:
        """Кладёт задачу в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(task)
        await self._session.flush()
        return task
