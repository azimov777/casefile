"""Выборки по журналу изменений и по outbox.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Самое нетривиальное здесь — `claim_next`. Всё остальное — обычные выборки.
"""

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import Select, delete, false, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.pagination import Page, paginate
from app.domain.events import OutboxStatus

#: Позиция в очереди событий: та же пара, по которой идёт вся пагинация проекта. Тип
#: объявлен здесь, а не в сценарии стрима, потому что его задают эти выборки: сценарий
#: обязан пользоваться той же парой, а не собирать свою из чего попало.
type StreamPosition = tuple[datetime, uuid.UUID]

#: Состояния, в которых событие уже отработано и является историей, а не работой.
#: `FAILED` сюда входит: попытки исчерпаны, само оно больше не повторится. Чистка
#: удаляет только эти два — `PENDING` не трогает никогда, каким бы старым он ни был.
PROCESSED_STATUSES: tuple[OutboxStatus, ...] = (OutboxStatus.DELIVERED, OutboxStatus.FAILED)


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

    async def get(self, event_id: uuid.UUID) -> OutboxEvent | None:
        """Одно событие по идентификатору.

        Нужно стриму: `Last-Event-ID` разрешается в позицию `(created_at, id)`, с
        которой поток продолжает выдачу.
        """
        statement = select(OutboxEvent).where(OutboxEvent.id == event_id)
        return (await self._session.scalars(statement)).one_or_none()

    async def latest_position(self) -> StreamPosition | None:
        """Позиция самого свежего события или `None`, если очередь пуста.

        Стрим, открытый без `Last-Event-ID`, начинает отсюда: клиент, не назвавший
        курсор, просит «что будет дальше», а не историю установки.
        """
        statement = (
            select(OutboxEvent.created_at, OutboxEvent.id)
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else (row[0], row[1])

    async def list_after(
        self,
        *,
        position: StreamPosition | None,
        event_types: Collection[str] = (),
        limit: int,
    ) -> list[OutboxEvent]:
        """События строго после позиции, в порядке появления.

        Тот же порядок `(created_at, id)`, что у пагинации и у выборки воркера: поток
        обязан отдавать события в том порядке, в каком они происходили, иначе клиент,
        восстанавливающий состояние по потоку, получит «закрыта» перед «открыта».

        Отбор по типу идёт здесь, отбор по очереди и проекту — в сценарии: первое
        ложится на индекс, второе считается из нагрузки и в SQL не выражается без
        второй реализации разбора события.
        """
        statement = select(OutboxEvent)
        if position is not None:
            statement = statement.where(tuple_(OutboxEvent.created_at, OutboxEvent.id) > position)
        if event_types:
            statement = statement.where(OutboxEvent.event_type.in_(sorted(event_types)))
        statement = statement.order_by(OutboxEvent.created_at, OutboxEvent.id).limit(limit)
        return list(await self._session.scalars(statement))

    async def count_after(
        self,
        *,
        position: StreamPosition,
        event_types: Collection[str] = (),
    ) -> int:
        """Сколько событий появилось после позиции.

        Нужно стриму ровно для одного решения: влезает ли отставание клиента в окно
        переподключения. Считать приходится точно, а не «есть ли что-то»: клиент,
        отставший на три события, и клиент, отставший на три тысячи, обслуживаются
        по-разному.
        """
        statement = select(func.count()).select_from(OutboxEvent)
        statement = statement.where(tuple_(OutboxEvent.created_at, OutboxEvent.id) > position)
        if event_types:
            statement = statement.where(OutboxEvent.event_type.in_(sorted(event_types)))
        return int((await self._session.scalar(statement)) or 0)

    async def list_page(
        self,
        *,
        event_types: Collection[str] = (),
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[OutboxEvent]:
        """Лента событий страницами, от старого к новому — как все коллекции проекта.

        Тот же порядок `(created_at, id)`, что у выборки потока: страница ленты и кадр
        потока обязаны идти в одном порядке, иначе клиент, догоняющий историю после
        разрыва, склеит её не в том виде, в каком события происходили.
        """
        statement = select(OutboxEvent)
        if event_types:
            statement = statement.where(OutboxEvent.event_type.in_(sorted(event_types)))
        return await paginate(self._session, statement, OutboxEvent, limit=limit, cursor=cursor)

    async def replay_floor(self, *, replay_limit: int) -> StreamPosition | None:
        """Позиция самого старого события, которое обязано пережить чистку.

        Это и есть защита обещания, данного `TRACKER_STREAM_REPLAY_LIMIT`: поток
        пускает клиента, пока после его курсора лежит не больше `replay_limit`
        событий, значит уцелеть обязаны `replay_limit + 1` самых свежих — у последнего
        из них отставание равно ровно лимиту. Отсюда `OFFSET replay_limit`.

        `None` означает, что событий в очереди меньше, чем обещает окно: удалять из неё
        нельзя ничего, каким бы старым ни был её хвост.

        Отбор по типам событий здесь не применяется намеренно. Поток, суженный
        `event_types`, считает отставание только по своим типам, поэтому в абсолютных
        событиях его окно шире; покрыть его полом нельзя ничем ограниченным, и обещание
        поэтому сформулировано абсолютно — см. `app/domain/retention.py`.
        """
        statement = (
            select(OutboxEvent.created_at, OutboxEvent.id)
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
            .offset(replay_limit)
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else (row[0], row[1])

    def _expired(
        self,
        *,
        cutoff: datetime,
        floor: StreamPosition | None,
    ) -> Select[tuple[uuid.UUID]]:
        """Идентификаторы событий, которые чистка вправе удалить, от самых старых.

        Два ограничителя разом: возраст и пол окна переподключения. Пол `None` —
        удалять нельзя ничего, и выборка это выражает заведомо ложным условием, а не
        отсутствием строки в коде вызывающего.
        """
        statement = (
            select(OutboxEvent.id)
            .where(
                OutboxEvent.status.in_(PROCESSED_STATUSES),
                OutboxEvent.created_at < cutoff,
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
        )
        if floor is None:
            return statement.where(false())
        return statement.where(tuple_(OutboxEvent.created_at, OutboxEvent.id) < floor)

    async def count_expired(self, *, cutoff: datetime, floor: StreamPosition | None) -> int:
        """Сколько событий чистка удалит, если её не ограничивать потолком прохода."""
        expired = self._expired(cutoff=cutoff, floor=floor).subquery()
        statement = select(func.count()).select_from(expired)
        return int((await self._session.scalar(statement)) or 0)

    async def count_kept_by_window(self, *, cutoff: datetime, floor: StreamPosition | None) -> int:
        """Сколько отработанных событий старше срока держит окно переподключения.

        Ненулевое значение — это и есть несогласованность срока с окном, выраженная
        числом: строки, которые срок хранения удалил бы, а окно не даёт. Сравнивать
        дни с событиями напрямую нельзя, а этот счётчик сравним с обоими.
        """
        statement = (
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.status.in_(PROCESSED_STATUSES),
                OutboxEvent.created_at < cutoff,
            )
        )
        if floor is not None:
            statement = statement.where(tuple_(OutboxEvent.created_at, OutboxEvent.id) >= floor)
        return int((await self._session.scalar(statement)) or 0)

    async def delete_expired(
        self,
        *,
        cutoff: datetime,
        floor: StreamPosition | None,
        limit: int,
    ) -> int:
        """Удаляет одну пачку самых старых событий. Возвращает число удалённых строк.

        Удаление идёт по списку идентификаторов, а не условием напрямую: `DELETE` с
        `LIMIT` PostgreSQL не поддерживает, а без потолка одна команда сняла бы миллион
        строк за раз — с блокировкой на всё время выполнения и разом выросшим WAL.
        """
        victims = self._expired(cutoff=cutoff, floor=floor).limit(limit)
        statement = delete(OutboxEvent).where(OutboxEvent.id.in_(victims.scalar_subquery()))
        result = await self._session.execute(
            statement,
            execution_options={"synchronize_session": False},
        )
        return result.rowcount or 0
