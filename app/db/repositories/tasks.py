"""Выборки и вставки по задачам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
Изменения полей задачи идут через объект в сессии, а не массовыми `UPDATE`: версию
ведёт `version_id_col`, и запрос мимо ORM обошёл бы оптимистичную блокировку.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import distinct, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.task import Task


class TaskRepository:
    """Доступ к таблице `tasks`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def get_by_key(self, key: str) -> Task | None:
        """Поиск по уже канонизированному ключу — текущему или прежнему.

        Канонизацию делает домен, не запрос. Прежний ключ перенесённой задачи ведёт на неё
        так же, как текущий (`CONCEPT.md`, 3.3): отдельного пути «задача по прежнему
        ключу» нет, и каждое обращение к задаче по ключу идёт отсюда.
        """
        statement = select(Task).where(named_by(key))
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_by_keys(self, keys: Sequence[str]) -> dict[str, Task]:
        """Задачи по набору канонизированных ключей, одним запросом: ключ запроса → задача.

        Нужен проверке ссылок записи дела: `refs` короткий, но запрос на каждую ссылку
        превратил бы подшивку одной записи в десяток обращений к базе. Словарь — по
        ключу **запроса**, а не по текущему ключу задачи: ссылка `UI-5#2` на
        перенесённую задачу обязана найти её под тем ключом, которым её назвали.
        """
        wanted = set(keys)
        if not wanted:
            return {}
        statement = select(Task).where(or_(*(named_by(key) for key in sorted(wanted))))
        found: dict[str, Task] = {}
        for task in (await self._session.scalars(statement)).unique():
            for key in wanted.intersection((task.key, *task.previous_keys)):
                found[key] = task
        return found

    async def decision_counts(self, refs: Sequence[str]) -> dict[str, int]:
        """Сколько задач ссылается на каждое из решений: ссылка `TRK#15` → число задач.

        Задачи любого статуса и любого проекта: это история «что сделано по решению»
        (`CONCEPT.md`, 3.2), и закрытая задача в ней важнее открытой. Решения без ссылок в
        словарь не попадают — их число ноль. Один запрос на весь список: раскладка поля
        `decisions` по строкам и подсчёт по ссылке.
        """
        if not refs:
            return {}
        ref = func.jsonb_array_elements_text(Task.decisions).table_valued("value").alias("ref")
        statement = (
            select(ref.c.value, func.count(distinct(Task.id)))
            .select_from(Task)
            .join(ref, true())
            .where(ref.c.value.in_(sorted(set(refs))))
            .group_by(ref.c.value)
        )
        return {value: int(count) for value, count in (await self._session.execute(statement))}

    async def add(self, task: Task) -> Task:
        """Кладёт задачу в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(task)
        await self._session.flush()
        return task


def named_by(key: str) -> ColumnElement[bool]:
    """Условие «задача носит этот ключ сейчас или носила раньше» — одно на все выборки.

    Прежний ключ ищется вхождением в `previous_keys` (`@>`), под которое лежит GIN-индекс
    `ix_tasks_previous_keys`. Ключ одной задачи другой не выдаётся (`CONCEPT.md`, 3.3),
    поэтому условие находит не больше одной задачи.
    """
    return or_(Task.key == key, Task.previous_keys.contains([key]))
