"""Выборки и вставки по задачам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
Изменения полей задачи идут через объект в сессии, а не массовыми `UPDATE`: версию
ведёт `version_id_col`, и запрос мимо ORM обошёл бы оптимистичную блокировку.

Здесь же условие «задача отложена» (`deferred_now`): одно выражение на проверку входа в
`in_progress`, признак `deferred` карточки и строки выдачи и отбор `deferred:`, как
`open_blockers_of` у `blocked` (`app/db/repositories/links.py`).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import DateTime, and_, distinct, func, literal, or_, select, true
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
        так же, как текущий (TRK#112): отдельного пути «задача по прежнему
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
        (TRK#92), и закрытая задача в ней важнее открытой. Решения без ссылок в
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

    async def clock(self) -> datetime:
        """Часы базы — `now()` транзакции, по которым считается `deferred`.

        Нужны тому, кто ставит момент от часов установки, а не от своих: демо
        откладывает задачу на неделю от посева, тесты — на день в обе стороны. Часы
        процесса приложения с ними не совпадают, и задача, отложенная по ним, наступала
        бы не тогда, когда её отпустит проверка входа.
        """
        moment = await self._session.scalar(select(func.now()))
        assert moment is not None  # `SELECT now()` строку отдаёт всегда.
        return moment

    async def is_deferred(self, not_before: datetime | None) -> bool:
        """Отложен ли момент `not_before` по часам базы — тем же выражением, что отбор.

        Значение приходит из объекта задачи, а не из строки таблицы: у перехода, которому
        тот же вызов только что поменял поле, правка ещё не записана (`autoflush`
        выключен), а проверить надо будущее состояние. Часы — `now()` транзакции, как у
        признака в выдаче: часы процесса приложения в сравнении не участвуют.
        """
        moment = literal(not_before, type_=DateTime(timezone=True))
        return bool(await self._session.scalar(select(deferred_now(moment))))

    async def add(self, task: Task) -> Task:
        """Кладёт задачу в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(task)
        await self._session.flush()
        return task


def named_by(key: str) -> ColumnElement[bool]:
    """Условие «задача носит этот ключ сейчас или носила раньше» — одно на все выборки.

    Прежний ключ ищется вхождением в `previous_keys` (`@>`), под которое лежит GIN-индекс
    `ix_tasks_previous_keys`. Ключ одной задачи другой не выдаётся (TRK#112),
    поэтому условие находит не больше одной задачи.
    """
    return or_(Task.key == key, Task.previous_keys.contains([key]))


def deferred_now(not_before: ColumnElement[datetime | None]) -> ColumnElement[bool]:
    """Условие «момент `not_before` ещё не наступил» по часам базы (решение проекта `TRK#47`).

    Единственное написание признака `deferred`: им считают и проверку входа в
    `in_progress` (`TaskRepository.is_deferred`), и колонку признака в выдаче, и отбор
    `deferred:` (`app/db/repositories/search.py`). Второе написание развело бы «можно ли
    взять» у перехода и у списка кандидатов ровно в минуту наступления момента.

    Часы — `now()`: время начала транзакции, одно на все сравнения одного запроса. Пустое
    поле даёт `false`, а не `NULL`: `IS NOT NULL` стоит первым, и отрицание
    (`deferred: false`) находит задачи без момента.
    """
    return and_(not_before.is_not(None), not_before > func.now())
