"""Сценарии по реестру полей: области действия, применимость, защита от разрушительных правок.

Проверка значений против базы (существование актора, скрытые и неприменимые поля) —
тоже здесь: домен её сделать не может, а без неё валидатор отвечал бы клиенту
«такого поля нет» там, где поле есть.

Задачи со значениями полей в этих тестах настоящие: счётчики из
`app/services/issue_usage.py` перестали быть заглушками в задаче 05, и подменять их
больше нечем — подмена скрыла бы расхождение между запросом и тем, что он должен считать.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind
from app.domain.errors import (
    CatalogEntryUnavailableError,
    FieldInUseError,
    FieldKeyTakenError,
    FieldNotFoundError,
    FieldTypeLockedError,
    FieldValuesInvalidError,
    InvalidFieldDefinitionError,
    InvalidFieldKeyError,
    IssueTypeInUseError,
)
from app.domain.fields import FieldOption, FieldValueType
from app.services import catalogs as catalogs_service
from app.services import fields as service
from app.services import queues as queues_service

MakeIssue = Callable[..., Awaitable[object]]


@pytest.fixture
def issues_with_value(make_issue: MakeIssue) -> Callable[..., Awaitable[None]]:
    """Заводит задачи, у которых заполнено указанное поле.

    Настоящие задачи, а не подменённый счётчик: запрет менять тип поля с данными
    обязан опираться на тот же запрос по `values JSONB`, которым пользуется рабочий код.
    """

    async def _create(count: int, ref: str = "severity", value: Any = "высокая") -> None:
        for _ in range(count):
            await make_issue(values={ref: value})

    return _create


async def issue_type(session: AsyncSession, owner: Actor, ref: str) -> IssueType:
    return await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, ref, initiator=owner
    )


async def make_field(
    session: AsyncSession,
    owner: Actor,
    *,
    key: str = "severity",
    value_type: FieldValueType = FieldValueType.STRING,
    **kwargs: object,
) -> object:
    return await service.create_field(
        session,
        initiator=owner,
        key=key,
        name="Серьёзность",
        value_type=value_type,
        **kwargs,
    )


# --- Области действия ------------------------------------------------------------


async def test_same_key_lives_in_the_global_and_in_the_local_scope(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Глобальное `severity` и локальное `TRK.severity` — два разных поля."""
    global_field = await make_field(db_session, owner)
    local_field = await make_field(db_session, owner, queue=queue)

    assert global_field.id != local_field.id
    assert service.field_ref(global_field) == "severity"
    assert service.field_ref(local_field) == "TRK.severity"


async def test_duplicate_key_in_the_same_scope_is_rejected(
    db_session: AsyncSession, owner: Actor
) -> None:
    await make_field(db_session, owner)

    with pytest.raises(FieldKeyTakenError):
        await make_field(db_session, owner)


async def test_local_field_is_not_visible_outside_its_queue(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(db_session, owner, queue=queue)

    other = await queues_service.create_queue(
        db_session, initiator=owner, key="OPS", name="Эксплуатация"
    )
    visible = await service.applicable_fields(db_session, queue=other)

    assert visible == []


async def test_field_is_resolved_by_its_reference(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(db_session, owner, queue=queue)

    found = await queues_service.resolve_field_ref(db_session, "trk.SEVERITY", initiator=owner)

    assert service.field_ref(found) == "TRK.severity"

    with pytest.raises(FieldNotFoundError):
        await queues_service.resolve_field_ref(db_session, "severity", initiator=owner)


async def test_system_field_key_is_rejected(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(InvalidFieldKeyError):
        await make_field(db_session, owner, key="assignee")


# --- Применимость к связке «очередь + тип задачи» --------------------------------


async def test_field_without_restrictions_applies_to_every_issue_type(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(db_session, owner, queue=queue)

    task = await issue_type(db_session, owner, "task")
    bug = await issue_type(db_session, owner, "bug")

    for entry in (task, bug):
        applicable = await service.applicable_fields(db_session, queue=queue, issue_type=entry)
        assert [service.field_ref(field) for field in applicable] == ["TRK.severity"]


async def test_restricted_field_applies_only_to_the_listed_issue_types(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    bug = await issue_type(db_session, owner, "bug")
    task = await issue_type(db_session, owner, "task")
    await make_field(db_session, owner, queue=queue, issue_types=[bug])

    assert await service.applicable_fields(db_session, queue=queue, issue_type=task) == []
    for_bug = await service.applicable_fields(db_session, queue=queue, issue_type=bug)
    assert [service.field_ref(field) for field in for_bug] == ["TRK.severity"]


async def test_queue_sees_global_fields_together_with_its_own(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Это и есть ответ на вопрос «какие поля есть у задачи в этой очереди»."""
    await make_field(db_session, owner, key="business_value", display_order=1)
    await make_field(db_session, owner, queue=queue, display_order=2)

    applicable = await service.applicable_fields(db_session, queue=queue)

    assert [service.field_ref(field) for field in applicable] == [
        "business_value",
        "TRK.severity",
    ]


async def test_applicable_fields_follow_the_display_order(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(db_session, owner, key="second", display_order=20)
    await make_field(db_session, owner, key="first", display_order=10)

    applicable = await service.applicable_fields(db_session, queue=queue)

    assert [field.key for field in applicable] == ["first", "second"]


async def test_hidden_field_leaves_the_queue_configuration(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    field = await make_field(db_session, owner, queue=queue)
    await service.update_field(db_session, field, initiator=owner, is_hidden=True)

    assert await service.applicable_fields(db_session, queue=queue) == []
    with_hidden = await service.applicable_fields(db_session, queue=queue, include_hidden=True)
    assert [service.field_ref(entry) for entry in with_hidden] == ["TRK.severity"]


async def test_global_field_cannot_be_restricted_to_a_local_issue_type(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Иначе глобальное поле работало бы ровно в одной очереди, и понять это было бы нельзя."""
    local_type = await catalogs_service.create_entry(
        db_session,
        CatalogKind.ISSUE_TYPE,
        initiator=owner,
        key="incident",
        name="Инцидент",
        queue=queue,
    )

    with pytest.raises(CatalogEntryUnavailableError) as info:
        await make_field(db_session, owner, issue_types=[local_type])

    assert info.value.details["reason"] == "global_field_needs_global_issue_types"


async def test_local_field_cannot_be_restricted_to_another_queue_issue_type(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    other = await queues_service.create_queue(
        db_session, initiator=owner, key="OPS", name="Эксплуатация"
    )
    foreign_type = await catalogs_service.create_entry(
        db_session,
        CatalogKind.ISSUE_TYPE,
        initiator=owner,
        key="incident",
        name="Инцидент",
        queue=other,
    )

    with pytest.raises(CatalogEntryUnavailableError):
        await make_field(db_session, owner, queue=queue, issue_types=[foreign_type])


async def test_issue_type_used_as_a_field_restriction_cannot_be_deleted(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Каскад стёр бы ограничение и молча расширил поле «только для багов» до всех типов."""
    bug = await issue_type(db_session, owner, "bug")
    await make_field(db_session, owner, issue_types=[bug])

    with pytest.raises(IssueTypeInUseError) as info:
        await catalogs_service.delete_entry(
            db_session, bug, CatalogKind.ISSUE_TYPE, initiator=owner
        )

    assert info.value.details["reason"] == "restricts_fields"


# --- Описание поля ---------------------------------------------------------------


async def test_enum_without_options_is_rejected(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(InvalidFieldDefinitionError) as info:
        await make_field(db_session, owner, value_type=FieldValueType.ENUM)

    assert info.value.details["reason"] == "enum_requires_options"


async def test_options_on_a_non_enum_field_are_not_swallowed(
    db_session: AsyncSession, owner: Actor
) -> None:
    """Проглотить их значило бы вернуть успех и уверенность, что список применён."""
    with pytest.raises(InvalidFieldDefinitionError) as info:
        await make_field(
            db_session,
            owner,
            value_type=FieldValueType.NUMBER,
            options=[FieldOption(key="minor", name="Мелкая")],
        )

    assert info.value.details["reason"] == "options_belong_to_enum_only"


async def test_duplicate_option_keys_are_rejected(db_session: AsyncSession, owner: Actor) -> None:
    with pytest.raises(InvalidFieldDefinitionError) as info:
        await make_field(
            db_session,
            owner,
            value_type=FieldValueType.ENUM,
            options=[
                FieldOption(key="minor", name="Мелкая"),
                FieldOption(key="minor", name="Небольшая"),
            ],
        )

    assert info.value.details["reason"] == "duplicate_option_key"


async def test_default_value_is_checked_by_the_same_validator_as_a_real_value(
    db_session: AsyncSession, owner: Actor
) -> None:
    """Иначе умолчание положило бы в задачу то, что сама задача принять не может."""
    with pytest.raises(InvalidFieldDefinitionError) as info:
        await make_field(db_session, owner, value_type=FieldValueType.NUMBER, default_value="пять")

    assert info.value.details["reason"] == "not_valid_for_this_type"


async def test_default_value_is_stored_in_the_canonical_shape(
    db_session: AsyncSession, owner: Actor
) -> None:
    field = await make_field(
        db_session,
        owner,
        key="release_date",
        value_type=FieldValueType.DATETIME,
        default_value="2026-08-27T13:00:00+03:00",
    )

    assert field.default_value == "2026-08-27T10:00:00+00:00"


# --- Изменение поля --------------------------------------------------------------


async def test_renaming_and_toggling_required_are_always_allowed(
    db_session: AsyncSession, owner: Actor, issues_with_value: Callable[..., Awaitable[None]]
) -> None:
    field = await make_field(db_session, owner)
    await issues_with_value(1)

    updated = await service.update_field(
        db_session, field, initiator=owner, name="Критичность", is_required=True
    )

    assert (updated.name, updated.is_required) == ("Критичность", True)


async def test_value_type_of_a_field_with_data_cannot_be_changed(
    db_session: AsyncSession, owner: Actor, issues_with_value: Callable[..., Awaitable[None]]
) -> None:
    field = await make_field(db_session, owner)
    await issues_with_value(3)

    with pytest.raises(FieldTypeLockedError) as info:
        await service.update_field(
            db_session, field, initiator=owner, value_type=FieldValueType.NUMBER
        )

    assert info.value.details["issues"] == 3


async def test_multiplicity_of_a_field_with_data_cannot_be_changed(
    db_session: AsyncSession, owner: Actor, issues_with_value: Callable[..., Awaitable[None]]
) -> None:
    """Множественность — часть формы записи в JSONB, а не косметика."""
    field = await make_field(db_session, owner)
    await issues_with_value(1)

    with pytest.raises(FieldTypeLockedError):
        await service.update_field(db_session, field, initiator=owner, is_multiple=True)


async def test_value_type_of_an_untouched_field_can_be_changed(
    db_session: AsyncSession, owner: Actor
) -> None:
    field = await make_field(db_session, owner)

    updated = await service.update_field(
        db_session, field, initiator=owner, value_type=FieldValueType.NUMBER
    )

    assert updated.value_type is FieldValueType.NUMBER


async def test_option_in_use_cannot_be_dropped_from_the_list(
    db_session: AsyncSession, owner: Actor, issues_with_value: Callable[..., Awaitable[None]]
) -> None:
    field = await make_field(
        db_session,
        owner,
        value_type=FieldValueType.ENUM,
        options=[FieldOption(key="minor", name="Мелкая"), FieldOption(key="major", name="Крупная")],
    )
    await issues_with_value(1, value="minor")

    with pytest.raises(FieldInUseError) as info:
        await service.update_field(
            db_session,
            field,
            initiator=owner,
            options=[FieldOption(key="major", name="Крупная")],
        )

    reported = (info.value.details["reason"], info.value.details["option"])
    assert reported == ("option_in_use", "minor")


async def test_option_can_always_be_renamed(
    db_session: AsyncSession, owner: Actor, issues_with_value: Callable[..., Awaitable[None]]
) -> None:
    """Хранится ключ, а не название, поэтому переименование ничего не ломает."""
    field = await make_field(
        db_session,
        owner,
        value_type=FieldValueType.ENUM,
        options=[FieldOption(key="minor", name="Мелкая")],
    )
    await issues_with_value(1, value="minor")

    updated = await service.update_field(
        db_session, field, initiator=owner, options=[FieldOption(key="minor", name="Небольшая")]
    )

    assert updated.options == [{"key": "minor", "name": "Небольшая"}]


async def test_default_can_be_dropped_and_left_alone_separately(
    db_session: AsyncSession, owner: Actor
) -> None:
    """Три состояния: не передано, передано `null`, передано значение."""
    field = await make_field(db_session, owner, default_value="minor")

    untouched = await service.update_field(db_session, field, initiator=owner, name="Критичность")
    assert untouched.default_value == "minor"

    cleared = await service.update_field(db_session, field, initiator=owner, default_value=None)
    assert cleared.default_value is None


# --- Удаление и скрытие ----------------------------------------------------------


async def test_field_with_values_cannot_be_deleted_only_hidden(
    db_session: AsyncSession, owner: Actor, issues_with_value: Callable[..., Awaitable[None]]
) -> None:
    field = await make_field(db_session, owner)
    await issues_with_value(1)

    with pytest.raises(FieldInUseError) as info:
        await service.delete_field(db_session, field, initiator=owner)

    assert info.value.details["hint"] == "hide the field instead"

    hidden = await service.update_field(db_session, field, initiator=owner, is_hidden=True)
    assert hidden.is_hidden is True


async def test_unused_field_is_deleted_outright(db_session: AsyncSession, owner: Actor) -> None:
    """Удаление существует ради опечатки в ключе сразу после создания: ключ неизменяем."""
    field = await make_field(db_session, owner)

    await service.delete_field(db_session, field, initiator=owner)

    with pytest.raises(FieldNotFoundError):
        await service.get_field(db_session, key="severity", queue=None)


# --- Проверка значений против базы -----------------------------------------------


async def test_values_are_validated_against_the_applicable_fields(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(
        db_session,
        owner,
        queue=queue,
        value_type=FieldValueType.ENUM,
        is_required=True,
        options=[FieldOption(key="minor", name="Мелкая")],
    )
    task = await issue_type(db_session, owner, "task")

    stored = await service.validate_issue_values(
        db_session, queue=queue, issue_type=task, values={"trk.severity": "minor"}
    )

    assert stored == {"TRK.severity": "minor"}


async def test_missing_required_value_is_reported_with_the_field_reference(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(db_session, owner, queue=queue, is_required=True)
    task = await issue_type(db_session, owner, "task")

    with pytest.raises(FieldValuesInvalidError) as info:
        await service.validate_issue_values(db_session, queue=queue, issue_type=task, values={})

    assert info.value.details["fields"] == [
        {"field": "TRK.severity", "reason": "required", "type": "string"}
    ]


async def test_value_of_a_field_that_does_not_apply_to_this_type_says_so(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Иначе агент пошёл бы заводить поле, которое уже есть."""
    bug = await issue_type(db_session, owner, "bug")
    task = await issue_type(db_session, owner, "task")
    await make_field(db_session, owner, queue=queue, issue_types=[bug])

    with pytest.raises(FieldValuesInvalidError) as info:
        await service.validate_issue_values(
            db_session, queue=queue, issue_type=task, values={"TRK.severity": "major"}
        )

    reported = info.value.details["fields"][0]
    assert (reported["reason"], reported["applies_to"]) == ("not_applicable", ["bug"])


async def test_value_of_a_hidden_field_says_the_field_is_hidden(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    field = await make_field(db_session, owner, queue=queue)
    await service.update_field(db_session, field, initiator=owner, is_hidden=True)
    task = await issue_type(db_session, owner, "task")

    with pytest.raises(FieldValuesInvalidError) as info:
        await service.validate_issue_values(
            db_session, queue=queue, issue_type=task, values={"TRK.severity": "major"}
        )

    assert info.value.details["fields"][0]["reason"] == "hidden"


async def test_reference_to_a_missing_actor_is_rejected(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    """Форму ссылки проверил домен, существование актора видно только базе."""
    await make_field(
        db_session, owner, key="reviewer", queue=queue, value_type=FieldValueType.ACTOR
    )
    task = await issue_type(db_session, owner, "task")

    accepted = await service.validate_issue_values(
        db_session, queue=queue, issue_type=task, values={"TRK.reviewer": "owner"}
    )
    assert accepted == {"TRK.reviewer": "owner"}

    with pytest.raises(FieldValuesInvalidError) as info:
        await service.validate_issue_values(
            db_session, queue=queue, issue_type=task, values={"TRK.reviewer": "nobody"}
        )

    reported = info.value.details["fields"][0]
    assert (reported["reason"], reported["value"]) == ("actor_not_found", "nobody")


async def test_default_value_fills_an_absent_field(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(db_session, owner, queue=queue, default_value="minor")
    task = await issue_type(db_session, owner, "task")

    stored = await service.validate_issue_values(
        db_session, queue=queue, issue_type=task, values={}
    )

    assert stored == {"TRK.severity": "minor"}


async def test_every_problem_reaches_the_client_in_one_answer(
    db_session: AsyncSession, owner: Actor, queue: Queue
) -> None:
    await make_field(
        db_session, owner, key="estimate", queue=queue, value_type=FieldValueType.NUMBER
    )
    await make_field(db_session, owner, key="due_on", queue=queue, value_type=FieldValueType.DATE)
    await make_field(db_session, owner, key="note", queue=queue, is_required=True)
    task = await issue_type(db_session, owner, "task")

    with pytest.raises(FieldValuesInvalidError) as info:
        await service.validate_issue_values(
            db_session,
            queue=queue,
            issue_type=task,
            values={"TRK.estimate": "много", "TRK.due_on": "скоро"},
        )

    assert sorted(item["field"] for item in info.value.details["fields"]) == [
        "TRK.due_on",
        "TRK.estimate",
        "TRK.note",
    ]
