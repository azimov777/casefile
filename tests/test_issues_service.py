"""Сценарии по задачам: создание, единая точка изменений, версии, наблюдатели.

Главное здесь — не то, что задача создаётся, а поведение единой точки применения
изменений: она возвращает список фактических изменений, не трогает непереданные поля,
очищает поле переданным `null` и отказывается писать поверх чужой версии. К этой же
точке в задаче 06 подключатся журнал и события, поэтому её поведение зафиксировано
тестами уже сейчас.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.domain.actors import ActorType
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.errors import (
    ActorInactiveError,
    CatalogEntryUnavailableError,
    FieldValuesInvalidError,
    InvalidIssueDeadlineError,
    InvalidIssueKeyError,
    InvalidIssueSummaryError,
    IssueNotFoundError,
    IssueReferencedError,
    IssueVersionConflictError,
    QueueArchivedError,
)
from app.domain.fields import FieldOption, FieldValueType
from app.domain.issues import IssueField, IssuePriority
from app.services import actors as actors_service
from app.services import catalogs as catalogs_service
from app.services import fields as fields_service
from app.services import issues as service
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _entry(session: AsyncSession, owner: Actor, kind: CatalogKind, ref: str) -> object:
    return await queues_service.resolve_catalog_ref(session, kind, ref, initiator=owner)


# --- Создание --------------------------------------------------------------------


async def test_new_issue_gets_a_key_and_the_queue_defaults(
    make_issue: MakeIssue, owner: Actor
) -> None:
    """Первая задача очереди получает первый номер, тип и статус — из настроек очереди."""
    issue = await make_issue()

    assert issue.key == "TRK-1"
    assert issue.issue_type.key == "task"
    assert issue.status.key == "open"
    assert issue.resolution is None
    assert issue.priority is IssuePriority.NORMAL
    assert issue.author.key == owner.key
    assert issue.version == 1


async def test_numbers_are_handed_out_in_order(make_issue: MakeIssue) -> None:
    first = await make_issue()
    second = await make_issue()

    assert (first.key, second.key) == ("TRK-1", "TRK-2")


async def test_author_defaults_to_the_initiator_not_to_the_queue_owner(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """У задачи, заведённой агентом, автор — агент: иначе история врёт с первого дня."""
    agent, _ = await actors_service.ensure_actor(
        db_session, actor_type=ActorType.AGENT, key="release_bot", display_name="Бот"
    )

    issue = await make_issue(initiator=agent)

    assert issue.author.key == "release_bot"
    assert owner.key != "release_bot"


async def test_archived_queue_accepts_no_new_issues(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    await queues_service.archive_queue(db_session, queue, initiator=owner)

    with pytest.raises(QueueArchivedError):
        await make_issue()


async def test_issue_type_must_be_allowed_in_the_queue(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    queue: Queue,
) -> None:
    """Иначе задача получила бы тип, которого нет ни в конфигурации, ни в форме создания."""
    incident = await catalogs_service.create_entry(
        db_session, CatalogKind.ISSUE_TYPE, initiator=owner, key="incident", name="Инцидент"
    )

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await make_issue(issue_type=incident)

    assert error.value.details["reason"] == "not_allowed_in_queue"


async def test_local_status_of_another_queue_is_rejected(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    other = await queues_service.create_queue(
        db_session, initiator=owner, key="OPS", name="Эксплуатация"
    )
    foreign = await catalogs_service.create_entry(
        db_session,
        CatalogKind.STATUS,
        initiator=owner,
        key="waiting",
        name="Ожидание",
        queue=other,
        category=StatusCategory.NEW,
    )

    with pytest.raises(CatalogEntryUnavailableError) as error:
        await make_issue(status=foreign)

    assert error.value.details["reason"] == "belongs_to_another_queue"


async def test_a_failed_creation_does_not_burn_a_number(
    make_issue: MakeIssue, queue: Queue
) -> None:
    """Проверки идут до выдачи номера: иначе неудачный запрос оставлял бы дыру в ключах."""
    with pytest.raises(InvalidIssueSummaryError):
        await make_issue(summary="   ")

    assert queue.last_issue_number == 0
    assert (await make_issue()).key == "TRK-1"


async def test_deadline_without_timezone_is_rejected(make_issue: MakeIssue) -> None:
    with pytest.raises(InvalidIssueDeadlineError):
        await make_issue(deadline=datetime(2026, 9, 1, 12, 0))


async def test_inactive_actor_cannot_be_assigned(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Уже записанные ссылки на отключённого актора живут дальше, новые — нет."""
    retired, _ = await actors_service.ensure_actor(
        db_session, actor_type=ActorType.AGENT, key="retired_bot", display_name="Старый бот"
    )
    await actors_service.update_actor(db_session, retired, initiator=owner, is_active=False)

    with pytest.raises(ActorInactiveError) as error:
        await make_issue(assignee=retired)

    assert error.value.details["reason"] == "cannot_be_assignee"


# --- Чтение ----------------------------------------------------------------------


async def test_issue_is_addressed_softly(db_session: AsyncSession, make_issue: MakeIssue) -> None:
    """`trk-1` находит ту же задачу, что и `TRK-1`: адресация в проекте мягкая."""
    issue = await make_issue()

    assert (await service.get_issue_by_key(db_session, "trk-1")).id == issue.id


async def test_unknown_key_is_not_found(db_session: AsyncSession, queue: Queue) -> None:
    with pytest.raises(IssueNotFoundError):
        await service.get_issue_by_key(db_session, "TRK-404")


async def test_malformed_key_is_rejected_with_the_expected_format(
    db_session: AsyncSession,
) -> None:
    """`invalid_issue_key` объясняет формат; шаблон в пути такого объяснить не может."""
    with pytest.raises(InvalidIssueKeyError) as error:
        await service.get_issue_by_key(db_session, "TRK-007")

    assert error.value.details["reason"] == "pattern_mismatch"


async def test_listing_is_narrowed_to_the_queue(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    await make_issue()
    other = await queues_service.create_queue(
        db_session, initiator=owner, key="OPS", name="Эксплуатация"
    )
    await service.create_issue(db_session, initiator=owner, queue=other, summary="Чужая задача")

    page = await service.list_issues(db_session, initiator=owner, queue=other)

    assert [issue.key for issue in page.items] == ["OPS-1"]


# --- Частичное обновление --------------------------------------------------------


async def test_update_touches_only_the_given_fields(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue(description="Исходное описание", tags=["release"])

    mutation = await service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=service.IssueChanges(summary="Новое название"),
    )

    assert issue.summary == "Новое название"
    assert issue.description == "Исходное описание"
    assert issue.tags == ["release"]
    assert [change.field for change in mutation.changes] == [IssueField.SUMMARY.value]


async def test_change_carries_the_previous_and_the_new_value(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Из этих записей задача 06 соберёт журнал и полезную нагрузку события."""
    issue = await make_issue()
    closed = await _entry(db_session, owner, CatalogKind.STATUS, "closed")

    mutation = await service.update_issue(
        db_session, issue, initiator=owner, changes=service.IssueChanges(status=closed)
    )

    (change,) = mutation.changes
    assert (change.field, change.before, change.after) == (
        IssueField.STATUS.value,
        "open",
        "closed",
    )


async def test_null_clears_the_field_and_a_missing_key_does_not(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Ровно ради этой разницы в проекте заведён признак «не передано»."""
    deadline = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    issue = await make_issue(assignee=owner, deadline=deadline)

    await service.update_issue(
        db_session, issue, initiator=owner, changes=service.IssueChanges(assignee=None)
    )

    assert issue.assignee is None
    assert issue.deadline == deadline


async def test_setting_the_same_value_changes_nothing(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Иначе журнал заполнился бы пустыми строками, а автоматика срабатывала бы впустую."""
    issue = await make_issue(summary="Название")

    mutation = await service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=service.IssueChanges(summary="Название", priority=IssuePriority.NORMAL),
    )

    assert mutation.changes == ()
    assert not mutation.changed
    assert issue.version == 1


async def test_actual_change_raises_the_version(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    await service.update_issue(
        db_session, issue, initiator=owner, changes=service.IssueChanges(summary="Другое")
    )

    assert issue.version == 2


async def test_stale_version_is_a_conflict(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Молчаливая перезапись хуже отказа: потерянное изменение находят спустя дни."""
    issue = await make_issue()
    await service.update_issue(
        db_session, issue, initiator=owner, changes=service.IssueChanges(summary="Первое")
    )

    with pytest.raises(IssueVersionConflictError) as error:
        await service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=service.IssueChanges(summary="Второе"),
            expected_version=1,
        )

    assert error.value.details == {
        "key": "TRK-1",
        "expected": 1,
        "actual": 2,
        "hint": "re-read the issue and retry",
    }
    assert issue.summary == "Первое"


async def test_matching_version_passes(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    await service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=service.IssueChanges(summary="Другое"),
        expected_version=1,
    )

    assert issue.summary == "Другое"


async def test_tags_are_replaced_as_a_whole_set(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue(tags=["release"])

    mutation = await service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=service.IssueChanges(tags=["backend", "Backend", "release"]),
    )

    assert issue.tags == ["backend", "release"]
    (change,) = mutation.changes
    assert (change.before, change.after) == (["release"], ["backend", "release"])


# --- Исполнитель и наблюдатели ---------------------------------------------------


async def test_assigning_records_the_actor_key(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    mutation = await service.assign_issue(db_session, issue, initiator=owner, assignee=owner)

    (change,) = mutation.changes
    assert (change.field, change.before, change.after) == (
        IssueField.ASSIGNEE.value,
        None,
        owner.key,
    )


async def test_followers_are_added_and_removed(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    watcher, _ = await actors_service.ensure_actor(
        db_session, actor_type=ActorType.AGENT, key="release_bot", display_name="Бот"
    )

    await service.add_follower(db_session, issue, initiator=owner, actor=watcher)
    assert [follower.key for follower in issue.followers] == ["release_bot"]

    await service.remove_follower(db_session, issue, initiator=owner, actor=watcher)
    assert issue.followers == []


async def test_following_twice_changes_nothing(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Идемпотентно по той же причине, что отзыв токена: повтор запроса — не ошибка."""
    issue = await make_issue()
    await service.add_follower(db_session, issue, initiator=owner, actor=owner)
    version_after_first = issue.version

    mutation = await service.add_follower(db_session, issue, initiator=owner, actor=owner)

    assert mutation.changes == ()
    assert issue.version == version_after_first


async def test_unfollowing_a_stranger_changes_nothing(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    mutation = await service.remove_follower(db_session, issue, initiator=owner, actor=owner)

    assert mutation.changes == ()


# --- Кастомные поля --------------------------------------------------------------


async def _severity(session: AsyncSession, owner: Actor, *, is_required: bool = False) -> object:
    return await fields_service.create_field(
        session,
        initiator=owner,
        key="severity",
        name="Серьёзность",
        value_type=FieldValueType.ENUM,
        is_required=is_required,
        options=[
            FieldOption(key="minor", name="Мелкая"),
            FieldOption(key="critical", name="Критическая"),
        ],
    )


async def test_values_are_stored_in_the_registry_form(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """В `values` ложится результат валидатора, а не присланный словарь."""
    await _severity(db_session, owner)

    issue = await make_issue(values={"SEVERITY": " critical "})

    assert issue.values == {"severity": "critical"}


async def test_required_field_is_checked_at_creation(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    await _severity(db_session, owner, is_required=True)

    with pytest.raises(FieldValuesInvalidError) as error:
        await make_issue()

    assert error.value.details["fields"][0]["reason"] == "required"


async def test_unknown_value_is_rejected(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    await _severity(db_session, owner)

    with pytest.raises(FieldValuesInvalidError) as error:
        await make_issue(values={"severity": "catastrophic"})

    assert error.value.details["fields"][0]["reason"] == "not_allowed"


async def test_partial_values_update_clears_by_null_and_keeps_the_rest(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Правило `null` снимает, отсутствующий ключ не трогает — общее с реестром полей."""
    await _severity(db_session, owner)
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="reported_by",
        name="Кто сообщил",
        value_type=FieldValueType.STRING,
    )
    issue = await make_issue(values={"severity": "minor", "reported_by": "поддержка"})

    mutation = await service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=service.IssueChanges(values={"severity": None}),
    )

    assert issue.values == {"reported_by": "поддержка"}
    (change,) = mutation.changes
    assert (change.field, change.before, change.after) == ("severity", "minor", None)


async def test_partial_values_update_cannot_drop_a_required_field(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Валидатор проверяет полный набор, поэтому склейка идёт до проверки, а не после."""
    await _severity(db_session, owner, is_required=True)
    issue = await make_issue(values={"severity": "minor"})

    with pytest.raises(FieldValuesInvalidError):
        await service.update_issue(
            db_session,
            issue,
            initiator=owner,
            changes=service.IssueChanges(values={"severity": None}),
        )


async def test_changing_the_issue_type_rechecks_the_values(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """У нового типа другой набор применимых полей: молча оставить старые нельзя."""
    bug = await _entry(db_session, owner, CatalogKind.ISSUE_TYPE, "bug")
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="steps",
        name="Шаги воспроизведения",
        value_type=FieldValueType.TEXT,
        is_required=True,
        issue_types=[bug],
    )
    issue = await make_issue()

    with pytest.raises(FieldValuesInvalidError) as error:
        await service.update_issue(
            db_session, issue, initiator=owner, changes=service.IssueChanges(issue_type=bug)
        )

    assert error.value.details["fields"][0]["field"] == "steps"


async def test_issue_reference_field_sees_existing_issues(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Заглушка, разрешавшая ссылку на несуществующую задачу, заменена запросом."""
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="caused_by",
        name="Вызвано задачей",
        value_type=FieldValueType.ISSUE,
    )
    existing = await make_issue()

    linked = await make_issue(values={"caused_by": existing.key})
    assert linked.values == {"caused_by": existing.key}

    with pytest.raises(FieldValuesInvalidError) as error:
        await make_issue(values={"caused_by": "TRK-999"})

    assert error.value.details["fields"][0]["reason"] == "issue_not_found"


# --- Удаление --------------------------------------------------------------------


async def test_referenced_issue_is_not_deleted(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Иначе в чужом поле остался бы ключ, за которым ничего нет.

    Записать такую ссылку валидатор не даёт, и получать это состояние удалением было бы
    странно вдвойне: дыра выглядела бы как опечатка в данных.
    """
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="caused_by",
        name="Вызвано задачей",
        value_type=FieldValueType.ISSUE,
    )
    target = await make_issue()
    await make_issue(values={"caused_by": target.key})

    with pytest.raises(IssueReferencedError) as error:
        await service.delete_issue(db_session, target, initiator=owner)

    assert error.value.details["issues"] == ["TRK-2"]


async def test_self_reference_does_not_block_deletion(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Поле, ссылающееся на собственную задачу, исчезает вместе с ней."""
    await fields_service.create_field(
        db_session,
        initiator=owner,
        key="caused_by",
        name="Вызвано задачей",
        value_type=FieldValueType.ISSUE,
    )
    issue = await make_issue()
    await service.update_issue(
        db_session,
        issue,
        initiator=owner,
        changes=service.IssueChanges(values={"caused_by": issue.key}),
    )

    await service.delete_issue(db_session, issue, initiator=owner)

    with pytest.raises(IssueNotFoundError):
        await service.get_issue_by_key(db_session, issue.key)


async def test_deleted_issue_does_not_release_its_key(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Иначе ссылка `TRK-1` в переписке однажды указала бы на чужую задачу."""
    issue = await make_issue()

    await service.delete_issue(db_session, issue, initiator=owner)

    with pytest.raises(IssueNotFoundError):
        await service.get_issue_by_key(db_session, "TRK-1")
    assert (await make_issue()).key == "TRK-2"


async def test_deadline_change_is_recorded_as_an_iso_string(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Событие переживает транзакцию, поэтому в записи изменения — строка, а не объект."""
    issue = await make_issue()
    deadline = datetime.now(UTC).replace(microsecond=0) + timedelta(days=7)

    mutation = await service.update_issue(
        db_session, issue, initiator=owner, changes=service.IssueChanges(deadline=deadline)
    )

    (change,) = mutation.changes
    assert change.before is None
    assert change.after == deadline.astimezone(UTC).isoformat()
