"""Выборки по проектам и портфелям, обход вложенности и подсчёт прогресса.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

## Прогресс считается страницей, а не по одному объекту

Все функции подсчёта принимают **набор** идентификаторов и возвращают словарь. Иначе
страница из пятидесяти проектов означала бы пятьдесят запросов `COUNT`, и список
проектов стал бы самым дорогим эндпоинтом в API. Отсутствующий в словаре ключ — это
проект без задач, а не потерянный результат: `GROUP BY` не возвращает строк для пустых
групп, и разбирать это должен вызывающий (`app/services/projects.py` подставляет нулевой
`Progress`).

## Второй рекурсивный запрос проекта, и он такой же, как первый

Обход вложенности портфелей устроен ровно как подъём по родителям задач
(`app/db/repositories/links.py`): рекурсивный CTE с ограничителем глубины и `UNION ALL`.
`UNION` вместо `UNION ALL` здесь был бы ошибкой — он заглушил бы повтор и спрятал
кольцо, ради которого ограничитель и стоит.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import Integer, Select, Uuid, cast, func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.models.project import Portfolio, Project
from app.db.pagination import Page, decode_cursor, encode_cursor, paginate, resolve_limit
from app.domain.catalogs import StatusCategory
from app.domain.projects import MAX_PORTFOLIO_DEPTH, PlanningKind, Progress, ProjectStatus


class ProjectRepository:
    """Доступ к таблице `projects` и к счётчикам задач по проектам."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_by_key(self, key: str) -> Project | None:
        statement = select(Project).where(Project.key == key)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        portfolio_id: uuid.UUID | None = None,
        status: ProjectStatus | None = None,
        is_archived: bool | None = None,
        lead_id: uuid.UUID | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Project]:
        """Страница проектов в порядке создания.

        `portfolio_id` отбирает проекты **прямых** детей портфеля, а не всех потомков:
        «что лежит в этом портфеле» и «какие проекты под ним вообще» — разные вопросы,
        и второй обслуживает прогресс, а не список.
        """
        return await paginate(
            self._session,
            _filtered(select(Project), Project, portfolio_id, status, is_archived, lead_id),
            Project,
            limit=limit,
            cursor=cursor,
        )

    async def progress_of(self, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Progress]:
        """Счётчики задач по каждому проекту набора: всего и в статусах категории `done`.

        Один запрос на всю страницу. `count(*) FILTER (WHERE ...)` вместо второго
        запроса или `sum(case ...)`: обе цифры берутся за один проход по тем же строкам,
        и план не расходится между «всего» и «сделано».

        Категория статуса, а не его ключ: команда переименовывает «Закрыт» в «Готово»,
        и прогресс от этого меняться не должен.
        """
        if not project_ids:
            return {}
        statement = (
            select(
                Issue.project_id,
                func.count(Issue.id),
                func.count(Issue.id).filter(Status.category == StatusCategory.DONE),
            )
            .join(Status, Status.id == Issue.status_id)
            .where(Issue.project_id.in_(list(project_ids)))
            .group_by(Issue.project_id)
        )
        rows = await self._session.execute(statement)
        return {row[0]: Progress(total=row[1], done=row[2]) for row in rows}

    async def count_in_portfolios(
        self,
        portfolio_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Сколько проектов лежит непосредственно в каждом портфеле набора."""
        if not portfolio_ids:
            return {}
        statement = (
            select(Project.portfolio_id, func.count(Project.id))
            .where(Project.portfolio_id.in_(list(portfolio_ids)))
            .group_by(Project.portfolio_id)
        )
        return {row[0]: row[1] for row in await self._session.execute(statement)}

    async def load_many(self, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Project]:
        """Проекты набора одним запросом: состав портфеля читается пачкой, а не по одному."""
        if not project_ids:
            return {}
        statement = select(Project).where(Project.id.in_(list(project_ids)))
        return {item.id: item for item in (await self._session.scalars(statement)).unique()}

    async def add(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        return project

    async def flush(self) -> None:
        await self._session.flush()


class PortfolioRepository:
    """Доступ к таблице `portfolios`, обход вложенности и агрегация прогресса."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, portfolio_id: uuid.UUID) -> Portfolio | None:
        return await self._session.get(Portfolio, portfolio_id)

    async def get_by_key(self, key: str) -> Portfolio | None:
        statement = select(Portfolio).where(Portfolio.key == key)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        parent_id: uuid.UUID | None = None,
        status: ProjectStatus | None = None,
        is_archived: bool | None = None,
        lead_id: uuid.UUID | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Portfolio]:
        """Страница портфелей в порядке создания; `parent_id` — прямые дети портфеля."""
        return await paginate(
            self._session,
            _filtered(select(Portfolio), Portfolio, parent_id, status, is_archived, lead_id),
            Portfolio,
            limit=limit,
            cursor=cursor,
        )

    async def count_children(self, portfolio_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Сколько портфелей вложено непосредственно в каждый портфель набора."""
        if not portfolio_ids:
            return {}
        statement = (
            select(Portfolio.parent_id, func.count(Portfolio.id))
            .where(Portfolio.parent_id.in_(list(portfolio_ids)))
            .group_by(Portfolio.parent_id)
        )
        return {row[0]: row[1] for row in await self._session.execute(statement)}

    async def has_ancestor(
        self,
        *,
        portfolio_id: uuid.UUID,
        ancestor_id: uuid.UUID,
    ) -> bool:
        """Встречается ли `ancestor_id` при подъёме от `portfolio_id` вверх по родителям.

        Сам портфель считается своим предком: подъём начинается с него. Это и нужно
        проверке цикла — вложение «A внутрь B» замкнёт кольцо ровно тогда, когда A уже
        находится над B (или является им).

        `depth` — не украшение: родитель у портфеля один, поэтому в здоровой базе
        цепочка конечна, но проверка живёт в сценарии и на гонку двух одновременных
        запросов не рассчитана. Без ограничителя уже возникшее кольцо крутило бы запрос
        вечно.
        """
        chain = select(
            cast(literal(portfolio_id), Uuid).label("portfolio_id"),
            cast(literal(0), Integer).label("depth"),
        ).cte("ancestors", recursive=True)
        step = aliased(Portfolio)
        chain = chain.union_all(
            select(step.parent_id, chain.c.depth + 1).where(
                step.id == chain.c.portfolio_id,
                step.parent_id.is_not(None),
                chain.c.depth < MAX_PORTFOLIO_DEPTH,
            )
        )
        statement = select(chain.c.portfolio_id).where(chain.c.portfolio_id == ancestor_id).limit(1)
        return (await self._session.scalar(statement)) is not None

    async def progress_of(self, portfolio_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Progress]:
        """Прогресс каждого портфеля набора, агрегированный **по задачам** его потомков.

        Спуск и агрегация — один запрос: рекурсивный CTE разворачивает каждый портфель
        в список его потомков, сохраняя рядом идентификатор корня, и уже к нему
        подшиваются проекты, задачи и статусы. Поэтому страница портфелей стоит одного
        запроса, а не одного на портфель.

        Формула — `сумма done / сумма total` по всем задачам под портфелем (см.
        `app/domain/projects.py`, `aggregate`). Среднее от детей дало бы другое число,
        и вложенный портфель пришлось бы взвешивать отдельно; у суммы вложенность
        схлопывается сама.

        Ограничитель глубины стоит здесь по той же причине, что и в подъёме: кольцо,
        если оно возникло, обязано сломать один запрос, а не повесить процесс.
        """
        if not portfolio_ids:
            return {}

        subtree = select(
            cast(Portfolio.id, Uuid).label("root_id"),
            cast(Portfolio.id, Uuid).label("portfolio_id"),
            cast(literal(0), Integer).label("depth"),
        ).where(Portfolio.id.in_(list(portfolio_ids)))
        tree = subtree.cte("subtree", recursive=True)
        child = aliased(Portfolio)
        tree = tree.union_all(
            select(tree.c.root_id, child.id, tree.c.depth + 1).where(
                child.parent_id == tree.c.portfolio_id,
                tree.c.depth < MAX_PORTFOLIO_DEPTH,
            )
        )

        statement = (
            select(
                tree.c.root_id,
                func.count(Issue.id),
                func.count(Issue.id).filter(Status.category == StatusCategory.DONE),
            )
            .select_from(tree)
            .join(Project, Project.portfolio_id == tree.c.portfolio_id)
            .join(Issue, Issue.project_id == Project.id)
            .join(Status, Status.id == Issue.status_id)
            .group_by(tree.c.root_id)
        )
        rows = await self._session.execute(statement)
        return {row[0]: Progress(total=row[1], done=row[2]) for row in rows}

    async def content_page(
        self,
        portfolio_id: uuid.UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[tuple[PlanningKind, uuid.UUID]]:
        """Страница состава портфеля: вложенные портфели и проекты одним списком.

        Порядок общий — по паре `(created_at, id)`, как во всём проекте, — поэтому
        страницы не зависят от того, чего в портфеле больше. Собрать две отдельные
        страницы и склеить их в памяти было бы нельзя: курсор указывает позицию в
        **одном** упорядоченном запросе, и склейка сломала бы пагинацию на первой же
        границе.

        Возвращаются пары «вид + идентификатор», а не сами объекты: в одной выборке
        строки двух разных таблиц, и общего ORM-типа у них нет. Загрузку объектов
        двумя пачками делает сценарий — он же знает, что именно ему нужно.
        """
        size = resolve_limit(limit)
        columns = (
            literal(PlanningKind.PORTFOLIO.value).label("kind"),
            Portfolio.id.label("id"),
            Portfolio.created_at.label("created_at"),
        )
        nested = select(*columns).where(Portfolio.parent_id == portfolio_id)
        projects = select(
            literal(PlanningKind.PROJECT.value),
            Project.id,
            Project.created_at,
        ).where(Project.portfolio_id == portfolio_id)
        union = nested.union_all(projects).subquery("content")

        statement = select(union.c.kind, union.c.id, union.c.created_at)
        if cursor is not None:
            created_at, item_id = decode_cursor(cursor)
            statement = statement.where(
                tuple_(union.c.created_at, union.c.id) > (created_at, item_id)
            )
        statement = statement.order_by(union.c.created_at, union.c.id).limit(size + 1)

        rows = list(await self._session.execute(statement))
        items = [(PlanningKind(row[0]), row[1]) for row in rows[:size]]
        if len(rows) <= size:
            return Page(items=items, next_cursor=None)
        last = rows[size - 1]
        return Page(items=items, next_cursor=encode_cursor(last[2], last[1]))

    async def load_many(
        self,
        portfolio_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, Portfolio]:
        """Портфели набора одним запросом: состав грузится пачкой, а не по одному."""
        if not portfolio_ids:
            return {}
        statement = select(Portfolio).where(Portfolio.id.in_(list(portfolio_ids)))
        return {item.id: item for item in (await self._session.scalars(statement)).unique()}

    async def add(self, portfolio: Portfolio) -> Portfolio:
        self._session.add(portfolio)
        await self._session.flush()
        return portfolio

    async def flush(self) -> None:
        await self._session.flush()


def _filtered[ModelT: (Project, Portfolio)](
    statement: Select[tuple[ModelT]],
    model: type[ModelT],
    parent_id: uuid.UUID | None,
    status: ProjectStatus | None,
    is_archived: bool | None,
    lead_id: uuid.UUID | None,
) -> Select[tuple[ModelT]]:
    """Общие фильтры списка. Родитель у проекта — портфель, у портфеля — портфель же.

    Одна функция на обе таблицы: набор фильтров у них одинаков, и две почти одинаковые
    сборки условий однажды разошлись бы обработкой `is_archived=False`, где разница
    между «не в архиве» и «фильтра нет» решает всё.
    """
    parent_column = model.portfolio_id if model is Project else model.parent_id
    if parent_id is not None:
        statement = statement.where(parent_column == parent_id)
    if status is not None:
        statement = statement.where(model.status == status)
    if is_archived is not None:
        statement = statement.where(model.is_archived == is_archived)
    if lead_id is not None:
        statement = statement.where(model.lead_id == lead_id)
    return statement
