"""Выборки, вставки и выдача номеров по проектам."""

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models.project import Project
from app.db.pagination import Page, paginate


class ProjectRepository:
    """Доступ к таблице `projects`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key(self, key: str) -> Project | None:
        """Поиск по уже канонизированному ключу: канонизацию делает домен, не запрос."""
        statement = select(Project).where(Project.key == key)
        return (await self._session.scalars(statement)).one_or_none()

    async def first_archived(
        self, project_ids: Collection[uuid.UUID]
    ) -> tuple[str, datetime] | None:
        """Ключ и время архивирования первого по ключу архивного проекта среди названных.

        Колонки, а не объект: объект проекта в карте сессии мог быть прочитан до очереди
        изменений или нести незаписанную правку сценария, и выборка сущности вернула бы
        его как есть. Запрос колонок под очередью видит состояние после всех
        зафиксировавшихся соседей (`READ COMMITTED`) и чужих объектов не трогает.
        """
        if not project_ids:
            return None
        statement = (
            select(Project.key, Project.archived_at)
            .where(Project.id.in_(project_ids), Project.archived_at.is_not(None))
            .order_by(Project.key)
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None or row.archived_at is None:
            return None
        return row.key, row.archived_at

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Project]:
        return await paginate(self._session, select(Project), Project, limit=limit, cursor=cursor)

    async def add(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        return project

    async def allocate_task_number(self, project: Project) -> int:
        """Следующий номер задачи в проекте — одним запросом, без гонок.

        Инкремент считает база поверх текущего значения строки: наивное «прочитать и
        записать +1» выдало бы двум параллельным запросам один и тот же номер.
        `SEQUENCE` не блокирует, но живёт вне строки проекта, и его пришлось бы заводить
        на каждый новый проект отдельной командой DDL.

        Две особенности, обе намеренные и обе неустранимые без отказа от
        транзакционности:

        - выдача сериализует создание задач **в одном проекте** до конца транзакции:
          строка проекта заблокирована `UPDATE` до коммита;
        - откатившаяся транзакция свой номер теряет, и в нумерации остаётся дыра.
          Поэтому номер выдаётся последним, после всех проверок создания задачи.
        """
        statement = (
            update(Project)
            .where(Project.id == project.id)
            .values(last_task_number=Project.last_task_number + 1)
            .returning(Project.last_task_number)
        )
        number = await self._session.scalar(
            statement,
            execution_options={"synchronize_session": False},
        )
        if number is None:
            # Строка исчезнуть не может — проект не удаляется, — но молчаливое `None`
            # уехало бы в ключ задачи и превратилось в `TRK-None`.
            raise RuntimeError(f"Project {project.key} disappeared while allocating a task number")

        # Загруженный объект после массового `UPDATE` держит старое значение, и ответ,
        # собранный из него в том же запросе, показал бы счётчик до инкремента.
        # `set_committed_value` правит именно загруженное состояние: обычное
        # присваивание пометило бы атрибут изменённым и добавило второй `UPDATE`.
        set_committed_value(project, "last_task_number", number)
        return int(number)
