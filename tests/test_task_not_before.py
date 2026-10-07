"""Момент «не раньше»: поле `not_before`, признак `deferred`, отказ `task_deferred` (TRK-592).

Контракт — решение проекта `TRK#47`: необязательный момент со смещением пояса, правка в
любом незакрытом статусе с `field_changed`, держит только вход в `in_progress`, признак и
отбор считаются по часам базы одним выражением, наступление ничего не подшивает.

Часы в тестах — часы базы (`TaskRepository.clock`), и моменты ставятся от них на день в
обе стороны: вмороженная календарная дата однажды сделала бы набор красным без единой
правки (TRK-103, TRK-104). Тест идёт в одной транзакции, и `now()` в нём одно на весь тест.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import TaskRepository
from app.domain.case import EntryType
from app.domain.errors import TaskClosedError, TaskDeferredError, TaskFieldsInvalidError
from app.domain.tasks import (
    TaskField,
    TaskStatus,
    TransitionFacts,
    ensure_transition_allowed,
    moment_text,
    normalize_fields,
)
from app.services import case as case_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges
from conftest import Connect, call, refuse

#: Пояс постановщика: момент приходит со смещением его устройства, а не в UTC.
BERLIN_SUMMER = timezone(timedelta(hours=2))

DAY = timedelta(days=1)

#: Запрос кандидатов назначателя с условием `deferred: false` (решение проекта `TRK#47`, п. 5).
CANDIDATES = "status: open and blocked: false and open_blocking_questions: 0 and deferred: false"


async def _clock(session: AsyncSession) -> datetime:
    return await TaskRepository(session).clock()


def _iso(moment: datetime) -> str:
    """Момент строкой ISO 8601 со смещением пояса — как пишет `date -Iseconds`."""
    return moment.astimezone(BERLIN_SUMMER).isoformat()


async def _defer(session: AsyncSession, actor: Actor, task: Task, moment: Any) -> Any:
    return await tasks_service.update_task(
        session, task, actor=actor, changes=TaskChanges(not_before=moment)
    )


async def _field_changes(session: AsyncSession, actor: Actor, task: Task) -> list[dict[str, Any]]:
    entries = await case_service.list_entries(
        session, task, actor=actor, types=[EntryType.FIELD_CHANGED]
    )
    return [entry.payload for entry in entries.items]


async def _index_types(session: AsyncSession, actor: Actor, task: Task) -> list[EntryType]:
    return [heading.type for heading in await case_service.case_index(session, task, actor=actor)]


async def _keys(session: AsyncSession, actor: Actor, **kwargs: Any) -> list[str]:
    outcome = await search_service.search_tasks(session, actor=actor, **kwargs)
    return [found.task.key for found in outcome.page.items]


async def _open(session: AsyncSession, actor: Actor, task: Task) -> None:
    await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.OPEN)


async def _new(
    session: AsyncSession, actor: Actor, project: Project, title: str, **kw: Any
) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        project=project,
        title=title,
        description="Для проверки",
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
        assignee="owner",
        **kw,
    )


# --- Форма значения ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("2026-10-08", "time_required"),
        ("2026-10-08T09:00:00", "offset_required"),
        ("2026-10-08 09:00", "offset_required"),
        ("завтра в девять", "invalid_datetime"),
        ("", "invalid_datetime"),
        ("0001-01-01T00:00:00+05:00", "out_of_range"),
        (42, "not_a_string"),
    ],
)
def test_a_moment_without_a_time_or_an_offset_is_refused(value: Any, reason: str) -> None:
    """Дата без времени и время без пояса — `task_fields_invalid` с причиной и формой.

    Установка не знает, по каким часам написана строка без смещения; подставить полночь
    или пояс сервера значило бы отложить задачу не на тот момент (`TRK#47`, п. 1).
    """
    with pytest.raises(TaskFieldsInvalidError) as refused:
        normalize_fields({TaskField.NOT_BEFORE: value})

    [problem] = refused.value.details["fields"]
    assert (problem["field"], problem["reason"]) == ("not_before", reason)
    if reason != "not_a_string":
        assert problem["expected"] == "YYYY-MM-DDTHH:MM:SS±HH:MM"


@pytest.mark.parametrize(
    "value",
    ["2026-10-08T09:00:00+02:00", "2026-10-08T07:00:00Z", "2026-10-08T07:00:00+00:00"],
)
def test_a_moment_is_kept_as_an_instant_in_utc(value: str) -> None:
    """Хранится момент: одна и та же минута в разных поясах — одно значение."""
    normalized = normalize_fields({TaskField.NOT_BEFORE: value})[TaskField.NOT_BEFORE]

    assert normalized == datetime(2026, 10, 8, 7, 0, tzinfo=UTC)
    assert moment_text(normalized) == "2026-10-08T07:00:00Z"


def test_null_means_no_moment() -> None:
    assert normalize_fields({TaskField.NOT_BEFORE: None}) == {TaskField.NOT_BEFORE: None}


# --- Проверка входа в домене --------------------------------------------------------------


def _facts(from_status: TaskStatus, to_status: TaskStatus, **kw: Any) -> TransitionFacts:
    """Факты перехода, где сошлось всё, кроме момента: блокеров и вопросов нет."""
    given: dict[str, Any] = {
        "reason": None,
        "sections": {},
        "checks": ("проверка",),
        "open_blockers": (),
        "open_blocking_questions": (),
        "assignee": "claude",
        "requester": "claude",
        **kw,
    }
    return TransitionFacts(key="TRK-1", from_status=from_status, to_status=to_status, **given)


def test_the_domain_refuses_entry_while_deferred_and_names_the_moment() -> None:
    moment = datetime(2026, 10, 8, 9, 0, tzinfo=BERLIN_SUMMER)

    with pytest.raises(TaskDeferredError) as refused:
        ensure_transition_allowed(
            _facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, deferred=True, not_before=moment)
        )

    assert refused.value.code == "task_deferred"
    assert refused.value.details == {
        "key": "TRK-1",
        "from": "open",
        "to": "in_progress",
        "not_before": "2026-10-08T07:00:00Z",
    }
    ensure_transition_allowed(
        _facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS, deferred=False, not_before=moment)
    )


def test_an_uncounted_deferral_forbids_entry_with_its_own_reason() -> None:
    """Незаполненный факт запрещает вход, а не пропускает его, как у блокеров."""
    with pytest.raises(TaskDeferredError) as refused:
        ensure_transition_allowed(_facts(TaskStatus.OPEN, TaskStatus.IN_PROGRESS))

    assert refused.value.details["reason"] == "deferral_not_collected"
    assert "not_before" not in refused.value.details


def test_the_moment_holds_only_the_entry_into_work() -> None:
    """`backlog → open` и уход из работы момент не видят (`TRK#47`, п. 4)."""
    filled = {
        TaskField.GOAL: "цель",
        TaskField.CONTEXT: "контекст",
        TaskField.CONSTRAINTS: "ограничения",
        TaskField.OUTPUT: "выход",
    }
    ensure_transition_allowed(
        _facts(TaskStatus.BACKLOG, TaskStatus.OPEN, deferred=True, sections=filled)
    )
    ensure_transition_allowed(
        _facts(
            TaskStatus.IN_PROGRESS,
            TaskStatus.OPEN,
            deferred=True,
            reason="жду момента",
            has_summary_since_in_progress=True,
        )
    )


# --- Вход в работу по часам базы -------------------------------------------------------------


async def test_entry_before_the_moment_is_refused_with_task_deferred(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    """Обзорная проверка 1: момент = часы базы + 1 день → `409 task_deferred`."""
    await _open(db_session, main_actor, task)
    moment = await _clock(db_session) + DAY
    await _defer(db_session, main_actor, task, _iso(moment))
    entries_before = len(await _index_types(db_session, main_actor, task))

    with pytest.raises(TaskDeferredError) as refused:
        await tasks_service.transition_task(
            db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
        )

    assert refused.value.details == {
        "key": task.key,
        "from": "open",
        "to": "in_progress",
        "not_before": moment_text(moment),
    }
    assert task.status is TaskStatus.OPEN
    assert len(await _index_types(db_session, main_actor, task)) == entries_before, (
        "отказ ничего не подшивает"
    )


async def test_entry_after_the_moment_passes_without_a_tracker_entry(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    """Обзорная проверка 1: момент = часы базы − 1 день → вход проходит.

    Наступивший момент ничего не подшивает: после правки поля в деле только сам переход.
    """
    await _open(db_session, main_actor, task)
    await _defer(db_session, main_actor, task, _iso(await _clock(db_session) - DAY))
    before = await _index_types(db_session, main_actor, task)

    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
    )

    after = await _index_types(db_session, main_actor, task)
    assert task.status is TaskStatus.IN_PROGRESS
    assert after == [*before, EntryType.STATUS_CHANGED]


async def test_clearing_the_moment_opens_the_way_and_each_edit_files_field_changed(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    await _open(db_session, main_actor, task)
    moment = await _clock(db_session) + DAY
    await _defer(db_session, main_actor, task, _iso(moment))
    with pytest.raises(TaskDeferredError):
        await tasks_service.transition_task(
            db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
        )

    cleared = await _defer(db_session, main_actor, task, None)
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
    )

    assert cleared.changed
    assert task.not_before is None
    assert await _field_changes(db_session, main_actor, task) == [
        {"field": "not_before", "before": None, "after": moment_text(moment)},
        {"field": "not_before", "before": moment_text(moment), "after": None},
    ]


async def test_the_same_instant_in_another_offset_changes_nothing(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    moment = await _clock(db_session) + DAY
    await _defer(db_session, main_actor, task, _iso(moment))
    version = task.version

    same = await _defer(db_session, main_actor, task, moment_text(moment))

    assert not same.changed
    assert task.version == version
    assert len(await _field_changes(db_session, main_actor, task)) == 1


async def test_the_moment_is_editable_in_every_unclosed_status_and_refused_when_closed(
    db_session: AsyncSession, main_actor: Actor, project: Project, task: Task
) -> None:
    clock = await _clock(db_session)
    await _defer(db_session, main_actor, task, _iso(clock + DAY))
    await _open(db_session, main_actor, task)
    await _defer(db_session, main_actor, task, None)
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
    )
    await _defer(db_session, main_actor, task, _iso(clock + 2 * DAY))

    cancelled = await _new(db_session, main_actor, project, "Отменённая")
    await tasks_service.transition_task(
        db_session, cancelled, actor=main_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )
    with pytest.raises(TaskClosedError) as refused:
        await _defer(db_session, main_actor, cancelled, _iso(clock + DAY))

    assert refused.value.details["fields"] == ["not_before"]
    assert len(await _field_changes(db_session, main_actor, task)) == 3


async def test_a_task_in_progress_keeps_working_and_the_moment_holds_the_next_entry(
    db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    """Момент у задачи в работе текущий проход не прерывает (`TRK#47`, п. 3)."""
    await _open(db_session, main_actor, task)
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
    )
    await _defer(db_session, main_actor, task, _iso(await _clock(db_session) + DAY))
    assert task.status is TaskStatus.IN_PROGRESS

    await case_service.add_summary(
        db_session,
        task,
        actor=main_actor,
        done="Отправлено, ждать недели",
        remaining="Сверка",
        blockers="Момент not_before",
        next_step="Сверить",
    )
    await tasks_service.transition_task(
        db_session, task, actor=main_actor, to=TaskStatus.OPEN, reason="Жду момента"
    )
    with pytest.raises(TaskDeferredError):
        await tasks_service.transition_task(
            db_session, task, actor=main_actor, to=TaskStatus.IN_PROGRESS
        )


async def test_a_task_born_deferred_names_the_moment_in_its_case(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    """Носитель ожидания виден в деле с рождения: `field_changed` одним действием с `created`."""
    moment = await _clock(db_session) + DAY

    created = await _new(db_session, main_actor, project, "Отложенная", not_before=_iso(moment))
    plain = await _new(db_session, main_actor, project, "Без момента")

    assert created.not_before == moment
    assert await _field_changes(db_session, main_actor, created) == [
        {"field": "not_before", "before": None, "after": moment_text(moment)}
    ]
    page = await case_service.list_entries(db_session, created, actor=main_actor)
    assert [entry.type for entry in page.items] == [EntryType.CREATED, EntryType.FIELD_CHANGED]
    assert page.items[0].action_id == page.items[1].action_id
    assert await _field_changes(db_session, main_actor, plain) == []


# --- Признак карточки и отбор ---------------------------------------------------------------


async def test_the_card_feature_and_the_selection_name_the_same_tasks(
    db_session: AsyncSession, main_actor: Actor, project: Project
) -> None:
    """Обзорная проверка 1: `features.deferred` карточки и отбор `deferred: true` совпадают.

    Задачи с моментом впереди, позади и без момента, в разных статусах: карточка считает
    признак своим запросом, выдача — колонкой и условием, и состав обязан сойтись.
    """
    clock = await _clock(db_session)
    ahead = await _new(db_session, main_actor, project, "Впереди", not_before=_iso(clock + DAY))
    behind = await _new(db_session, main_actor, project, "Позади", not_before=_iso(clock - DAY))
    plain = await _new(db_session, main_actor, project, "Без момента")
    ahead_open = await _new(
        db_session, main_actor, project, "Впереди, открыта", not_before=_iso(clock + DAY)
    )
    await _open(db_session, main_actor, ahead_open)
    tasks = [ahead, behind, plain, ahead_open]

    by_card = set()
    for item in tasks:
        package = await tasks_service.read_task_package(db_session, item.key, actor=main_actor)
        if package.features.deferred:
            by_card.add(item.key)
    selected = set(await _keys(db_session, main_actor, query="deferred: true"))
    not_selected = set(await _keys(db_session, main_actor, query="deferred: false"))
    structured = set(
        await _keys(
            db_session,
            main_actor,
            structured=[search_service.StructuredTerm(name="deferred", values=[True])],
        )
    )
    rows = await search_service.search_tasks(db_session, actor=main_actor, query="project: TRK")

    assert by_card == {ahead.key, ahead_open.key}
    assert selected == by_card == structured
    assert not_selected == {behind.key, plain.key}
    assert {found.task.key for found in rows.page.items if found.features.deferred} == by_card
    # Запрос кандидатов назначателя (`TRK#47`, п. 5): единственная открытая задача отложена.
    assert await _keys(db_session, main_actor, query=CANDIDATES) == []


# --- REST ------------------------------------------------------------------------------------


async def test_a_human_patch_sets_the_moment_and_files_field_changed_by_a_human(
    auth_client: AsyncClient, db_session: AsyncSession, task: Task
) -> None:
    """Обзорная проверка 1: `PATCH /api/v1/tasks/{key}` от человека меняет поле и подшивает
    `field_changed` с `author.kind: human`."""
    moment = await _clock(db_session) + DAY

    patched = await auth_client.patch(
        f"/api/v1/tasks/{task.key}", json={"not_before": _iso(moment)}
    )
    entries = await auth_client.get(
        f"/api/v1/tasks/{task.key}/entries", params={"types": "field_changed"}
    )
    package = await auth_client.get(f"/api/v1/tasks/{task.key}")

    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["not_before"] == moment_text(moment)
    [entry] = entries.json()["data"]
    assert entry["author"]["kind"] == "human"
    assert entry["author"]["signature"] == "owner"
    assert entry["payload"] == {"field": "not_before", "before": None, "after": moment_text(moment)}
    assert package.json()["data"]["task"]["not_before"] == moment_text(moment)
    assert package.json()["data"]["features"]["deferred"] is True


async def test_rest_refuses_entry_with_task_deferred_and_the_moment_in_details(
    auth_client: AsyncClient, db_session: AsyncSession, main_actor: Actor, task: Task
) -> None:
    await _open(db_session, main_actor, task)
    moment = await _clock(db_session) + DAY
    await auth_client.patch(f"/api/v1/tasks/{task.key}", json={"not_before": _iso(moment)})

    refused = await auth_client.post(
        f"/api/v1/tasks/{task.key}/transition", json={"to": "in_progress"}
    )
    cleared = await auth_client.patch(f"/api/v1/tasks/{task.key}", json={"not_before": None})
    entered = await auth_client.post(
        f"/api/v1/tasks/{task.key}/transition", json={"to": "in_progress"}
    )

    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "task_deferred"
    assert error["details"] == {
        "key": task.key,
        "from": "open",
        "to": "in_progress",
        "not_before": moment_text(moment),
    }
    assert cleared.json()["data"]["not_before"] is None
    assert entered.status_code == 200, entered.text


@pytest.mark.parametrize(
    ("value", "reason"),
    [("2026-10-08T09:00:00", "offset_required"), ("2026-10-08", "time_required")],
)
async def test_rest_refuses_a_moment_without_a_time_or_an_offset(
    auth_client: AsyncClient, task: Task, value: str, reason: str
) -> None:
    patched = await auth_client.patch(f"/api/v1/tasks/{task.key}", json={"not_before": value})
    created = await auth_client.post(
        "/api/v1/tasks",
        json={"project": "TRK", "title": "Новая", "description": "d", "not_before": value},
    )

    for response in (patched, created):
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "task_fields_invalid"
        assert error["details"]["fields"][0]["reason"] == reason


async def test_rest_creates_and_finds_deferred_tasks(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    moment = await _clock(db_session) + DAY

    created = await auth_client.post(
        "/api/v1/tasks",
        json={"project": "TRK", "title": "Новая", "description": "d", "not_before": _iso(moment)},
    )
    by_query = await auth_client.get(
        "/api/v1/tasks", params={"query": "deferred: true", "fields": "key,not_before,features"}
    )
    by_filter = await auth_client.get("/api/v1/tasks", params={"deferred": "true", "fields": "key"})

    assert created.status_code == 201, created.text
    key = created.json()["data"]["key"]
    assert created.json()["data"]["not_before"] == moment_text(moment)
    [row] = by_query.json()["data"]
    assert row["key"] == key
    assert row["not_before"] == moment_text(moment)
    assert row["features"]["deferred"] is True
    assert [item["key"] for item in by_filter.json()["data"]] == [key]


# --- MCP -------------------------------------------------------------------------------------


async def test_mcp_defers_refuses_clears_and_enters(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession, project: Project
) -> None:
    """Сценарий проверки 4 на тестовом сервере: момент, отказ, снятие, вход, две записи."""
    moment = await _clock(db_session) + DAY
    async with mcp_session(task_secret) as session:
        created = await call(
            session,
            "create_task",
            project="TRK",
            title="Отложенная",
            description="Ждёт момента",
            sections={
                "goal": "цель",
                "context": "контекст",
                "constraints": "ограничения",
                "output": "выход",
                "checks": ["проверка"],
            },
            not_before=_iso(moment),
        )
        key = created["key"]
        await call(session, "transition", key=key, to="open")
        await call(session, "update_task", key=key, changes={"assignee": "owner"})
        card = await call(session, "get_task", key=key)
        found = await call(session, "search_tasks", deferred=True, fields=["key", "not_before"])
        refused = await refuse(session, "transition", key=key, to="in_progress")
        bad = await refuse(
            session, "update_task", key=key, changes={"not_before": "2026-10-08T09:00:00"}
        )
        await call(session, "update_task", key=key, changes={"not_before": None})
        entered = await call(session, "transition", key=key, to="in_progress")
        changed = await call(session, "read_entries", key=key, types=["field_changed"])

    assert card["task"]["not_before"] == moment_text(moment)
    assert card["features"]["deferred"] is True
    assert found["items"] == [{"key": key, "not_before": moment_text(moment)}]
    assert "task_deferred" in refused
    assert moment_text(moment) in refused
    assert "task_fields_invalid" in bad and "offset_required" in bad
    assert entered["status"] == "in_progress"
    # Две записи про момент: постановка при заведении и снятие.
    assert [item["payload"] for item in changed["items"]] == [
        {"field": "not_before", "before": None, "after": moment_text(moment)},
        {"field": "not_before", "before": moment_text(moment), "after": None},
    ]
