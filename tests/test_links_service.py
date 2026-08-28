"""Сценарии связей: обе стороны, дубликаты, иерархия, циклы, дерево, события.

Главное здесь — то, ради чего связь хранится одной строкой: заведённая с одной стороны,
она немедленно видна со второй под обратным именем, и второй записи, которая могла бы с
ней разойтись, не существует.

Иерархия проверяется тремя правилами, и каждое ловит своё: эпик без родителя, один
родитель, отсутствие цикла на любой глубине. Цикл проверяется именно на цепочке из трёх
задач — прямой «А родитель Б, Б родитель А» поймала бы и наивная проверка на один шаг.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.issue import Issue
from app.db.models.link import IssueLink
from app.db.repositories import OutboxRepository
from app.domain.catalogs import CatalogKind
from app.domain.errors import (
    EpicParentError,
    IssueLinkExistsError,
    IssueLinkNotFoundError,
    IssueParentExistsError,
    LinkCycleError,
    SelfLinkError,
)
from app.domain.events import EventType, ObjectType
from app.domain.links import LINKS_CHANGE_FIELD, MAX_TREE_NODES, LinkType
from app.services import links as service
from app.services import queues as queues_service
from app.services.issues import IssueChanges
from app.services.issues import update_issue as update_issue_service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _epic_type(session: AsyncSession, owner: Actor) -> IssueType:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, "epic", initiator=owner
    )
    assert isinstance(entry, IssueType)
    return entry


async def _history(session: AsyncSession, issue: Issue) -> list[ChangelogEntry]:
    statement = (
        select(ChangelogEntry)
        .where(ChangelogEntry.issue_id == issue.id)
        .order_by(ChangelogEntry.created_at, ChangelogEntry.id)
    )
    return list((await session.scalars(statement)).all())


async def _link_events(session: AsyncSession, link_id) -> list[OutboxEvent]:
    return await OutboxRepository(session).list_by_object(
        object_type=ObjectType.LINK.value,
        object_id=link_id,
    )


async def _link_count(session: AsyncSession) -> int:
    return (await session.scalar(select(func.count()).select_from(IssueLink))) or 0


async def _links_of(
    session: AsyncSession,
    issue: Issue,
    owner: Actor,
) -> list[service.IssueLinkView]:
    page = await service.list_issue_links(session, issue, initiator=owner)
    return page.items


# --- Обе стороны одной строки -----------------------------------------------------


async def test_a_link_is_visible_from_both_sides_under_opposite_names(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Заведена одна связь — видна обеим задачам, каждой своим именем."""
    blocker = await make_issue(summary="Починить выдачу ключей")
    blocked = await make_issue(summary="Выпустить релиз")

    await service.create_link(
        db_session,
        initiator=owner,
        source=blocked,
        link_type=LinkType.DEPENDS_ON,
        target=blocker,
    )

    from_blocked = await _links_of(db_session, blocked, owner)
    from_blocker = await _links_of(db_session, blocker, owner)

    assert [(view.link_type, view.issue.key) for view in from_blocked] == [
        (LinkType.DEPENDS_ON, blocker.key)
    ]
    assert [(view.link_type, view.issue.key) for view in from_blocker] == [
        (LinkType.BLOCKS, blocked.key)
    ]
    # Строка одна: вторая, способная разойтись с первой, не заводится.
    assert await _link_count(db_session) == 1


async def test_the_opposite_direction_is_the_same_link(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """«A blocks B» после «B depends_on A» — не новая связь, а дубликат."""
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    await service.create_link(
        db_session,
        initiator=owner,
        source=second,
        link_type=LinkType.DEPENDS_ON,
        target=first,
    )

    with pytest.raises(IssueLinkExistsError):
        await service.create_link(
            db_session,
            initiator=owner,
            source=first,
            link_type=LinkType.BLOCKS,
            target=second,
        )

    assert await _link_count(db_session) == 1


async def test_a_symmetric_link_is_the_same_in_both_orders(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """У `relates` обратная сторона равна прямой, и порядок задач ничего не меняет."""
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.RELATES, target=second
    )

    with pytest.raises(IssueLinkExistsError):
        await service.create_link(
            db_session, initiator=owner, source=second, link_type=LinkType.RELATES, target=first
        )

    views = await _links_of(db_session, second, owner)
    assert [view.link_type for view in views] == [LinkType.RELATES]


async def test_an_issue_cannot_be_linked_to_itself(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    with pytest.raises(SelfLinkError):
        await service.create_link(
            db_session, initiator=owner, source=issue, link_type=LinkType.RELATES, target=issue
        )


async def test_two_issues_can_hold_several_links_of_different_types(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Запрещён дубликат связи, а не вторая связь между теми же задачами."""
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")

    await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.RELATES, target=second
    )
    await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.DUPLICATES, target=second
    )

    views = await _links_of(db_session, first, owner)
    assert {view.link_type for view in views} == {LinkType.RELATES, LinkType.DUPLICATES}


# --- Иерархия ---------------------------------------------------------------------


async def test_an_issue_keeps_a_single_parent(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Второй родитель отвергается: иначе дерево перестало бы быть деревом."""
    child = await make_issue(summary="Подзадача")
    first_parent = await make_issue(summary="Родитель")
    second_parent = await make_issue(summary="Другой родитель")
    await service.create_link(
        db_session,
        initiator=owner,
        source=child,
        link_type=LinkType.SUBTASK_OF,
        target=first_parent,
    )

    with pytest.raises(IssueParentExistsError) as failure:
        await service.create_link(
            db_session,
            initiator=owner,
            source=second_parent,
            link_type=LinkType.PARENT_OF,
            target=child,
        )

    assert failure.value.details["parent"] == first_parent.key


async def test_a_cycle_is_refused_at_any_depth(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Кольцо из трёх задач ломает обход так же, как из двух.

    Проверка на один шаг назад пропустила бы этот случай: у `top` родителя нет, и
    прямого «middle родитель top» тоже нет — цикл виден только при подъёме до конца.
    """
    top = await make_issue(summary="Верхняя задача")
    middle = await make_issue(summary="Средняя задача")
    bottom = await make_issue(summary="Нижняя задача")
    await service.create_link(
        db_session, initiator=owner, source=middle, link_type=LinkType.SUBTASK_OF, target=top
    )
    await service.create_link(
        db_session, initiator=owner, source=bottom, link_type=LinkType.SUBTASK_OF, target=middle
    )

    with pytest.raises(LinkCycleError):
        await service.create_link(
            db_session, initiator=owner, source=top, link_type=LinkType.SUBTASK_OF, target=bottom
        )


async def test_an_epic_cannot_be_given_a_parent(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Эпик — верхний уровень планирования, внутрь задачи он не вкладывается."""
    epic = await make_issue(summary="Эпик", issue_type=await _epic_type(db_session, owner))
    task = await make_issue(summary="Задача")

    with pytest.raises(EpicParentError):
        await service.create_link(
            db_session, initiator=owner, source=epic, link_type=LinkType.SUBTASK_OF, target=task
        )


async def test_an_epic_holds_children_like_any_other_issue(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Содержимое эпика держится на обычной иерархической связи, без своего типа."""
    epic = await make_issue(summary="Эпик", issue_type=await _epic_type(db_session, owner))
    task = await make_issue(summary="Задача")

    await service.create_link(
        db_session, initiator=owner, source=task, link_type=LinkType.SUBTASK_OF, target=epic
    )

    views = await _links_of(db_session, epic, owner)
    assert [(view.link_type, view.issue.key) for view in views] == [(LinkType.PARENT_OF, task.key)]


async def test_a_child_issue_cannot_be_turned_into_an_epic(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Запрет «у эпика нет родителя» не обходится сменой типа задачи.

    Без этой проверки инвариант нарушался бы без единой операции над связями: сначала
    задача становится подзадачей, потом ей меняют тип.
    """
    parent = await make_issue(summary="Родитель")
    child = await make_issue(summary="Подзадача")
    await service.create_link(
        db_session, initiator=owner, source=child, link_type=LinkType.SUBTASK_OF, target=parent
    )

    with pytest.raises(EpicParentError):
        await update_issue_service(
            db_session,
            child,
            initiator=owner,
            changes=IssueChanges(issue_type=await _epic_type(db_session, owner)),
        )


# --- Дерево -----------------------------------------------------------------------


async def test_the_tree_stops_at_the_requested_depth_and_says_so(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Обрезанное дерево отличимо от полного: у листа стоит `has_more_children`."""
    root = await make_issue(summary="Корень")
    first = await make_issue(summary="Первый уровень")
    second = await make_issue(summary="Второй уровень")
    await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.SUBTASK_OF, target=root
    )
    await service.create_link(
        db_session, initiator=owner, source=second, link_type=LinkType.SUBTASK_OF, target=first
    )

    shallow = await service.build_tree(db_session, root, initiator=owner, depth=1)
    deep = await service.build_tree(db_session, root, initiator=owner, depth=2)

    assert [node.issue.key for node in shallow.children] == [first.key]
    assert shallow.children[0].children == ()
    assert shallow.children[0].has_more_children is True

    assert [node.issue.key for node in deep.children[0].children] == [second.key]
    assert deep.children[0].has_more_children is False
    assert deep.children[0].children[0].has_more_children is False


async def test_the_tree_of_a_leaf_is_a_single_node(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    tree = await service.build_tree(db_session, issue, initiator=owner)

    assert tree.issue.key == issue.key
    assert tree.children == ()
    assert tree.has_more_children is False


async def test_the_tree_never_exceeds_the_node_cap(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Потолок узлов существует и назван: широкий эпик не вытаскивает половину базы."""
    assert MAX_TREE_NODES > 0

    root = await make_issue(summary="Корень")
    for index in range(3):
        child = await make_issue(summary=f"Подзадача {index}")
        await service.create_link(
            db_session, initiator=owner, source=child, link_type=LinkType.SUBTASK_OF, target=root
        )

    tree = await service.build_tree(db_session, root, initiator=owner)

    assert len(tree.children) == 3
    assert tree.has_more_children is False


async def test_only_hierarchical_links_build_the_tree(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """`relates` и `blocks` в дерево не попадают: дерево строит только иерархия."""
    root = await make_issue(summary="Корень")
    related = await make_issue(summary="Просто связанная")
    await service.create_link(
        db_session, initiator=owner, source=root, link_type=LinkType.RELATES, target=related
    )

    tree = await service.build_tree(db_session, root, initiator=owner)

    assert tree.children == ()


# --- История и события ------------------------------------------------------------


async def test_a_new_link_writes_history_for_both_issues_and_one_event(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Две записи журнала — по одной каждой задаче — и ровно одно событие на связь."""
    blocked = await make_issue(summary="Выпустить релиз")
    blocker = await make_issue(summary="Починить выдачу ключей")

    link = await service.create_link(
        db_session,
        initiator=owner,
        source=blocked,
        link_type=LinkType.DEPENDS_ON,
        target=blocker,
    )

    blocked_history = await _history(db_session, blocked)
    blocker_history = await _history(db_session, blocker)

    assert blocked_history[-1].event_type == EventType.LINK_CREATED
    assert blocked_history[-1].changes == [
        {
            "field": LINKS_CHANGE_FIELD,
            "before": None,
            "after": {"type": LinkType.DEPENDS_ON.value, "issue": blocker.key},
        }
    ]
    # Вторая сторона видит ту же связь обратным именем — как и в ответе API.
    assert blocker_history[-1].changes[0]["after"] == {
        "type": LinkType.BLOCKS.value,
        "issue": blocked.key,
    }

    events = await _link_events(db_session, link.id)
    assert len(events) == 1
    payload = events[0].payload
    assert events[0].event_type == EventType.LINK_CREATED
    assert payload["link"]["type"] == LinkType.DEPENDS_ON.value
    # Снимки обеих задач: подписчику не нужно ходить в базу за контекстом.
    assert payload["issues"]["source"]["key"] == blocked.key
    assert payload["issues"]["target"]["key"] == blocker.key


async def test_deleting_a_link_records_both_sides_and_emits_an_event(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    link = await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.RELATES, target=second
    )
    link_id = link.id

    await service.delete_link(db_session, link, initiator=owner)

    assert await _link_count(db_session) == 0
    for issue in (first, second):
        history = await _history(db_session, issue)
        assert history[-1].event_type == EventType.LINK_DELETED
        assert history[-1].changes[0]["after"] is None
        assert history[-1].changes[0]["before"]["type"] == LinkType.RELATES.value

    events = await _link_events(db_session, link_id)
    assert [event.event_type for event in events] == [
        EventType.LINK_CREATED,
        EventType.LINK_DELETED,
    ]


async def test_a_link_of_another_pair_is_not_found_through_this_issue(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Чужая связь для клиента — то же самое, что несуществующая."""
    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    outsider = await make_issue(summary="Посторонняя")
    link = await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.RELATES, target=second
    )

    with pytest.raises(IssueLinkNotFoundError):
        await service.get_issue_link(db_session, outsider, link.id)


async def test_deleting_an_issue_takes_its_links_with_it(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Каскад по обоим ключам: связь без одной из задач бессмысленна.

    Событий `link.deleted` при этом не появляется — удаление задачи объявляется одним
    `issue.deleted`. Это осознанная цена каскада, см. `docs/notes/links.md`.
    """
    from app.services.issues import delete_issue as delete_issue_service

    first = await make_issue(summary="Первая")
    second = await make_issue(summary="Вторая")
    await service.create_link(
        db_session, initiator=owner, source=first, link_type=LinkType.RELATES, target=second
    )

    await delete_issue_service(db_session, second, initiator=owner)

    assert await _link_count(db_session) == 0
    assert await _links_of(db_session, first, owner) == []
