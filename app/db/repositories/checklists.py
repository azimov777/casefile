"""Выборки и изменения по пунктам чеклиста.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Пагинации здесь нет, и это решение, а не пропуск: число пунктов у задачи ограничено
доменом (`MAX_CHECKLIST_ITEMS`), поэтому чеклист всегда читается целиком. Курсор
посреди списка, порядок в котором задаётся перетаскиванием, указывал бы на позицию,
которой после следующего перемещения уже нет.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.checklist import ChecklistItem


class ChecklistRepository:
    """Доступ к таблице `checklist_items`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, item_id: uuid.UUID) -> ChecklistItem | None:
        statement = select(ChecklistItem).where(ChecklistItem.id == item_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_for_issue(self, issue_id: uuid.UUID) -> list[ChecklistItem]:
        """Пункты задачи по порядку.

        Сортировка по паре `(position, id)`: позиции уникальными не объявлены —
        перенумерация меняет их пачкой, и уникальный индекс отверг бы промежуточное
        состояние одного UPDATE. Второй элемент ключа доопределяет порядок до
        устойчивого, чтобы совпавшие позиции не давали произвольную выдачу.
        """
        statement = (
            select(ChecklistItem)
            .where(ChecklistItem.issue_id == issue_id)
            .order_by(ChecklistItem.position, ChecklistItem.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def add(self, item: ChecklistItem) -> ChecklistItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def delete(self, item: ChecklistItem) -> None:
        await self._session.delete(item)
        await self._session.flush()

    async def flush(self) -> None:
        """Фиксирует изменения объектов в базе, не закрывая транзакцию."""
        await self._session.flush()
