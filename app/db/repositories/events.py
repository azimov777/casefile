"""Выборки по журналу изменений и по outbox.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Самое нетривиальное здесь — `claim_next`. Всё остальное — обычные выборки.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.pagination import Page, paginate
from app.domain.events import OutboxStatus


class ChangelogRepository:
    """История изменений задач."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: ChangelogEntry) -> ChangelogEntry:
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def add_all(self, entries: list[ChangelogEntry]) -> list[ChangelogEntry]:
        """Пачкой: массовый перенос задач между статусами пишет запись на каждую задачу."""
        if not entries:
            return []
        self._session.add_all(entries)
        await self._session.flush()
        return entries

    async def list_page(
        self,
        *,
        issue_id: uuid.UUID,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[ChangelogEntry]:
        """История одной задачи в хронологическом порядке, страницами.

        От старого к новому, а не наоборот: так читается история, и так работает
        единственная в проекте пагинация — по возрастанию пары `(created_at, id)`.
        Своя сортировка здесь означала бы второй курсор, несовместимый с общим.
        """
        statement = select(ChangelogEntry).where(ChangelogEntry.issue_id == issue_id)
        return await paginate(self._session, statement, ChangelogEntry, limit=limit, cursor=cursor)


class OutboxRepository:
    """Очередь событий: запись сценарием, выборка воркером."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEvent) -> OutboxEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def claim_next(self, *, now: datetime) -> OutboxEvent | None:
        """Берёт в работу одно событие, блокируя его строку до конца транзакции.

        `FOR UPDATE SKIP LOCKED` — суть всей надёжности воркера, и обе половины важны.
        `FOR UPDATE` держит строку до конца транзакции: если процесс убьют посреди
        обработки, транзакция откатится, блокировка снимется, и событие снова станет
        необработанным — потерять его нельзя. `SKIP LOCKED` заставляет второй процесс
        пройти мимо занятой строки, а не ждать её: без него две реплики воркера
        выстроились бы в очередь друг за другом, а с обычным `SELECT` — обработали бы
        одно событие дважды.

        Порядок — по паре `(created_at, id)`, тот же, что у пагинации: события уходят
        подписчикам в том порядке, в каком происходили.
        """
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def list_by_object(
        self,
        *,
        object_type: str,
        object_id: uuid.UUID,
    ) -> list[OutboxEvent]:
        """Все события объекта в порядке появления.

        Адресация парой «тип + идентификатор», а не внешним ключом: события удалённой
        задачи никуда не деваются, и найти их можно только так.
        """
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.object_type == object_type, OutboxEvent.object_id == object_id)
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
        )
        return list(await self._session.scalars(statement))
