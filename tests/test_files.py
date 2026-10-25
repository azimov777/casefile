"""Файлы в ядре (TRK-734): загрузка, замена, выдача, удаление с надгробием, список,
вложения записей дела, предел размера, заморозка архива и перенос установки.

Входов REST и MCP у файлов ещё нет (их делают следующие задачи), поэтому сценарии
зовутся напрямую — как их позовут оба интерфейса (TRK#216).
"""

import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.file import EntryFile, File, FileContent
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import (
    EntryFieldsInvalidError,
    FileDeletedError,
    FileFieldsInvalidError,
    FileTooLargeError,
    ProjectArchivedError,
    TrackerFileNotFoundError,
)
from app.domain.files import MAX_ENTRY_FILES, FileCard, FileSort
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import files as service
from app.services import projects as projects_service
from app.services.auth import Actor
from conftest import make_task
from test_archive import ARCHIVE, bearer, fresh_installation, wipe

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4  # байты, не похожие на текст


async def upload(
    session: AsyncSession,
    actor: Actor,
    project: Project,
    name: str = "scheme.png",
    data: bytes = PNG,
    mime_type: str | None = "image/png",
) -> FileCard:
    return await service.upload_file(
        session, actor=actor, project=project.key, name=name, data=data, mime_type=mime_type
    )


async def attach(
    session: AsyncSession, task: Task, actor: Actor, *cards: FileCard, title: str = "Схема"
) -> Any:
    return await case_service.add_entry(
        session,
        task,
        actor=actor,
        type="note",
        title=title,
        files=[card.id for card in cards],
    )


async def attachments_of(session: AsyncSession, entry: Any) -> list[FileCard]:
    return (await service.entry_attachments(session, [entry])).get(entry.id, [])


# --- Загрузка ---------------------------------------------------------------------


async def test_an_uploaded_file_has_a_card_with_its_history(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)

    assert (card.project_key, card.name, card.mime_type) == ("TRK", "scheme.png", "image/png")
    assert card.size_bytes == len(PNG)
    assert card.sha256 == hashlib.sha256(PNG).hexdigest()
    assert card.added_by.signature == "owner"
    assert card.added_at is not None
    assert (card.replaced_by, card.replaced_at, card.last_opened_at) == (None, None, None)
    assert not card.deleted and (card.entries, card.tasks) == (0, 0)
    assert await service.read_file(db_session, card.id, actor=main_actor) == card


async def test_name_and_type_are_checked_and_a_missing_type_is_octet_stream(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    plain = await upload(db_session, main_actor, project, name=" notes.txt ", mime_type=None)
    assert (plain.name, plain.mime_type) == ("notes.txt", "application/octet-stream")
    typed = await upload(db_session, main_actor, project, mime_type="Text/Plain; charset=utf-8")
    assert typed.mime_type == "text/plain"

    for name, mime in (
        ("", None),
        ("a/b.png", None),
        ("..", None),
        ("x" * 300, None),
        ("ok", "png"),
    ):
        with pytest.raises(FileFieldsInvalidError) as refusal:
            await upload(db_session, main_actor, project, name=name, mime_type=mime)
        assert refusal.value.details["fields"]


async def test_a_file_over_the_limit_is_refused_with_the_limit_in_details(
    db_session: AsyncSession,
    project: Project,
    main_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "file_max_bytes", 100)

    exactly = await upload(db_session, main_actor, project, data=b"x" * 100)
    assert exactly.size_bytes == 100
    with pytest.raises(FileTooLargeError) as refusal:
        await upload(db_session, main_actor, project, data=b"x" * 101)
    assert refusal.value.details == {"size": 101, "max_bytes": 100}
    with pytest.raises(FileTooLargeError):
        await service.replace_file(db_session, exactly.id, actor=main_actor, data=b"y" * 101)
    # Отказ ничего не сохранил: байты прежние.
    assert (await service.open_file(db_session, exactly.id, actor=main_actor)).data == b"x" * 100
    assert await db_session.scalar(select(func.count()).select_from(File)) == 1


def test_the_limit_defaults_to_twenty_five_megabytes() -> None:
    assert get_settings().file_max_bytes == 25 * 1024 * 1024


# --- Замена ----------------------------------------------------------------------


async def test_a_replaced_file_shows_new_content_in_the_entry_that_attaches_it(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor, task_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)
    entry = await attach(db_session, task, task_actor, card)
    assert [item.sha256 for item in await attachments_of(db_session, entry)] == [card.sha256]

    fresh = b"new bytes"
    replaced = await service.replace_file(
        db_session, card.id, actor=task_actor, data=fresh, mime_type="text/plain"
    )

    assert replaced.id == card.id  # та же ссылка
    assert (replaced.size_bytes, replaced.mime_type) == (len(fresh), "text/plain")
    assert replaced.replaced_by is not None and replaced.replaced_by.signature == "owner"
    assert replaced.replaced_at is not None
    assert replaced.added_at == card.added_at and replaced.name == card.name
    shown = await attachments_of(db_session, entry)
    assert [(item.sha256, item.size_bytes) for item in shown] == [
        (hashlib.sha256(fresh).hexdigest(), len(fresh))
    ]
    opened = await service.open_file(db_session, card.id, actor=main_actor)
    assert opened.data == fresh
    # Прежние байты не хранятся.
    contents = (await db_session.scalars(select(FileContent.data))).all()
    assert contents == [fresh]


# --- Выдача ----------------------------------------------------------------------


async def test_serving_the_bytes_sets_last_opened(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)
    assert card.last_opened_at is None

    first = await service.open_file(db_session, card.id, actor=main_actor)
    assert first.data == PNG
    assert first.card.last_opened_at is not None
    again = await service.open_file(db_session, card.id, actor=main_actor)
    assert again.card.last_opened_at is not None
    assert again.card.last_opened_at >= first.card.last_opened_at
    # Карточка и список байтов не выдают и отметку не ставят.
    other = await upload(db_session, main_actor, project, name="other.png")
    await service.read_file(db_session, other.id, actor=main_actor)
    await service.list_files(db_session, actor=main_actor)
    assert (await service.read_file(db_session, other.id, actor=main_actor)).last_opened_at is None


async def test_an_unknown_file_is_not_found(db_session: AsyncSession, main_actor: Actor) -> None:
    for call in (service.read_file, service.open_file, service.delete_file):
        with pytest.raises(TrackerFileNotFoundError):
            await call(db_session, uuid.uuid4(), actor=main_actor)


# --- Удаление и надгробие --------------------------------------------------------


async def test_a_deleted_file_leaves_a_tombstone_and_the_entry_says_so(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor, task_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)
    entry = await attach(db_session, task, task_actor, card)

    tomb = await service.delete_file(db_session, card.id, actor=task_actor)

    assert tomb.deleted and tomb.deleted_at is not None
    assert tomb.deleted_by is not None and tomb.deleted_by.signature == "owner"
    assert (tomb.name, tomb.size_bytes, tomb.sha256) == (card.name, card.size_bytes, card.sha256)
    assert await db_session.scalar(select(func.count()).select_from(FileContent)) == 0
    shown = await attachments_of(db_session, entry)
    assert [item.deleted for item in shown] == [True]
    assert shown[0].name == card.name
    # Надгробие читается, но байтов нет, заменить и приложить его нельзя.
    assert (await service.read_file(db_session, card.id, actor=main_actor)).deleted
    with pytest.raises(FileDeletedError):
        await service.open_file(db_session, card.id, actor=main_actor)
    with pytest.raises(FileDeletedError):
        await service.replace_file(db_session, card.id, actor=main_actor, data=b"x")
    with pytest.raises(FileDeletedError):
        await service.delete_file(db_session, card.id, actor=main_actor)
    with pytest.raises(FileDeletedError):
        await attach(db_session, task, task_actor, card, title="Ещё раз")


# --- Вложения записей ------------------------------------------------------------


async def test_entries_attach_files_in_order_and_cards_count_references(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor, task_actor: Actor
) -> None:
    first = await upload(db_session, main_actor, project, name="a.png")
    second = await upload(db_session, main_actor, project, name="b.png")
    other_task = await make_task(
        db_session, actor=task_actor, project=project, title="Вторая", description="Есть"
    )

    entry = await attach(db_session, task, task_actor, second, first)
    await attach(db_session, task, task_actor, first, title="И ещё раз")
    await attach(db_session, other_task, task_actor, first, title="Из другой задачи")
    plain = await case_service.add_entry(
        db_session, task, actor=task_actor, type="note", title="Без файлов"
    )

    assert [item.name for item in await attachments_of(db_session, entry)] == ["b.png", "a.png"]
    assert await attachments_of(db_session, plain) == []
    counted = await service.read_file(db_session, first.id, actor=main_actor)
    assert (counted.entries, counted.tasks) == (3, 2)
    lonely = await service.read_file(db_session, second.id, actor=main_actor)
    assert (lonely.entries, lonely.tasks) == (1, 1)


async def test_an_entry_can_attach_a_file_of_another_project(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor, task_actor: Actor
) -> None:
    elsewhere = await projects_service.create_project(
        db_session, actor=main_actor, key="OTH", title="Другой", description="Другой проект"
    )
    card = await upload(db_session, main_actor, elsewhere)

    entry = await attach(db_session, task, task_actor, card)

    assert [item.project_key for item in await attachments_of(db_session, entry)] == ["OTH"]


async def test_project_and_discussion_entries_take_files_too(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)

    note = await case_service.append_project_entry(
        db_session, project, actor=main_actor, type="note", title="Схема", files=[str(card.id)]
    )
    discussion = await discussions_service.create_discussion(
        db_session, actor=main_actor, project=project, title="Про схему", opening=EntryType.NOTE
    )
    reply = await case_service.add_discussion_entry(
        db_session, discussion, actor=main_actor, type="note", title="Вот", files=[card.id]
    )

    assert [item.id for item in await attachments_of(db_session, note)] == [card.id]
    assert [item.id for item in await attachments_of(db_session, reply)] == [card.id]
    assert (await service.read_file(db_session, card.id, actor=main_actor)).entries == 2


async def test_a_bad_file_list_is_refused_and_files_none_are_attached(
    db_session: AsyncSession, project: Project, task: Task, main_actor: Actor, task_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)
    many = [uuid.uuid4() for _ in range(MAX_ENTRY_FILES + 1)]
    for bad in ("abc", [card.id, card.id], ["not-an-id"], many, 5):
        with pytest.raises(EntryFieldsInvalidError) as refusal:
            await case_service.add_entry(
                db_session, task, actor=task_actor, type="note", title="Плохо", files=bad
            )
        assert refusal.value.details["fields"][0]["field"] == "files"
    with pytest.raises(TrackerFileNotFoundError):
        await attach(db_session, task, task_actor, replace(card, id=uuid.uuid4()))
    assert await db_session.scalar(select(func.count()).select_from(EntryFile)) == 0


# --- Архивный проект -------------------------------------------------------------


async def test_an_archived_project_freezes_its_files_but_still_serves_them(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)
    live_project = await projects_service.create_project(
        db_session, actor=main_actor, key="LIV", title="Живой", description="Живой проект"
    )
    live = await upload(db_session, main_actor, live_project, name="live.png")
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")

    with pytest.raises(ProjectArchivedError):
        await upload(db_session, main_actor, project, name="more.png")
    with pytest.raises(ProjectArchivedError):
        await service.replace_file(db_session, card.id, actor=main_actor, data=b"x")
    with pytest.raises(ProjectArchivedError):
        await service.delete_file(db_session, card.id, actor=main_actor)

    assert (await service.read_file(db_session, card.id, actor=main_actor)).name == card.name
    assert (await service.open_file(db_session, card.id, actor=main_actor)).data == PNG
    # В общем списке архивный проект скрыт, названный явно — виден.
    everywhere = await service.list_files(db_session, actor=main_actor)
    assert [item.id for item in everywhere.items] == [live.id]
    named = await service.list_files(db_session, actor=main_actor, project="TRK")
    assert [item.id for item in named.items] == [card.id]


# --- Список ----------------------------------------------------------------------


async def test_the_list_sorts_by_size_and_filters_by_type_name_and_project(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OTH", title="Другой", description="Другой проект"
    )
    sizes = {"a.png": 30, "b.png": 10, "c.pdf": 20, "d.jpg": 40}
    types = {"png": "image/png", "pdf": "application/pdf", "jpg": "image/jpeg"}
    cards = {
        name: await upload(
            db_session,
            main_actor,
            other if name == "d.jpg" else project,
            name=name,
            data=b"x" * size,
            mime_type=types[name.rsplit(".", 1)[1]],
        )
        for name, size in sizes.items()
    }

    # `now()` одинаков на всю транзакцию теста (TRK/db#35): дни добавления разводим руками.
    for day, card in enumerate(cards.values()):
        stored = await db_session.get(File, card.id)
        assert stored is not None
        stored.created_at = datetime(2026, 10, 1 + day, tzinfo=UTC)
    await db_session.flush()

    async def names(**filters: Any) -> list[str]:
        page = await service.list_files(db_session, actor=main_actor, **filters)
        return [item.name for item in page.items]

    assert await names(sort=FileSort.SIZE, descending=False) == ["b.png", "c.pdf", "a.png", "d.jpg"]
    assert await names(sort=FileSort.SIZE) == ["d.jpg", "a.png", "c.pdf", "b.png"]
    assert (await names(sort=FileSort.TYPE, descending=False))[:2] == ["c.pdf", "d.jpg"]
    assert sorted(await names(mime_type="image")) == ["a.png", "b.png", "d.jpg"]
    assert sorted(await names(mime_type="image/*")) == ["a.png", "b.png", "d.jpg"]
    assert await names(mime_type="image/png", sort=FileSort.SIZE) == ["a.png", "b.png"]
    assert await names(mime_type="application/pdf") == ["c.pdf"]
    assert await names(query="PNG", sort=FileSort.SIZE, mime_type="image") == ["a.png", "b.png"]
    assert await names(project="OTH") == ["d.jpg"]
    assert await names(query="100%") == []  # шаблон LIKE не работает как шаблон

    await service.open_file(db_session, cards["b.png"].id, actor=main_actor)
    assert (await names(sort=FileSort.OPENED))[0] == "b.png"
    assert (await names(sort=FileSort.ADDED))[0] == "d.jpg"
    assert (await names(sort=FileSort.ADDED, descending=False))[0] == "a.png"


async def test_the_list_pages_by_cursor_without_gaps_or_repeats(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    for index in range(7):  # размеры повторяются: тайбрейкер обязателен
        await upload(db_session, main_actor, project, name=f"f{index}.bin", data=b"x" * (index % 3))

    for descending in (False, True):
        seen: list[uuid.UUID] = []
        cursor = None
        while True:
            page = await service.list_files(
                db_session,
                actor=main_actor,
                sort=FileSort.SIZE,
                descending=descending,
                limit=2,
                cursor=cursor,
            )
            seen += [item.id for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 7


async def test_deleted_files_leave_the_list_unless_asked_for(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    keep = await upload(db_session, main_actor, project, name="keep.png")
    gone = await upload(db_session, main_actor, project, name="gone.png")
    await service.delete_file(db_session, gone.id, actor=main_actor)

    plain = await service.list_files(db_session, actor=main_actor)
    assert [item.id for item in plain.items] == [keep.id]
    full = await service.list_files(db_session, actor=main_actor, include_deleted=True)
    assert {item.id: item.deleted for item in full.items} == {keep.id: False, gone.id: True}


# --- Перенос установки -----------------------------------------------------------


async def test_the_installation_archive_carries_files_and_tombstones(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    task: Task,
    main_actor: Actor,
    task_actor: Actor,
) -> None:
    """Обзорная проверка 4: sha256 каждого файла и надгробия после приёма — исходные."""
    big = bytes(range(256)) * 600 + b"\\\t\n\r\x00 tail"  # байты, которые COPY читает как разметку
    alive = await upload(db_session, main_actor, project, name="alive.bin", data=big)
    gone = await upload(db_session, main_actor, project, name="gone.png")
    entry = await attach(db_session, task, task_actor, alive, gone)
    await service.delete_file(db_session, gone.id, actor=task_actor)
    await service.open_file(db_session, alive.id, actor=main_actor)
    before = {
        card.id: card
        for card in (
            await service.read_file(db_session, alive.id, actor=main_actor),
            await service.read_file(db_session, gone.id, actor=main_actor),
        )
    }
    archive = (await auth_client.get(ARCHIVE)).json()["data"]
    assert {"files", "file_contents", "entry_files"} <= {item["name"] for item in archive["tables"]}

    await wipe(db_session)
    target_ui, _ = await fresh_installation(db_session)
    response = await auth_client.post(ARCHIVE, json={"data": archive}, headers=bearer(target_ui))

    assert response.status_code == 200, response.text
    rows = {item["name"]: item["rows"] for item in response.json()["data"]["tables"]}
    assert (rows["files"], rows["file_contents"], rows["entry_files"]) == (2, 1, 2)
    for file_id, card in before.items():
        after = await service.read_file(db_session, file_id, actor=main_actor)
        assert after == card
    opened = await service.open_file(db_session, alive.id, actor=main_actor)
    assert opened.data == big
    assert hashlib.sha256(opened.data).hexdigest() == before[alive.id].sha256
    assert (await service.read_file(db_session, gone.id, actor=main_actor)).sha256 == gone.sha256
    with pytest.raises(FileDeletedError):
        await service.open_file(db_session, gone.id, actor=main_actor)
    shown = await service.entry_attachments(db_session, [entry])
    assert [(item.name, item.deleted) for item in shown[entry.id]] == [
        ("alive.bin", False),
        ("gone.png", True),
    ]
