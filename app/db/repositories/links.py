"""Выборки и изменения по связям задач, включая обход графа при проверке цикла.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Здесь же живёт единственный в проекте рекурсивный запрос. Он отвечает на один вопрос —
достижима ли одна задача из другой по рёбрам **одного** вида, — и этого хватает и
иерархии, и блокировкам: графа два, а обход у них один.

Часть выборок объявлена функциями модуля, а не методами репозитория: `open_blockers_of`
— единственное определение признака `blocked` в SQL, и поиску нужен тот же запрос,
вложенный в `EXISTS` по каждой строке выдачи. Метод, привязанный к сессии, туда не
годится, а второе написание условия развело бы поиск с карточкой (`docs/notes/search.md`).
Так же объявлен `parents_of`: родители строки выдачи — подзапрос внутри выборки страницы.
"""

import uuid
from typing import Any

from sqlalchemy import Integer, Select, Uuid, cast, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.link import Link
from app.db.models.task import Task
from app.domain.links import MAX_LINK_DEPTH, LinkKind
from app.domain.tasks import CLOSED_STATUSES


class LinkRepository:
    """Доступ к таблице `links`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        kind: LinkKind,
    ) -> Link | None:
        """Связь по канонической тройке. Ищется уже приведённое направление.

        Приводить направление здесь нельзя: у симметричного вида порядок зависит от
        ключей задач, а их эта таблица не знает. Канонизацию делает сценарий.
        """
        statement = select(Link).where(
            Link.source_id == source_id,
            Link.target_id == target_id,
            Link.kind == kind,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_for_task(self, task_id: uuid.UUID) -> list[Link]:
        """Все связи задачи: и те, где она источник, и те, где она цель.

        Одним запросом с `OR`, а не двумя выборками со склейкой: склеенные списки
        пришлось бы сортировать в памяти, а порядок связей виден в карточке.

        Без страниц и без потолка — намеренно. Из этого же списка считается признак
        `blocked`, и обрезанная выдача сделала бы его ложью: невлезший блокер выглядел
        бы как его отсутствие. Связей у одной задачи единицы, а цена ошибки здесь —
        задача, взятая в работу поверх открытого блокера.

        Порядок — по времени появления связи, а не по ключу задачи на другой стороне:
        ключ содержит номер, и строковая сортировка поставила бы `TRK-10` перед `TRK-2`.
        """
        statement = (
            select(Link)
            .where(or_(Link.source_id == task_id, Link.target_id == task_id))
            .order_by(Link.created_at, Link.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def open_blocker_keys(self, task_id: uuid.UUID) -> list[str]:
        """Ключи задач, блокирующих эту и не закрытых: связь `blocks`, где она — цель.

        Отдельный запрос, а не фильтр по прочитанным связям: факты перехода собираются
        до того, как что-либо прочитано, и тащить ради них весь список связей значило
        бы платить лишним запросом за каждый переход в `backlog`.
        """
        return await self._ordered_keys(open_blockers_of(task_id))

    async def unclosed_child_keys(self, task_id: uuid.UUID) -> list[str]:
        """Ключи детей не в `done` и не в `cancelled`: связь `parent`, где она — источник."""
        return await self._ordered_keys(
            related_task_keys(task_id, kind=LinkKind.PARENT, as_source=True)
        )

    async def reaches(
        self,
        *,
        kind: LinkKind,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
    ) -> bool:
        """Достижима ли `to_id` из `from_id` по рёбрам `source → target` этого вида.

        Сама задача считается достижимой из себя: обход начинается с неё. Это и нужно
        проверке цикла — новое ребро `A → B` замкнёт кольцо ровно тогда, когда A уже
        достижима из B.

        Рекурсия, а не цикл запросов в Python: длина цепочки заранее неизвестна, а
        кольцо из трёх задач ломает граф так же, как из двух. Одним запросом это и один
        round-trip, и работа на индексе `ix_links_source_id_kind`.

        `depth` — не украшение. Кольцо в базе появиться всё-таки может: проверка живёт в
        сценарии и на гонку двух одновременных запросов не рассчитана
        (`docs/notes/links.md`). Без ограничителя запрос крутился бы вечно. `UNION ALL`
        вместо `UNION` выбран сознательно: `UNION` глушил бы повтор и маскировал ровно
        ту ситуацию, ради которой стоит ограничитель.
        """
        chain = select(
            cast(literal(from_id), Uuid).label("task_id"),
            cast(literal(0), Integer).label("depth"),
        ).cte("chain", recursive=True)
        step = aliased(Link)
        chain = chain.union_all(
            select(step.target_id, chain.c.depth + 1).where(
                step.source_id == chain.c.task_id,
                step.kind == kind,
                chain.c.depth < MAX_LINK_DEPTH,
            )
        )
        statement = select(chain.c.task_id).where(chain.c.task_id == to_id).limit(1)
        return (await self._session.scalar(statement)) is not None

    async def add(self, link: Link) -> Link:
        """Кладёт связь в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(link)
        await self._session.flush()
        return link

    async def delete(self, link: Link) -> None:
        await self._session.delete(link)
        await self._session.flush()

    async def _ordered_keys(self, statement: Select[tuple[str]]) -> list[str]:
        """Ключи в порядке появления связи, а не по ключу задачи на другой стороне.

        Порядок дописывается здесь, а не в самом запросе: тот же запрос уходит внутрь
        `EXISTS` у поиска, где сортировать нечего и незачем.
        """
        return list(await self._session.scalars(statement.order_by(Link.created_at, Link.id)))


def open_blockers_of(task_id: Any) -> Select[tuple[str]]:
    """Ключи незакрытых блокеров задачи — единственное определение признака `blocked`.

    Признак равен «есть связь `blocks`, где эта задача — цель, а задача-источник не в
    `done` и не в `cancelled`» (`CONCEPT.md`, 4.3). Отсюда его берут двое: проверка
    перехода в `in_progress` — списком ключей, и поиск — обёрткой `EXISTS` по каждой
    строке выдачи. Третьего написания этого условия быть не должно: разойдясь, поиск и
    карточка начнут отвечать по-разному на один вопрос.

    `task_id` поэтому и объявлен как `Any`: принимается и готовый идентификатор, и
    колонка внешнего запроса (`Task.id`). Задача на другой стороне берётся псевдонимом
    — без него запрос нельзя вложить в выборку по той же таблице.
    """
    return related_task_keys(task_id, kind=LinkKind.BLOCKS, as_source=False)


def related_task_keys(task_id: Any, *, kind: LinkKind, as_source: bool) -> Select[tuple[str]]:
    """Ключи незакрытых задач на другой стороне связей этого вида, без порядка.

    `as_source` — с какой стороны стоит сама задача: у детей она источник (`parent`), у
    блокеров — цель (`blocks`).
    """
    other = aliased(Task, name="related_task")
    own_side = Link.source_id if as_source else Link.target_id
    other_side = Link.target_id if as_source else Link.source_id
    return (
        select(other.key)
        .join(Link, other.id == other_side)
        .where(own_side == task_id, Link.kind == kind, other.status.not_in(CLOSED_STATUSES))
    )


def parents_of(task_id: Any) -> Select[tuple[Any]]:
    """Прямые родители задачи одним значением: JSON-список `{key, title}`, пустой — `[]`.

    Отдаётся не строками, а одним агрегатом, потому что поиск вкладывает запрос в
    выборку страницы скалярным подзапросом — колонкой рядом с признаками, — и родители
    всей страницы приезжают тем же запросом, что и сама страница, без запроса на строку
    (`CONCEPT.md`, 4.4). Строками запрос пришлось бы соединять со страницей, а соединение
    размножило бы задачу по числу родителей и сломало бы и страницу, и курсор.

    Родитель — источник связи `parent`, задача — её цель (`app/domain/links.py`,
    `canonical_form`), поэтому ребёнок ищется по `target_id`: тот же индекс
    `ix_links_target_id_kind`, что у отбора `parent:`. Порядок — появление связи, как у
    связей в карточке (`list_for_task`): ключ содержит номер, и строковый порядок поставил
    бы `TRK-10` перед `TRK-2`.

    `[]`, а не `NULL`, у задачи без родителей: у списка «ничего» — это пустой список, и
    второй способ сказать то же самое вызывающему пришлось бы помнить.
    """
    parent = aliased(Task, name="parent_task")
    listed = func.jsonb_agg(
        aggregate_order_by(
            func.jsonb_build_object("key", parent.key, "title", parent.title),
            Link.created_at,
            Link.id,
        )
    )
    return (
        select(func.coalesce(listed, text("'[]'::jsonb")))
        .select_from(Link)
        .join(parent, parent.id == Link.source_id)
        .where(Link.kind == LinkKind.PARENT, Link.target_id == task_id)
    )
