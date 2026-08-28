"""Выборки и изменения по связям задач, включая подъём по иерархии.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Здесь же живёт единственный в проекте рекурсивный запрос. Он нужен обеим механикам
иерархии: проверке цикла (подъём вверх по родителям) и построению дерева (спуск вниз
уровнями). Спуск сделан не рекурсивным CTE, а запросом на уровень, потому что выдача
всё равно ограничена глубиной и числом узлов — и потому что каждый уровень отдаёт
задачи со всеми их связями, а `selectin` делает это одной пачкой на уровень.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import Integer, Uuid, cast, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.link import IssueLink
from app.db.pagination import Page, paginate
from app.domain.links import HIERARCHY_STORED_TYPE, MAX_HIERARCHY_DEPTH, LinkType


class IssueLinkRepository:
    """Доступ к таблице `issue_links`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, link_id: uuid.UUID) -> IssueLink | None:
        statement = select(IssueLink).where(IssueLink.id == link_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def find(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        link_type: LinkType,
    ) -> IssueLink | None:
        """Связь по канонической тройке. Ищется уже приведённое направление.

        Приводить направление здесь нельзя: для симметричных типов порядок зависит от
        ключей задач, а их эта таблица не знает. Канонизацию делает сценарий.
        """
        statement = select(IssueLink).where(
            IssueLink.source_id == source_id,
            IssueLink.target_id == target_id,
            IssueLink.link_type == link_type,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_for_issue_page(
        self,
        issue_id: uuid.UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[IssueLink]:
        """Страница связей задачи: и те, где она источник, и те, где она цель.

        Одним запросом с `OR`, а не двумя выборками с последующей склейкой: склеенные
        страницы пришлось бы сортировать в памяти, и курсорная пагинация перестала бы
        работать — курсор указывает позицию в одном упорядоченном запросе.
        """
        statement = select(IssueLink).where(
            or_(IssueLink.source_id == issue_id, IssueLink.target_id == issue_id)
        )
        return await paginate(self._session, statement, IssueLink, limit=limit, cursor=cursor)

    async def parent_link(self, child_id: uuid.UUID) -> IssueLink | None:
        """Связь с родителем, если он есть. У задачи их не больше одной."""
        statement = select(IssueLink).where(
            IssueLink.source_id == child_id,
            IssueLink.link_type == HIERARCHY_STORED_TYPE,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def children(self, parent_ids: Sequence[uuid.UUID]) -> list[IssueLink]:
        """Связи детей сразу для набора родителей — один запрос на уровень дерева.

        Порядок — по времени создания связи, а не по ключу задачи: ключ содержит номер,
        и строковая сортировка поставила бы `TRK-10` перед `TRK-2`. Порядок появления
        связей устойчив и объясним.
        """
        if not parent_ids:
            return []
        statement = (
            select(IssueLink)
            .where(
                IssueLink.target_id.in_(parent_ids),
                IssueLink.link_type == HIERARCHY_STORED_TYPE,
            )
            .order_by(IssueLink.created_at, IssueLink.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def has_ancestor(self, *, issue_id: uuid.UUID, ancestor_id: uuid.UUID) -> bool:
        """Встречается ли `ancestor_id` при подъёме от `issue_id` вверх по родителям.

        Сама задача считается своим предком: подъём начинается с неё. Это и нужно
        проверке цикла — связь «ребёнок → родитель» замкнёт кольцо ровно тогда, когда
        будущий родитель уже находится под будущим ребёнком.

        Рекурсия, а не цикл запросов в Python: глубина заранее неизвестна, а кольцо из
        трёх задач ломает дерево так же, как из двух. Одним запросом это и один
        round-trip, и работа на индексе `ix_issue_links_source_id_link_type`.

        `depth` — не украшение. Родитель у задачи один, поэтому в здоровой базе цепочка
        конечна, но если цикл всё же появился (проверка живёт в сценарии и на гонку
        двух одновременных запросов не рассчитана), без ограничения запрос крутился бы
        вечно. `UNION ALL` вместо `UNION` выбран сознательно: `UNION` глушил бы повтор
        и маскировал ровно ту ситуацию, ради которой стоит ограничитель.
        """
        chain = select(
            cast(literal(issue_id), Uuid).label("issue_id"),
            cast(literal(0), Integer).label("depth"),
        ).cte("chain", recursive=True)
        step = aliased(IssueLink)
        chain = chain.union_all(
            select(step.target_id, chain.c.depth + 1).where(
                step.source_id == chain.c.issue_id,
                step.link_type == HIERARCHY_STORED_TYPE,
                chain.c.depth < MAX_HIERARCHY_DEPTH,
            )
        )
        statement = select(chain.c.issue_id).where(chain.c.issue_id == ancestor_id).limit(1)
        return (await self._session.scalar(statement)) is not None

    async def add(self, link: IssueLink) -> IssueLink:
        self._session.add(link)
        await self._session.flush()
        return link

    async def delete(self, link: IssueLink) -> None:
        await self._session.delete(link)
        await self._session.flush()
