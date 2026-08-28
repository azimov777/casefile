"""Сценарии поиска: разрешение имён, фильтрация по каждому типу поля, устойчивая пагинация.

Главное, что здесь проверяется, — обещание задачи: структурный фильтр и строка запроса
дают **идентичный** результат. Ради этого оба входа сводятся к одному внутреннему
представлению, и тест сравнивает выдачи двух форм одного и того же вопроса.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.actors import ActorType
from app.domain.errors import (
    SearchFieldUnknownError,
    SearchOperatorNotSupportedError,
    SearchValueInvalidError,
)
from app.domain.fields import FieldOption, FieldValueType
from app.services import actors as actors_service
from app.services import comments as comments_service
from app.services import fields as fields_service
from app.services import queues as queues_service
from app.services import search as search_service
from app.services.search import StructuredTerm

IssueFactory = Callable[..., Awaitable[Issue]]


async def _keys(
    session: AsyncSession,
    owner: Actor,
    query: str | None = None,
    **kwargs: object,
) -> list[str]:
    outcome = await search_service.search_issues(session, initiator=owner, query=query, **kwargs)
    return sorted(issue.key for issue in outcome.page.items)


async def _entry(session: AsyncSession, owner: Actor, kind: str, ref: str) -> object:
    from app.domain.catalogs import CatalogKind

    return await queues_service.resolve_catalog_ref(
        session, CatalogKind(kind), ref, initiator=owner
    )


# --- Системные поля ----------------------------------------------------------------


async def test_a_query_and_a_structured_filter_give_the_same_result(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Обещание задачи: два входа — одно внутреннее представление — одна выдача."""
    await make_issue(summary="Первая", tags=["release"])
    await make_issue(summary="Вторая", tags=["backend"])

    by_query = await _keys(db_session, owner, "queue: TRK and tags: release")
    by_filter = await _keys(
        db_session,
        owner,
        structured=[
            StructuredTerm(name="queue", values=["TRK"]),
            StructuredTerm(name="tags", values=["release"]),
        ],
    )

    assert by_query == by_filter
    assert len(by_query) == 1


async def test_an_empty_filter_returns_every_issue(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Поиск без условий — это перечисление, а не отказ."""
    await make_issue(summary="Первая")
    await make_issue(summary="Вторая")

    assert len(await _keys(db_session, owner)) == 2


async def test_status_category_filters_by_the_machine_meaning(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Доски и отчёты опираются на категорию, а не на название статуса."""
    done = await make_issue(
        summary="Готова",
        status=await _entry(db_session, owner, "status", "closed"),
        resolution=await _entry(db_session, owner, "resolution", "done"),
    )
    await make_issue(summary="Открыта")

    assert await _keys(db_session, owner, "status_category: done") == [done.key]
    assert await _keys(db_session, owner, "status_category: != done") != [done.key]


async def test_me_resolves_to_the_actor_who_asks(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """`me()` вычисляется при выполнении: один фильтр «мои» работает у всех."""
    other, _ = await actors_service.ensure_actor(
        db_session, actor_type=ActorType.HUMAN, key="other", display_name="Другой"
    )
    mine = await make_issue(summary="Моя", assignee=owner)
    await make_issue(summary="Чужая", assignee=other)

    assert await _keys(db_session, owner, "assignee: me()") == [mine.key]
    assert await _keys(db_session, other, "assignee: me()") != [mine.key]


async def test_empty_finds_issues_without_a_value(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    unassigned = await make_issue(summary="Ничья")
    await make_issue(summary="Моя", assignee=owner)

    assert await _keys(db_session, owner, "assignee: empty()") == [unassigned.key]
    assert await _keys(db_session, owner, "assignee: != empty()") != [unassigned.key]


async def test_negation_includes_issues_without_a_value(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """«Все, кроме Алисы» обязано находить и неназначенные задачи.

    В SQL сравнение с NULL даёт NULL, и наивное `assignee_id <> :alice` молча
    выбросило бы из выдачи половину — заметить это можно было бы только пересчитав.
    """
    unassigned = await make_issue(summary="Ничья")
    mine = await make_issue(summary="Моя", assignee=owner)

    found = await _keys(db_session, owner, "assignee: != owner")

    assert unassigned.key in found
    assert mine.key not in found


async def test_priority_compares_by_severity_not_by_alphabet(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """В алфавите `blocker` меньше `minor`; по смыслу — наоборот."""
    from app.domain.issues import IssuePriority

    blocker = await make_issue(summary="Горит", priority=IssuePriority.BLOCKER)
    await make_issue(summary="Мелочь", priority=IssuePriority.MINOR)

    assert await _keys(db_session, owner, "priority: >= major") == [blocker.key]


async def test_a_bare_date_covers_the_whole_day(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """`deadline: <= today()` обязано находить просроченное сегодня, а не только вчера.

    Подстановка полуночи вместо интервала суток дала бы ровно эту потерю — молча.
    """
    today_evening = datetime.now(UTC).replace(hour=23, minute=0, second=0, microsecond=0)
    due_today = await make_issue(summary="Сегодня", deadline=today_evening)
    await make_issue(summary="Через неделю", deadline=today_evening + timedelta(days=7))

    assert due_today.key in await _keys(db_session, owner, "deadline: <= today()")
    assert due_today.key not in await _keys(db_session, owner, "deadline: > today()")
    assert due_today.key in await _keys(db_session, owner, "deadline: today()")


async def test_full_text_search_covers_summary_description_and_comments(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    by_summary = await make_issue(summary="Починить выдачу ключей")
    by_description = await make_issue(summary="Вторая", description="Ключи сгорают на откате")
    by_comment = await make_issue(summary="Третья")
    await comments_service.add_comment(
        db_session, by_comment, initiator=owner, body="Проблема в выдаче ключей"
    )
    await make_issue(summary="Посторонняя")

    found = await _keys(db_session, owner, 'text: "ключ"')

    assert found == sorted([by_summary.key, by_description.key, by_comment.key])


async def test_a_deleted_comment_is_not_findable(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Текст удалённого комментария затёрт, поэтому отдельного условия не нужно."""
    issue = await make_issue(summary="Задача")
    comment = await comments_service.add_comment(
        db_session, issue, initiator=owner, body="Секретное слово абракадабра"
    )
    await comments_service.delete_comment(db_session, comment, issue=issue, initiator=owner)

    assert await _keys(db_session, owner, 'text: "абракадабра"') == []


async def test_tags_are_matched_exactly(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Канонические написания берутся из словаря тегов — он и есть их источник."""
    tagged = await make_issue(summary="Первая", tags=["Release"])

    assert await _keys(db_session, owner, "tags: Release") == [tagged.key]
    assert await _keys(db_session, owner, "tags: release") == []
    assert await _keys(db_session, owner, "tags: ~ lea") == [tagged.key]


async def test_followers_are_matched_by_membership(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    watched = await make_issue(summary="Под наблюдением", followers=[owner])
    await make_issue(summary="Без наблюдателей")

    assert await _keys(db_session, owner, "followers: me()") == [watched.key]
    assert await _keys(db_session, owner, "followers: empty()") != [watched.key]


# --- Кастомные поля ----------------------------------------------------------------


@pytest.fixture
async def severity(db_session: AsyncSession, owner: Actor, queue: Queue) -> object:
    """Локальное перечисление очереди: адресуется с префиксом `TRK.severity`."""
    return await fields_service.create_field(
        db_session,
        initiator=owner,
        key="severity",
        name="Критичность",
        value_type=FieldValueType.ENUM,
        queue=queue,
        options=[
            FieldOption(key="minor", name="Незначительная"),
            FieldOption(key="critical", name="Критическая"),
        ],
    )


async def test_a_local_field_is_addressed_with_the_queue_prefix(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
    severity: object,
) -> None:
    critical = await make_issue(summary="Критичная", values={"TRK.severity": "critical"})
    await make_issue(summary="Мелкая", values={"TRK.severity": "minor"})

    assert await _keys(db_session, owner, "TRK.severity: critical") == [critical.key]
    assert await _keys(db_session, owner, "trk.SEVERITY: critical") == [critical.key]


async def test_a_number_field_compares_as_a_number(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Лексикографически `9` больше `10`; по смыслу — наоборот."""
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="estimate",
        name="Оценка",
        value_type=FieldValueType.NUMBER,
        queue=queue,
    )
    big = await make_issue(summary="Большая", values={"TRK.estimate": 10})
    await make_issue(summary="Маленькая", values={"TRK.estimate": 9})

    assert await _keys(db_session, owner, "TRK.estimate: > 9.5") == [big.key]


async def test_a_date_field_compares_chronologically(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """Формат хранения подобран так, что лексикографический порядок совпадает с хронологическим."""
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="released_on",
        name="Дата релиза",
        value_type=FieldValueType.DATE,
        queue=queue,
    )
    early = await make_issue(summary="Ранняя", values={"TRK.released_on": "2026-01-09"})
    await make_issue(summary="Поздняя", values={"TRK.released_on": "2026-01-10"})

    assert await _keys(db_session, owner, "TRK.released_on: < 2026-01-10") == [early.key]


async def test_a_multi_valued_field_matches_any_of_its_values(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    make_issue: IssueFactory,
) -> None:
    """У множественного поля значение лежит элементом массива, у одиночного — скаляром.

    Одного выражения на оба случая не хватает, и без разделения половина задач молча
    не находилась бы.
    """
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="components",
        name="Компоненты",
        value_type=FieldValueType.STRING,
        queue=queue,
        is_multiple=True,
    )
    issue = await make_issue(summary="Сборная", values={"TRK.components": ["api", "db"]})
    await make_issue(summary="Другая", values={"TRK.components": ["ui"]})

    assert await _keys(db_session, owner, "TRK.components: db") == [issue.key]
    assert await _keys(db_session, owner, "TRK.components: ~ AP") == [issue.key]


async def test_a_filter_value_is_checked_by_the_same_validator_as_a_stored_one(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
    severity: object,
) -> None:
    """Иначе фильтр понимал бы значение по-своему и молча не находил ничего."""
    with pytest.raises(SearchValueInvalidError) as error:
        await _keys(db_session, owner, "TRK.severity: unknown_option")

    assert error.value.details["reason"] == "not_allowed"


# --- Отказы ------------------------------------------------------------------------


async def test_a_reserved_name_without_a_filter_is_refused_not_searched_in_jsonb(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    """`project` появится в задаче 10; молчаливый уход в JSONB дал бы пустую выдачу."""
    with pytest.raises(SearchFieldUnknownError) as error:
        await _keys(db_session, owner, "project: alpha")

    assert error.value.details["reason"] == "not_searchable"


async def test_an_unknown_field_names_itself(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    with pytest.raises(SearchFieldUnknownError) as error:
        await _keys(db_session, owner, "nosuchfield: 1")

    assert error.value.details["field"] == "nosuchfield"


async def test_an_inapplicable_operator_lists_the_allowed_ones(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    """Агент исправляет запрос по `details`, поэтому там лежит список, а не «нельзя»."""
    with pytest.raises(SearchOperatorNotSupportedError) as error:
        await _keys(db_session, owner, "queue: > TRK")

    assert "=" in error.value.details["allowed"]


async def test_a_moment_without_a_timezone_is_refused(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    """То же правило, что у дедлайна: зону за клиента не домысливают."""
    with pytest.raises(SearchValueInvalidError) as error:
        await _keys(db_session, owner, 'deadline: >= "2026-08-28T10:00:00"')

    assert error.value.details["reason"] == "timezone_required"


async def test_an_unknown_queue_in_a_filter_is_a_bad_value_not_a_missing_object(
    db_session: AsyncSession,
    owner: Actor,
    queue: Queue,
) -> None:
    """`404` на поиске сбивал бы с толку: не нашлась не задача, а значение фильтра."""
    with pytest.raises(SearchValueInvalidError) as error:
        await _keys(db_session, owner, "queue: NOPE")

    assert error.value.details["reason"] == "queue_not_found"
