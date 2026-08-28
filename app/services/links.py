"""Сценарии связей между задачами: завести, удалить, прочитать, построить дерево.

## Одна строка на связь

Направление приводится к каноническому виду перед записью (`app/domain/links.py`), и
в таблицу ложится одна строка. Читается она с той стороны, с которой спросили: у
`depends_on` вторая сторона видит `blocks`. Две строки на связь означали бы, что
однажды одна из них удалится, а вторая останется, — и задача будет заблокирована
задачей, которая её не блокирует.

## Иерархия проверяется тремя правилами, и каждое ловит своё

- **у задачи типа «эпик» нет родителя** — эпик верхний уровень планирования;
- **у задачи не больше одного родителя** — иначе дерево перестаёт быть деревом;
- **цикла нет на любой глубине** — кольцо из трёх задач ломает обход так же, как из
  двух, поэтому проверка поднимается по цепочке родителей до конца, а не смотрит на
  один шаг назад.

Первые два правила продублированы в схеме (`app/db/models/link.py`): они выражаются
строкой и индексом. Третье выразить в базе нечем — это свойство графа целиком, — и
на одновременные запросы оно не рассчитано; цена названа в `docs/notes/links.md`.

Транзакцию сценарии не фиксируют: границу держит вход в приложение.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType
from app.db.models.issue import Issue
from app.db.models.link import IssueLink
from app.db.pagination import Page
from app.db.repositories import IssueLinkRepository
from app.domain.catalogs import EPIC_ISSUE_TYPE_KEY
from app.domain.errors import (
    EpicParentError,
    IssueLinkExistsError,
    IssueLinkNotFoundError,
    IssueParentExistsError,
    LinkCycleError,
    SelfLinkError,
)
from app.domain.links import (
    MAX_TREE_NODES,
    LinkType,
    canonical_form,
    is_hierarchy,
    validate_tree_depth,
    visible_type,
)
from app.services import events as events_service
from app.services.permissions import ensure_allowed


@dataclass(frozen=True, slots=True)
class IssueLinkView:
    """Связь глазами одной из двух задач.

    Отдельный тип, а не голая модель, потому что имя связи зависит от того, кто
    спрашивает: одна и та же строка — `depends_on` для источника и `blocks` для цели.
    Вычислять это в схеме ответа нельзя: то же самое нужно MCP и журналу изменений.
    """

    link: IssueLink
    link_type: LinkType
    issue: Issue


@dataclass(frozen=True, slots=True)
class IssueTreeNode:
    """Узел дерева иерархии: задача и её дети.

    `has_more_children` означает, что дети у узла есть, но в выдачу не поместились —
    кончилась глубина или потолок числа узлов. Флаг обязателен: без него обрезанное
    дерево неотличимо от полного, и клиент показал бы лист там, где на самом деле
    поддерево.
    """

    issue: Issue
    children: tuple[IssueTreeNode, ...]
    has_more_children: bool


@dataclass(slots=True)
class _TreeDraft:
    """Изменяемый узел на время обхода: готовый `IssueTreeNode` собирается в конце."""

    issue: Issue
    children: list[_TreeDraft] = field(default_factory=list)
    has_more_children: bool = False

    def freeze(self) -> IssueTreeNode:
        return IssueTreeNode(
            issue=self.issue,
            children=tuple(child.freeze() for child in self.children),
            has_more_children=self.has_more_children,
        )


# --- Чтение ----------------------------------------------------------------------


async def get_issue_link(session: AsyncSession, issue: Issue, link_id: uuid.UUID) -> IssueLink:
    """Связь этой задачи по идентификатору или `link_not_found`.

    Принадлежность проверяется здесь, а не в роутере: связь адресуется в пути своей
    задачей, и чужая связь для клиента — то же самое, что несуществующая. Иначе по
    идентификатору можно было бы удалить связь, о которой запрос ничего не знал.
    """
    link = await IssueLinkRepository(session).get_by_id(link_id)
    if link is None or issue.id not in (link.source_id, link.target_id):
        raise IssueLinkNotFoundError(details={"link": str(link_id), "issue": issue.key})
    return link


async def list_issue_links(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[IssueLinkView]:
    """Страница связей задачи — все типы, обе стороны, каждая своим именем."""
    ensure_allowed(initiator, "issue.links", target=issue)
    page = await IssueLinkRepository(session).list_for_issue_page(
        issue.id,
        limit=limit,
        cursor=cursor,
    )
    return Page(
        items=[link_view(link, issue) for link in page.items],
        next_cursor=page.next_cursor,
    )


def link_view(link: IssueLink, issue: Issue) -> IssueLinkView:
    """Связь с точки зрения одной из её задач."""
    from_source = link.source_id == issue.id
    return IssueLinkView(
        link=link,
        link_type=visible_type(link.link_type, from_source=from_source),
        issue=link.other_side(issue.id),
    )


async def build_tree(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    depth: int | None = None,
) -> IssueTreeNode:
    """Дерево подзадач от этой задачи вниз, не глубже заданного числа уровней.

    Обход идёт уровнями, а не рекурсивным запросом, и это осознанный выбор. Уровень
    целиком берётся одним запросом, а `selectin` подтягивает задачи уровня и их
    справочники пачкой; рекурсивный CTE вернул бы те же строки, но собирать по ним
    ORM-объекты со связями пришлось бы всё равно — выигрыша нет, а читаемость хуже.

    Два ограничителя, и оба обязательны. Глубина отсекает длинные цепочки, потолок
    числа узлов — широкие эпики, где второй уровень уже даёт сотни задач. Ни один не
    режет молча: узел, чьи дети не поместились, помечается `has_more_children`.
    """
    ensure_allowed(initiator, "issue.tree", target=issue)
    levels = validate_tree_depth(depth)
    repository = IssueLinkRepository(session)

    root = _TreeDraft(issue=issue)
    # Дети берутся только у тех, кого мы ещё не видели. При одном родителе повтор
    # невозможен, поэтому срабатывание этой защиты означает цикл в базе — и тогда она
    # спасает от бесконечного обхода, а не просто дедуплицирует.
    visited = {issue.id}
    level = [root]
    budget = MAX_TREE_NODES

    for _ in range(levels):
        if not level:
            break
        children_by_parent = _group_by_parent(await repository.children(_ids(level)))
        next_level: list[_TreeDraft] = []
        for draft in level:
            for link in children_by_parent.get(draft.issue.id, ()):
                if budget == 0 or link.source_id in visited:
                    draft.has_more_children = True
                    continue
                visited.add(link.source_id)
                budget -= 1
                child = _TreeDraft(issue=link.source)
                draft.children.append(child)
                next_level.append(child)
        level = next_level

    # Последний уровень ещё не знает, есть ли под ним что-то: детей у него не
    # запрашивали. Один дополнительный запрос — цена честного `has_more_children`.
    if level:
        deeper = {link.target_id for link in await repository.children(_ids(level))}
        for draft in level:
            draft.has_more_children = draft.issue.id in deeper

    return root.freeze()


# --- Изменение -------------------------------------------------------------------


async def create_link(
    session: AsyncSession,
    *,
    initiator: Actor,
    source: Issue,
    link_type: LinkType,
    target: Issue,
) -> IssueLink:
    """Связывает две задачи. `link_type` читается как «`source` <тип> `target`».

    Направление приводится к каноническому до всех проверок: иначе «A blocks B» и
    «B depends_on A» проверялись бы как две разные связи и легли бы двумя строками.

    Порядок проверок выбран так, чтобы клиент получал самую точную причину. Дубликат
    идёт раньше правил иерархии: если ровно такая связь уже есть, «у задачи уже есть
    родитель» было бы формально верным, но сбивающим с толку ответом.
    """
    ensure_allowed(initiator, "link.create", target=source)
    if source.id == target.id:
        raise SelfLinkError(details={"issue": source.key, "type": link_type.value})

    form = canonical_form(link_type, source_key=source.key, target_key=target.key)
    stored_source, stored_target = (target, source) if form.swapped else (source, target)

    repository = IssueLinkRepository(session)
    existing = await repository.find(
        source_id=stored_source.id,
        target_id=stored_target.id,
        link_type=form.link_type,
    )
    if existing is not None:
        raise IssueLinkExistsError(
            details={
                "link": str(existing.id),
                "source": stored_source.key,
                "target": stored_target.key,
                "type": form.link_type.value,
            },
        )

    if is_hierarchy(link_type):
        await _ensure_hierarchy_allowed(repository, child=stored_source, parent=stored_target)

    link = IssueLink(
        source=stored_source,
        target=stored_target,
        link_type=form.link_type,
        author=initiator,
    )
    await repository.add(link)
    # Журнал обеих задач и событие — в той же транзакции, что и сама связь: откат
    # уносит всё разом, и подписчик не узнает о связи, которой не появилось.
    await events_service.record_link_created(session, link, initiator=initiator)
    return link


async def delete_link(session: AsyncSession, link: IssueLink, *, initiator: Actor) -> None:
    """Удаляет связь. Обе задачи получают запись в историю, шина — одно событие."""
    ensure_allowed(initiator, "link.delete", target=link)
    # Запись собирается **до** удаления: после него обе стороны уже не прочитать.
    await events_service.record_link_deleted(session, link, initiator=initiator)
    await IssueLinkRepository(session).delete(link)


async def ensure_issue_type_allows_parent(
    session: AsyncSession,
    issue: Issue,
    issue_type: IssueType,
) -> None:
    """Запрещает сделать эпиком задачу, у которой уже есть родитель.

    Вторая половина правила «у эпика нет родителя». Без неё запрет обходится с чёрного
    хода: сначала задача становится подзадачей, потом её тип меняют на «эпик», и
    инвариант нарушен, хотя ни одна связь не создавалась. Зовётся из единой точки
    изменения задачи (`app/services/issues.py`).
    """
    if not is_epic_type(issue_type):
        return
    parent = await IssueLinkRepository(session).parent_link(issue.id)
    if parent is not None:
        raise EpicParentError(
            details={
                "issue": issue.key,
                "parent": parent.target.key,
                "reason": "issue_has_parent",
                "hint": "remove the parent link first",
            },
        )


def is_epic_type(issue_type: IssueType) -> bool:
    """Эпик ли это тип задачи.

    Сравнивается ключ, а не ссылка: локальный тип очереди `TRK.epic` — тоже эпик.
    Иначе очередь, заведшая свой набор типов, молча осталась бы без правила.
    """
    return issue_type.key == EPIC_ISSUE_TYPE_KEY


# --- Внутреннее ------------------------------------------------------------------


async def _ensure_hierarchy_allowed(
    repository: IssueLinkRepository,
    *,
    child: Issue,
    parent: Issue,
) -> None:
    """Три правила иерархии подряд: эпик, единственный родитель, отсутствие цикла."""
    if is_epic_type(child.issue_type):
        raise EpicParentError(
            details={
                "issue": child.key,
                "issue_type": child.issue_type.ref,
                "reason": "epic_cannot_be_a_child",
            },
        )

    current = await repository.parent_link(child.id)
    if current is not None:
        raise IssueParentExistsError(
            details={
                "issue": child.key,
                "parent": current.target.key,
                "hint": "remove the existing parent link first",
            },
        )

    # Кольцо замкнётся ровно тогда, когда будущий родитель уже находится под будущим
    # ребёнком. Подъём начинается с родителя и включает его самого — случай «A родитель
    # A» отсечён раньше запретом связи с самой собой, но проверка от этого не зависит.
    if await repository.has_ancestor(issue_id=parent.id, ancestor_id=child.id):
        raise LinkCycleError(
            details={"child": child.key, "parent": parent.key, "reason": "hierarchy_cycle"},
        )


def _ids(level: list[_TreeDraft]) -> list[uuid.UUID]:
    return [draft.issue.id for draft in level]


def _group_by_parent(links: list[IssueLink]) -> dict[uuid.UUID, list[IssueLink]]:
    grouped: dict[uuid.UUID, list[IssueLink]] = {}
    for link in links:
        grouped.setdefault(link.target_id, []).append(link)
    return grouped
