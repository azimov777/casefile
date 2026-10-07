"""Области (TRK-555): карточка, атрибуты, дело и архив, оба интерфейса.

Правила — `CONCEPT.md`, 3.7 (решения владельца `TRK#16`, `TRK#17`): область живёт в
одном проекте, адрес — `ПРОЕКТ/ключ`, атрибуты и дело устроены как у проекта, архив
замораживает карточку, атрибуты и дело, а архив проекта — и его области.

Обзорные проверки задачи: (а) заведение и чтение по адресу `TRK/x`, описание длиннее 320
знаков — `area_description_too_long`; (б) изменение атрибута без причины отклоняется,
история — в деле области; (в) `note` в дело области, ссылка `TRK/x#1` из дела
задачи принимается, на несуществующую запись — отклоняется; (г) запись в дело архивной
области — `area_archived`, после `restore` проходит.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.case import AreaEntryRef, EntryType, parse_ref
from app.domain.errors import (
    AreaArchivedError,
    AreaDescriptionTooLongError,
    AreaKeyTakenError,
    AreaNotArchivedError,
    AreaNotFoundError,
    AreaReasonRequiredError,
    AttributeReasonRequiredError,
    EntryFieldsInvalidError,
    InvalidAreaKeyError,
    ProjectArchivedError,
    ProjectNotFoundError,
)
from app.domain.fields import FieldProblem
from app.services import areas as service
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import journal as journal_service
from app.services import projects as projects_service
from app.services.auth import Actor
from conftest import Connect, call, refuse, without_empty_standing

AREAS = "/api/v1/projects/{key}/areas"
AREA = "/api/v1/projects/{key}/areas/{area}"


async def _promotion(session: AsyncSession, actor: Actor, project: Project) -> Area:
    """Область `TRK/x` — на ней проверяется всё, что требует существующей области."""
    del project  # проект `TRK` заводит фикстура; адрес называет его сам
    return await service.create_area(
        session, actor=actor, address="TRK/x", title="Популяризация", description="Каталоги"
    )


def _reasons(error: pytest.ExceptionInfo[EntryFieldsInvalidError]) -> list[dict[str, Any]]:
    return list(error.value.details["fields"])


# --- Карточка: заведение и чтение -------------------------------------------------------


async def test_an_area_is_created_and_read_by_its_address(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Обзорная проверка (а): заводится и читается по адресу `TRK/x`; первая запись дела —
    `created`, и принадлежит она области, а не проекту."""
    created = await service.create_area(
        db_session, actor=main_actor, address="trk/X", title="  Популяризация ", description=""
    )

    found = await service.get_area(db_session, "TRK/x")
    assert found.id == created.id
    assert (found.address, found.key, found.title, found.archived_at) == (
        "TRK/x",
        "x",
        "Популяризация",
        None,
    )
    assert found.project_id == project.id

    [first] = (await EntryRepository(db_session).list_area_page(created.id)).items
    assert (first.no, first.type, first.title) == (1, EntryType.CREATED, "Area created")
    assert (first.area_id, first.project_id, first.task_id) == (created.id, None, None)


async def test_the_description_longer_than_320_characters_is_refused(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Обзорная проверка (а): описание длиннее 320 знаков — `area_description_too_long`
    и при заведении, и при правке; ровно 320 проходит."""
    with pytest.raises(AreaDescriptionTooLongError) as refused:
        await service.create_area(
            db_session, actor=main_actor, address="TRK/x", title="X", description="ж" * 321
        )
    assert refused.value.details == {"length": 321, "max_length": 320}

    area = await service.create_area(
        db_session, actor=main_actor, address="TRK/x", title="X", description="ж" * 320
    )
    with pytest.raises(AreaDescriptionTooLongError):
        await service.update_area(db_session, area, actor=main_actor, description="ж" * 321)


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("promotion", "not_an_address"),
        ("/promotion", "not_an_address"),
        ("TRK/", "pattern_mismatch"),
        ("TRK/-promo", "pattern_mismatch"),
        ("TRK/promo-", "pattern_mismatch"),
        ("TRK/pro_mo", "pattern_mismatch"),
        ("TRK/a/b", "pattern_mismatch"),
        ("TRK/" + "a" * 33, "pattern_mismatch"),
    ],
)
async def test_a_malformed_address_is_refused_with_invalid_area_key(
    db_session: AsyncSession, project: Project, main_actor: Actor, address: str, reason: str
) -> None:
    with pytest.raises(InvalidAreaKeyError) as refused:
        await service.create_area(db_session, actor=main_actor, address=address, title="X")

    assert refused.value.details["reason"] == reason


async def test_a_key_taken_in_the_project_is_refused_in_any_case(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    await _promotion(db_session, main_actor, project)

    with pytest.raises(AreaKeyTakenError) as refused:
        await service.create_area(db_session, actor=main_actor, address="trk/X", title="Y")

    assert refused.value.details == {"key": "TRK/x"}


async def test_the_same_key_lives_in_another_project(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Ключ уникален внутри проекта, а не в установке."""
    await _promotion(db_session, main_actor, project)
    await projects_service.create_project(db_session, actor=main_actor, key="OPS", title="Опс")

    other = await service.create_area(db_session, actor=main_actor, address="OPS/x", title="X")

    assert other.address == "OPS/x"


async def test_an_unknown_project_and_an_unknown_area_are_named_apart(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.get_area(db_session, "NOPE/x")
    with pytest.raises(ProjectNotFoundError):
        await service.create_area(db_session, actor=main_actor, address="NOPE/x", title="X")
    with pytest.raises(AreaNotFoundError) as missing:
        await service.get_area(db_session, "TRK/nope")

    assert missing.value.details == {"key": "TRK/nope"}


async def test_editing_the_card_files_field_changed_in_the_area_case(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    area = await _promotion(db_session, main_actor, project)

    await service.update_area(
        db_session, area, actor=main_actor, title="Продвижение", description="Каталоги"
    )

    entries = (await EntryRepository(db_session).list_area_page(area.id)).items
    assert [(e.type, e.payload) for e in entries[1:]] == [
        (
            EntryType.FIELD_CHANGED,
            {"field": "title", "before": "Популяризация", "after": "Продвижение"},
        )
    ]


async def test_the_project_lists_its_active_areas(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Список областей проекта: архивные — только по явной просьбе."""
    first = await _promotion(db_session, main_actor, project)
    second = await service.create_area(
        db_session, actor=main_actor, address="TRK/commerce", title="Коммерция"
    )
    await service.archive_area(db_session, first, actor=main_actor, reason="Закрыто")

    active = await service.list_areas(db_session, project, actor=main_actor)
    every = await service.list_areas(db_session, project, actor=main_actor, include_archived=True)

    assert [d.address for d in active] == [second.address]
    assert [d.address for d in every] == ["TRK/commerce", "TRK/x"]


# --- Атрибуты ---------------------------------------------------------------------------


async def test_changing_an_attribute_needs_a_reason_and_the_history_is_in_the_area_case(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Обзорная проверка (б): изменение без причины отклоняется, история атрибута — записи
    дела области, а не проекта."""
    area = await _promotion(db_session, main_actor, project)
    await attributes_service.set_attribute(
        db_session, area, actor=main_actor, name="Channel", value="reddit"
    )

    with pytest.raises(AttributeReasonRequiredError):
        await attributes_service.set_attribute(
            db_session, area, actor=main_actor, name="channel", value="x.com"
        )
    await attributes_service.set_attribute(
        db_session, area, actor=main_actor, name="channel", value="x.com", reason="Сменили"
    )

    [attribute] = await attributes_service.list_attributes(db_session, area, actor=main_actor)
    assert (attribute.name, attribute.value) == ("Channel", "x.com")
    assert await attributes_service.list_attributes(db_session, project, actor=main_actor) == []

    history = await case_service.list_project_entries(
        db_session, area, actor=main_actor, attribute="CHANNEL"
    )
    assert [(e.type, e.payload.get("reason")) for e in history.items] == [
        (EntryType.ATTRIBUTE_CREATED, None),
        (EntryType.ATTRIBUTE_CHANGED, "Сменили"),
    ]
    assert all(e.area_id == area.id for e in history.items)
    project_case = await case_service.list_project_entries(db_session, project, actor=main_actor)
    assert [e.type for e in project_case.items] == [EntryType.CREATED]


async def test_removing_an_attribute_files_the_last_value(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    area = await _promotion(db_session, main_actor, project)
    await attributes_service.set_attribute(
        db_session, area, actor=main_actor, name="channel", value="reddit"
    )

    entry = await attributes_service.remove_attribute(
        db_session, area, actor=main_actor, name="CHANNEL", reason="Ушли"
    )

    assert (entry.type, entry.area_id) == (EntryType.ATTRIBUTE_REMOVED, area.id)
    assert entry.payload == {"name": "channel", "before": "reddit", "reason": "Ушли"}
    assert await attributes_service.list_attributes(db_session, area, actor=main_actor) == []


# --- Дело и ссылки --------------------------------------------------------------------


async def test_a_note_is_filed_and_a_task_entry_cites_it_by_the_area_address(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor
) -> None:
    """Обзорная проверка (в): `note` в дело области принимается, ссылка `TRK/x#1` из
    дела задачи принимается и хранится канонической, на несуществующую запись —
    отклоняется."""
    area = await _promotion(db_session, main_actor, project)
    note = await case_service.append_project_entry(
        db_session, area, actor=main_actor, type="note", title="Общая память области"
    )
    assert (note.no, note.type, note.area_id) == (2, EntryType.NOTE, area.id)

    cited = await case_service.add_entry(
        db_session,
        task,
        actor=main_actor,
        type=EntryType.FINDING,
        title="Опора на запись области",
        refs=["trk/X#1", "TRK/x#2"],
    )
    assert cited.refs == ["TRK/x#1", "TRK/x#2"]

    with pytest.raises(EntryFieldsInvalidError) as refused:
        await case_service.add_entry(
            db_session,
            task,
            actor=main_actor,
            type=EntryType.FINDING,
            title="Ссылки мимо",
            refs=["TRK/x#99", "TRK/nope#1", "NOPE/x#1"],
        )
    assert _reasons(refused) == [
        {"field": "refs", "reason": "unknown_entry", "ref": "TRK/x#99"},
        {"field": "refs", "reason": "unknown_area", "ref": "TRK/nope#1"},
        {"field": "refs", "reason": "unknown_project", "ref": "NOPE/x#1"},
    ]


async def test_the_area_case_takes_no_supersedes(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Механики решений проекта у дела области нет: `supersedes` — отказ формы, а
    решение подшивается с пустой нагрузкой, как решение задачи."""
    area = await _promotion(db_session, main_actor, project)

    with pytest.raises(EntryFieldsInvalidError) as refused:
        await case_service.append_project_entry(
            db_session, area, actor=main_actor, type="decision", title="Тезис", supersedes=[1]
        )
    decision = await case_service.append_project_entry(
        db_session, area, actor=main_actor, type="decision", title="Каналы — Reddit и X"
    )

    assert _reasons(refused) == [
        {"field": "supersedes", "reason": "not_allowed", "allowed_in": "project_case"}
    ]
    assert decision.payload == {}


def test_the_area_entry_reference_is_parsed_apart_from_project_and_url() -> None:
    assert parse_ref("trk/Promotion#3") == AreaEntryRef(
        project_key="TRK", area_key="promotion", no=3
    )
    assert parse_ref("https://example.com/a/b#3") is None
    for wrong, reason in (
        ("docs/x.md#3", "not_a_reference"),
        ("TRK/promotion", "not_a_reference"),
        ("TRK/promotion#0", "malformed_entry_ref"),
        ("TRK/promotion#007", "malformed_entry_ref"),
    ):
        with pytest.raises(FieldProblem) as problem:
            parse_ref(wrong)
        assert problem.value.details["reason"] == reason, wrong


# --- Архив ------------------------------------------------------------------------------


async def test_an_archived_area_refuses_entries_until_it_is_restored(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Обзорная проверка (г): запись в дело архивной области — `area_archived`,
    после `restore` проходит."""
    area = await _promotion(db_session, main_actor, project)
    archived = await service.archive_area(db_session, area, actor=main_actor, reason="Пауза")
    assert (archived.type, archived.title, archived.payload) == (
        EntryType.ARCHIVED,
        "Area archived",
        {"reason": "Пауза"},
    )
    assert area.archived_at == archived.created_at

    with pytest.raises(AreaArchivedError) as refused:
        await case_service.append_project_entry(
            db_session, area, actor=main_actor, type="note", title="Запись в архив"
        )
    assert refused.value.details["key"] == "TRK/x"
    for frozen in (
        attributes_service.set_attribute(db_session, area, actor=main_actor, name="a", value="b"),
        service.update_area(db_session, area, actor=main_actor, title="Новое"),
        service.archive_area(db_session, area, actor=main_actor, reason="Ещё раз"),
    ):
        with pytest.raises(AreaArchivedError):
            await frozen

    restored = await service.restore_area(db_session, area, actor=main_actor, reason="Вернулись")
    assert (restored.type, area.archived_at) == (EntryType.RESTORED, None)
    note = await case_service.append_project_entry(
        db_session, area, actor=main_actor, type="note", title="После восстановления"
    )
    assert note.type is EntryType.NOTE


async def test_archive_and_restore_need_a_reason_and_restore_needs_an_archive(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    area = await _promotion(db_session, main_actor, project)

    with pytest.raises(AreaReasonRequiredError):
        await service.archive_area(db_session, area, actor=main_actor, reason="  ")
    with pytest.raises(AreaNotArchivedError):
        await service.restore_area(db_session, area, actor=main_actor, reason="Зачем")


async def test_an_archived_project_freezes_its_areas_and_is_named_first(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Архив проекта замораживает и области (`project_archived`), и называется раньше
    архива самой области — восстановить область в архивном проекте нельзя."""
    live = await _promotion(db_session, main_actor, project)
    paused = await service.create_area(
        db_session, actor=main_actor, address="TRK/commerce", title="Коммерция"
    )
    await service.archive_area(db_session, paused, actor=main_actor, reason="Пауза")
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Всё")

    for frozen in (
        case_service.append_project_entry(
            db_session, live, actor=main_actor, type="note", title="Нота"
        ),
        service.archive_area(db_session, live, actor=main_actor, reason="Тоже"),
        service.restore_area(db_session, paused, actor=main_actor, reason="Назад"),
        service.create_area(db_session, actor=main_actor, address="TRK/new", title="Нота"),
    ):
        with pytest.raises(ProjectArchivedError):
            await frozen


# --- Лента ------------------------------------------------------------------------------


async def test_the_journal_names_an_area_entry_by_its_address(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Запись дела области — в ленте с адресом области; отбор по проекту берёт и
    дела его областей."""
    start = await EntryRepository(db_session).latest_seq()
    area = await _promotion(db_session, main_actor, project)

    by_project = await journal_service.read_journal(
        db_session,
        actor=main_actor,
        journal_filter=await journal_service.resolve_filter(db_session, project="TRK"),
        after=start,
    )

    assert [(i.task_key, i.project_key, i.area) for i in by_project.items] == [
        (None, None, "TRK/x")
    ]
    assert by_project.items[0].entry.area_id == area.id


# --- REST -------------------------------------------------------------------------------


async def test_rest_creates_reads_edits_and_lists_an_area(
    auth_client: AsyncClient, project: Project
) -> None:
    created = await auth_client.post(
        AREAS.format(key="trk"),
        json={"key": "X", "title": "Популяризация", "description": "Каталоги"},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000001"},
    )
    assert created.status_code == 201, created.text
    card = created.json()["data"]
    assert (card["address"], card["project_key"], card["key"], card["archived_at"]) == (
        "TRK/x",
        "TRK",
        "x",
        None,
    )

    read = await auth_client.get(AREA.format(key="TRK", area="X"))
    assert read.status_code == 200, read.text
    assert (read.json()["data"]["address"], read.json()["data"]["attributes"]) == ("TRK/x", [])

    edited = await auth_client.patch(
        AREA.format(key="TRK", area="x"), json={"title": "Продвижение"}
    )
    assert edited.json()["data"]["title"] == "Продвижение"

    the_project = await auth_client.get("/api/v1/projects/TRK")
    assert the_project.json()["data"]["areas"] == [{"address": "TRK/x", "title": "Продвижение"}]
    listed = await auth_client.get(AREAS.format(key="TRK"))
    assert [item["address"] for item in listed.json()["data"]] == ["TRK/x"]


async def test_rest_refuses_a_long_description_and_a_taken_key(
    auth_client: AsyncClient, project: Project
) -> None:
    too_long = await auth_client.post(
        AREAS.format(key="TRK"),
        json={"key": "x", "title": "X", "description": "ж" * 321},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000002"},
    )
    assert (too_long.status_code, too_long.json()["error"]["code"]) == (
        422,
        "area_description_too_long",
    )

    for number, expected in ((3, 201), (4, 409)):
        response = await auth_client.post(
            AREAS.format(key="TRK"),
            json={"key": "x", "title": "X"},
            headers={"Idempotency-Key": f"d1ec7000-0000-4000-8000-00000000000{number}"},
        )
        assert response.status_code == expected, response.text
    assert response.json()["error"]["code"] == "area_key_taken"

    missing = await auth_client.get(AREA.format(key="TRK", area="nope"))
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "area_not_found")


async def test_rest_keeps_attributes_entries_and_the_archive_of_an_area(
    auth_client: AsyncClient, project: Project
) -> None:
    await auth_client.post(
        AREAS.format(key="TRK"),
        json={"key": "x", "title": "X"},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000005"},
    )
    base = AREA.format(key="TRK", area="x")

    attribute = await auth_client.put(
        f"{base}/attributes/channel",
        json={"value": "reddit"},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000006"},
    )
    assert attribute.status_code == 200, attribute.text
    unreasoned = await auth_client.put(
        f"{base}/attributes/channel",
        json={"value": "x.com"},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000007"},
    )
    assert unreasoned.json()["error"]["code"] == "attribute_reason_required"

    note = await auth_client.post(
        f"{base}/entries",
        json={"type": "note", "title": "Заметка", "refs": ["TRK/x#1"]},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000008"},
    )
    assert note.status_code == 201, note.text
    filed = note.json()["data"]
    assert (filed["no"], filed["task_key"], filed["project_key"], filed["area"]) == (
        3,
        None,
        None,
        "TRK/x",
    )
    superseding = await auth_client.post(
        f"{base}/entries",
        json={"type": "decision", "title": "Решение", "supersedes": [1]},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000009"},
    )
    assert superseding.status_code == 422

    archived = await auth_client.post(f"{base}/archive", json={"reason": "Пауза"})
    assert archived.json()["data"]["archived_at"] is not None
    frozen = await auth_client.post(
        f"{base}/entries",
        json={"type": "note", "title": "Запись в архив"},
        headers={"Idempotency-Key": "d1ec7000-0000-4000-8000-000000000010"},
    )
    assert (frozen.status_code, frozen.json()["error"]["code"]) == (409, "area_archived")
    restored = await auth_client.post(f"{base}/restore", json={"reason": "Вернулись"})
    assert restored.json()["data"]["archived_at"] is None

    entries = await auth_client.get(f"{base}/entries", params={"attribute": "channel"})
    assert [item["type"] for item in entries.json()["data"]] == ["attribute_created"]
    one = await auth_client.get(f"{base}/entries/1")
    assert (one.json()["data"]["type"], one.json()["data"]["area"]) == ("created", "TRK/x")


# --- MCP --------------------------------------------------------------------------------


async def test_mcp_creates_an_area_with_create_project_and_reads_it_with_get_project(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Живой путь агента: `create_project` по адресу заводит область, `get_project`
    проекта называет её, `get_project` по адресу отдаёт карточку, атрибуты и опись."""
    async with mcp_session(task_secret) as session:
        created = await call(
            session, "create_project", key="TRK/X", title="Популяризация", description="Каталоги"
        )
        await call(session, "set_attribute", key="TRK/x", name="channel", value="reddit")
        filed = await call(
            session, "add_project_entry", key="trk/x", type="note", title="Общая память"
        )
        the_project = await call(session, "get_project", key="TRK")
        the_area = await call(session, "get_project", key="TRK/x")
        bodies = await call(session, "read_project_entries", key="TRK/x", nos=[filed["no"]])

    assert created == {"key": "TRK/x"}
    assert (filed["no"], filed["project_key"]) == (3, "TRK/x")
    assert the_project["areas"] == [
        {"address": "TRK/x", "title": "Популяризация", "archived_at": None}
    ]
    assert (the_area["key"], the_area["description"]) == ("TRK/x", "Каталоги")
    assert the_area["attributes"] == [{"name": "channel", "value": "reddit"}]
    assert (the_area["decisions"], the_area["areas"]) == ([], [])
    assert [(line["no"], line["type"]) for line in the_area["index"]] == [
        (1, "created"),
        (2, "attribute_created"),
        (3, "note"),
    ]
    [entry] = bodies["items"]
    assert (entry["task_key"], entry["project_key"], entry["area"]) == (None, None, "TRK/x")


async def test_the_agent_path_goes_by_area_and_the_old_name_direction_is_refused(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Обзорная проверка 3 TRK-675: путь агента по новому имени, прежнее — отказ схемы.

    `create_project` по адресу заводит область, `get_project` проекта называет её в
    `areas`, `create_task(area=…)` ставит её задаче, `search_tasks(area=[…])` находит
    задачу. Имя `direction` переходного периода не имеет (TRK#12): аргумент
    `create_task`, отбор `search_tasks` и флаг `get_project` с ним отказывают
    `extra_forbidden` и называют лишнее имя.
    """
    async with mcp_session(task_secret) as session:
        created = await call(session, "create_project", key="TRK/mcp", title="MCP-сервер")
        the_project = await call(session, "get_project", key="TRK")
        filed = await call(
            session,
            "create_task",
            project="TRK",
            title="Задача области",
            description="Ставится в область при создании",
            area="TRK/mcp",
        )
        found = await call(session, "search_tasks", area=["TRK/mcp"], fields=["key", "area"])
        card = await call(session, "get_task", key=filed["key"])
        old_argument = await refuse(
            session,
            "create_task",
            project="TRK",
            title="По-старому",
            description="Прежнее имя поля",
            direction="TRK/mcp",
        )
        old_filter = await refuse(session, "search_tasks", direction=["TRK/mcp"])
        old_flag = await refuse(session, "get_project", key="TRK", include_archived_directions=True)
        after = await call(session, "search_tasks", project=["TRK"], fields=["key"])

    assert created == {"key": "TRK/mcp"}
    assert the_project["areas"] == [
        {"address": "TRK/mcp", "title": "MCP-сервер", "archived_at": None}
    ]
    assert found["items"] == [
        {"key": filed["key"], "area": {"address": "TRK/mcp", "title": "MCP-сервер"}}
    ]
    assert card["task"]["area"]["address"] == "TRK/mcp"
    for failure, name in (
        (old_argument, "direction"),
        (old_filter, "direction"),
        (old_flag, "include_archived_directions"),
    ):
        assert name in failure and "extra_forbidden" in failure, failure
    assert [item["key"] for item in after["items"]] == [filed["key"]]


async def test_mcp_archives_and_restores_an_area_by_its_address(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/x", title="X")
        archived = await call(session, "archive_project", key="TRK/x", reason="Пауза")
        frozen = await refuse(session, "add_project_entry", key="TRK/x", type="note", title="Нота")
        hidden = await call(session, "get_project", key="TRK")
        shown = await call(session, "get_project", key="TRK", include_archived_areas=True)
        restored = await call(session, "restore_project", key="TRK/x", reason="Назад")
        again = await refuse(session, "restore_project", key="TRK/x", reason="Ещё")
        taken = await refuse(session, "create_project", key="TRK/x", title="Y")
        superseding = await refuse(
            session,
            "add_project_entry",
            key="TRK/x",
            type="decision",
            title="Решение",
            supersedes=[1],
        )

    assert (archived["key"], archived["no"]) == ("TRK/x", 2)
    assert archived["archived_at"] is not None
    assert "area_archived" in frozen
    assert hidden["areas"] == []
    assert [d["address"] for d in shown["areas"]] == ["TRK/x"]
    assert (restored["key"], restored["archived_at"]) == ("TRK/x", None)
    assert "area_not_archived" in again
    assert "area_key_taken" in taken
    assert "supersedes" in superseding


async def test_an_area_entry_reads_the_same_through_mcp_and_rest(
    mcp_session: Connect, auth_client: AsyncClient, task_secret: str, project: Project
) -> None:
    """Запись дела области — одна форма в обеих дверях, с адресом в `area`."""
    async with mcp_session(task_secret) as session:
        await call(session, "create_project", key="TRK/x", title="X")
        await call(session, "add_project_entry", key="TRK/x", type="decision", title="Решение")
        from_mcp = await call(session, "read_project_entries", key="TRK/x")

    response = await auth_client.get(f"{AREA.format(key='TRK', area='x')}/entries")
    assert response.status_code == 200, response.text

    assert from_mcp["items"] == without_empty_standing(response.json()["data"])
    assert from_mcp["items"][1]["payload"] == {"supersedes": []}
