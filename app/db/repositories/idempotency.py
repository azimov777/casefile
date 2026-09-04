"""Ключи идемпотентности: найти, занять, снять устаревшие."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.idempotency import IdempotencyKey


class IdempotencyRepository:
    """Доступ к таблице `idempotency_keys`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, *, token_id: uuid.UUID, key: str) -> IdempotencyKey | None:
        """Ключ этого токена или `None`.

        Чужие незафиксированные строки сюда не попадают, и это свойство механизма, а не
        случайность: пока транзакция, занявшая ключ, не закончилась, её строки не
        существует ни для кого, кроме неё самой.
        """
        statement = select(IdempotencyKey).where(
            IdempotencyKey.token_id == token_id,
            IdempotencyKey.key == key,
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def add(self, record: IdempotencyKey) -> IdempotencyKey:
        """Занимает ключ. `IntegrityError` здесь — рабочий исход, а не сбой.

        Вызывающий обязан обернуть вызов вложенной транзакцией (`session.begin_nested`)
        и разобрать нарушение уникальности: без точки сохранения упавший `flush`
        оставляет всю транзакцию непригодной, и разбирать будет уже нечего.
        """
        self._session.add(record)
        await self._session.flush()
        return record

    async def delete_expired(self, *, before: datetime) -> int:
        """Снимает ключи старше срока жизни. Возвращает число удалённых строк.

        Зовётся попутно, при записи нового ключа: фонового процесса в трекере нет
        (`CONVENTIONS.md`, «Запуск»), а ключ, который никто не удалит, хранил бы секрет
        выпущенного токена вечно.

        `synchronize_session=False` обязателен: синхронизация identity map с массовым
        удалением стоит лишнего запроса и ничего здесь не даёт — снятая строка в сессии
        больше не используется.
        """
        result = await self._session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.created_at < before),
            execution_options={"synchronize_session": False},
        )
        return result.rowcount
