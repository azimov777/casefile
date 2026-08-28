"""Выборки по доскам, спринтам и рангу карточек.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

## Порядок карточек: одна вычислимая позиция у каждой задачи

Позиция задачи на доске — `COALESCE(issue_ranks.position, <виртуальная>)`, где
виртуальная выводится из `created_at` (`app/domain/boards.py`, `virtual_position`). Обе
половины — целые одной шкалы, поэтому порядок полный, а «поставить между этими двумя»
всегда сводится к арифметике и меняет одну строку.

Соблазн отсортировать «сначала ранжированные, потом остальные по времени» (`NULLS
LAST`) выглядит проще и ошибочен: в таком порядке «поставить карточку в самый конец»
недостижимо — ранжированная задача не может оказаться после неранжированной, и клиент
получал бы успешный ответ на невыполненную операцию.

Цена решения названа прямо: `ORDER BY` идёт по выражению, а не по колонке, поэтому
страница доски сортирует весь отобранный набор. На доске в тысячи задач это миллисекунды,
на доске в миллионы — уже нет; тогда потребуется материализованный ранг у всех задач
доски, то есть отказ от виртуальной половины шкалы.

## Формула виртуальной позиции продублирована в SQL, и это проверяется тестом

То же число обязан давать Python (`virtual_position`): сценарий считает новую позицию из
позиций соседей, полученных отсюда. Разойдись они — карточка встала бы не туда, куда её
положили, и заметить это можно было бы только глазами. Совпадение стережёт
`tests/test_boards_service.py::test_the_virtual_position_matches_the_one_computed_in_sql`.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import (
    BigInteger,
    Numeric,
    Select,
    and_,
    cast,
    extract,
    func,
    literal,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.board import Board, BoardColumnStatus, IssueRank, Sprint
from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.pagination import Page, paginate
from app.db.repositories.search import issue_page
from app.domain.boards import RANK_SCALE, SprintState
from app.domain.catalogs import StatusCategory
from app.domain.ranking import POSITION_STEP

#: Микросекунд в секунде: множитель виртуальной шкалы. Вынесен константой, потому что
#: то же число стоит в `app/domain/boards.py` — там оно получается делением на
#: `timedelta(microseconds=1)`, здесь умножением на секунды эпохи.
_MICROSECONDS_PER_SECOND = 1_000_000


class BoardRepository:
    """Доступ к таблицам `boards`, `board_columns` и `board_column_statuses`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, board_id: uuid.UUID) -> Board | None:
        statement = select(Board).where(Board.id == board_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        saved_filter_id: uuid.UUID | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Board]:
        """Страница досок в порядке создания."""
        statement = select(Board)
        if saved_filter_id is not None:
            statement = statement.where(Board.saved_filter_id == saved_filter_id)
        return await paginate(self._session, statement, Board, limit=limit, cursor=cursor)

    async def column_of_status(
        self,
        board_id: uuid.UUID,
        status_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """В какой колонке доски уже лежит этот статус. `None` — ни в какой.

        Проверка сценария поверх уникального ограничения: без неё клиент получал бы
        голый `409 conflict` с именем ограничения вместо внятного «статус уже в другой
        колонке».
        """
        statement = select(BoardColumnStatus.column_id).where(
            BoardColumnStatus.board_id == board_id,
            BoardColumnStatus.status_id == status_id,
        )
        return await self._session.scalar(statement)

    async def count_columns_with_status(self, status_id: uuid.UUID) -> int:
        """Сколько колонок досок разложило этот статус.

        От ответа зависит запрет на удаление статуса: каскад по `status_id` нужен для
        удаления очереди, но он же молча оставил бы колонку без единого статуса, а
        такая колонка показывает все задачи доски.
        """
        statement = (
            select(func.count())
            .select_from(BoardColumnStatus)
            .where(BoardColumnStatus.status_id == status_id)
        )
        return await self._session.scalar(statement) or 0

    async def count_sprints(self, board_id: uuid.UUID) -> int:
        """Сколько спринтов у доски. От ответа зависит, можно ли доску удалить."""
        statement = select(func.count()).select_from(Sprint).where(Sprint.board_id == board_id)
        return await self._session.scalar(statement) or 0

    async def add(self, board: Board) -> Board:
        self._session.add(board)
        await self._session.flush()
        return board

    async def delete(self, board: Board) -> None:
        await self._session.delete(board)
        await self._session.flush()

    async def flush(self) -> None:
        await self._session.flush()


class SprintRepository:
    """Доступ к таблице `sprints` и к задачам, взятым в спринт."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, sprint_id: uuid.UUID) -> Sprint | None:
        statement = select(Sprint).where(Sprint.id == sprint_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        board_id: uuid.UUID | None = None,
        state: SprintState | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Sprint]:
        """Страница спринтов в порядке создания."""
        statement = select(Sprint)
        if board_id is not None:
            statement = statement.where(Sprint.board_id == board_id)
        if state is not None:
            statement = statement.where(Sprint.state == state)
        return await paginate(self._session, statement, Sprint, limit=limit, cursor=cursor)

    async def active_of_board(self, board_id: uuid.UUID) -> Sprint | None:
        """Активный спринт доски. Их не больше одного — это держит частичный индекс."""
        statement = select(Sprint).where(
            Sprint.board_id == board_id,
            Sprint.state == SprintState.ACTIVE,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def count_issues(self, sprint_id: uuid.UUID) -> int:
        """Сколько задач взято в спринт. От ответа зависит, можно ли его удалить."""
        statement = select(func.count()).select_from(Issue).where(Issue.sprint_id == sprint_id)
        return await self._session.scalar(statement) or 0

    async def unfinished_issues(self, sprint_id: uuid.UUID) -> list[Issue]:
        """Задачи спринта, не дошедшие до статуса категории `done`.

        Отдаются объектами, а не идентификаторами: каждую из них завершение спринта
        проводит через единую точку изменения задачи, и без объекта туда не зайти.
        Отсюда и ограничение, которое надо знать: завершение спринта на тысячу
        незакрытых задач поднимет в память тысячу задач.

        Категория статуса, а не его ключ: команда переименовывает «Закрыт» в «Готово»,
        и от этого состав переноса меняться не должен.
        """
        statement = (
            select(Issue)
            .join(Status, Status.id == Issue.status_id)
            .where(Issue.sprint_id == sprint_id, Status.category != StatusCategory.DONE)
            .order_by(Issue.created_at, Issue.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def add(self, sprint: Sprint) -> Sprint:
        self._session.add(sprint)
        await self._session.flush()
        return sprint

    async def delete(self, sprint: Sprint) -> None:
        await self._session.delete(sprint)
        await self._session.flush()

    async def flush(self) -> None:
        await self._session.flush()


class BoardIssueRepository:
    """Задачи доски: страница в порядке ранга, соседние позиции и перенумерация.

    Условие отбора (`scope`) приходит уже скомпилированным из фильтра доски
    (`app/db/repositories/search.py`, `compile_filter`). Своего разбора здесь нет и быть
    не должно: доска обязана понимать `assignee: me()` ровно так же, как поиск.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(
        self,
        board_id: uuid.UUID,
        scope: ColumnElement[bool] | None,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Issue]:
        """Страница задач доски в порядке ранга.

        Порядок задаёт доска, а не клиент: параметра сортировки у неё нет намеренно —
        иначе одна и та же доска показывала бы разный порядок в зависимости от запроса,
        и перетаскивание карточки перестало бы что-либо значить.
        """
        rank = aliased(IssueRank)
        statement: Select[tuple[Issue]] = select(Issue).outerjoin(
            rank,
            and_(rank.issue_id == Issue.id, rank.board_id == board_id),
        )
        if scope is not None:
            statement = statement.where(scope)
        keys = [(_effective_position(rank), False)]
        return await issue_page(self._session, statement, keys, limit=limit, cursor=cursor)

    async def contains(self, scope: ColumnElement[bool] | None, issue_id: uuid.UUID) -> bool:
        """Попадает ли задача в область доски.

        Проверяется перед ранжированием и перемещением: молча записанный ранг задачи
        вне области остался бы в базе навсегда, а клиент решил бы, что карточка
        переставлена.
        """
        statement = select(Issue.id).where(Issue.id == issue_id)
        if scope is not None:
            statement = statement.where(scope)
        return await self._session.scalar(statement) is not None

    async def position_of(self, board_id: uuid.UUID, issue_id: uuid.UUID) -> int | None:
        """Эффективная позиция задачи на доске; `None` — задачи нет вовсе.

        Считается в SQL, а не в Python по `created_at`: у задачи может быть явный ранг,
        и выбирать между двумя источниками должен один запрос, а не вызывающий.
        """
        rank = aliased(IssueRank)
        statement = (
            select(_effective_position(rank))
            .select_from(Issue)
            .outerjoin(rank, and_(rank.issue_id == Issue.id, rank.board_id == board_id))
            .where(Issue.id == issue_id)
        )
        return await self._session.scalar(statement)

    async def adjacent_position(
        self,
        board_id: uuid.UUID,
        scope: ColumnElement[bool] | None,
        *,
        anchor: tuple[int, uuid.UUID] | None,
        forward: bool,
        exclude_issue_id: uuid.UUID,
    ) -> int | None:
        """Позиция ближайшего соседа по порядку доски; `None` — соседа нет.

        `anchor` — пара «позиция, идентификатор» опорной задачи; `None` означает край
        списка. Сравнение идёт кортежем, а не одной позицией: позиции могут совпасть у
        задач, созданных одной транзакцией, и без тайбрейкера по `id` сосед нашёлся бы
        не тот, что стоит рядом в выдаче.

        Перемещаемая задача из поиска исключается: без этого «поставить после соседа»
        находило бы саму задачу и не двигало бы её никуда.
        """
        rank = aliased(IssueRank)
        position = _effective_position(rank)
        statement = (
            select(position)
            .select_from(Issue)
            .outerjoin(rank, and_(rank.issue_id == Issue.id, rank.board_id == board_id))
            .where(Issue.id != exclude_issue_id)
        )
        if scope is not None:
            statement = statement.where(scope)
        if anchor is not None:
            comparison = tuple_(position, Issue.id)
            statement = statement.where(
                comparison > anchor if forward else comparison < anchor,
            )
        order = (position.asc(), Issue.id.asc()) if forward else (position.desc(), Issue.id.desc())
        return await self._session.scalar(statement.order_by(*order).limit(1))

    async def set_position(
        self,
        board_id: uuid.UUID,
        issue_id: uuid.UUID,
        position: int,
    ) -> None:
        """Записывает ранг задачи на доске, заводя строку или обновляя существующую.

        `ON CONFLICT`, а не «прочитать и решить»: два одновременных перетаскивания одной
        карточки иначе дали бы попытку вставить вторую строку и `409` вместо последнего
        выигравшего значения. `updated_at` проставляется явно — запись идёт мимо ORM, и
        `onupdate` до неё не доезжает.
        """
        statement = pg_insert(IssueRank).values(
            board_id=board_id,
            issue_id=issue_id,
            position=position,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[IssueRank.board_id, IssueRank.issue_id],
                set_={"position": statement.excluded.position, "updated_at": func.now()},
            )
        )

    async def rebalance(self, board_id: uuid.UUID, scope: ColumnElement[bool] | None) -> int:
        """Раздаёт всем задачам доски явные ранги с полным шагом, сохраняя порядок.

        Вызывается редко — когда зазор между соседями исчерпан, то есть у задач,
        созданных одной транзакцией и потому получивших одинаковую виртуальную позицию.
        Это единственная операция доски, которая пишет больше одной строки, и её цена
        названа прямо: она трогает **все** задачи в области доски.

        Побочное следствие, которое надо знать: после перенумерации задачи, попавшие на
        доску позже, встают в конец, а не по времени создания среди прежних. Их
        виртуальная позиция на много порядков больше выданных здесь, и это правильное
        поведение для доски — новая карточка приходит в конец бэклога.

        Одним `INSERT ... SELECT`, а не циклом: перенумерация в цикле означала бы
        столько запросов, сколько задач на доске, и делала бы редкую операцию дорогой
        ровно там, где она и так дорога.
        """
        rank = aliased(IssueRank)
        ordered = (
            select(
                Issue.id.label("issue_id"),
                func.row_number()
                .over(order_by=(_effective_position(rank), Issue.id))
                .label("place"),
            )
            .select_from(Issue)
            .outerjoin(rank, and_(rank.issue_id == Issue.id, rank.board_id == board_id))
        )
        if scope is not None:
            ordered = ordered.where(scope)
        source = ordered.subquery("ordered")

        # `id` перечислен явно и считается в SQL. Без этого SQLAlchemy подставляет
        # питоновский `default=uuid.uuid4` — **одно** значение параметра на весь
        # `INSERT ... SELECT`, и вставка со второй строки падает нарушением первичного
        # ключа. Сбой не молчаливый, но и не очевидный: у обычной вставки одного объекта
        # того же дефекта нет.
        statement = pg_insert(IssueRank).from_select(
            ["id", "board_id", "issue_id", "position"],
            select(
                func.gen_random_uuid(),
                literal(board_id),
                source.c.issue_id,
                cast(source.c.place * POSITION_STEP, BigInteger),
            ),
        )
        result = await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[IssueRank.board_id, IssueRank.issue_id],
                set_={"position": statement.excluded.position, "updated_at": func.now()},
            )
        )
        return result.rowcount

    async def issue_ids_in_scope(
        self,
        scope: ColumnElement[bool] | None,
        issue_ids: Sequence[uuid.UUID],
    ) -> set[uuid.UUID]:
        """Какие из задач попадают в область доски. Одним запросом на весь набор."""
        if not issue_ids:
            return set()
        statement = select(Issue.id).where(Issue.id.in_(list(issue_ids)))
        if scope is not None:
            statement = statement.where(scope)
        return set(await self._session.scalars(statement))


def _effective_position(rank: type[IssueRank]) -> ColumnElement[int]:
    """Позиция задачи в порядке доски: явный ранг либо виртуальный из времени создания.

    `rank` — псевдоним таблицы рангов, уже присоединённый внешним соединением по паре
    «задача + доска». Без псевдонима два вхождения таблицы в один запрос слились бы.
    """
    return func.coalesce(rank.position, _virtual_position(Issue.created_at))


def _virtual_position(column: ColumnElement[object]) -> ColumnElement[int]:
    """Виртуальная позиция: микросекунды эпохи, умноженные на шаг шкалы.

    Та же формула, что в `app/domain/boards.py`. Умножение делается до приведения к
    `bigint`, чтобы промежуточный результат считался в `numeric` и не мог переполниться;
    `extract(epoch ...)` в PostgreSQL 14+ возвращает `numeric` и микросекунды не теряет,
    в отличие от `float`, которому на числах такого порядка уже не хватает мантиссы.
    """
    micros = cast(extract("epoch", column), Numeric) * _MICROSECONDS_PER_SECOND
    return cast(func.trunc(micros) * RANK_SCALE, BigInteger)
