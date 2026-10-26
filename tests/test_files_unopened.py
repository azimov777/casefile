"""Признак «изображение давно не открывали» и удаление отобранных (TRK-741, TRK~8#12).

Трекер признак только вычисляет при чтении; стирает человек или агент по отбору с
подтверждённым числом. Срок — настройка `file_unopened_days` (окружение
`TRACKER_FILE_UNOPENED_DAYS`, умолчание 90).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.file import File
from app.db.models.project import Project
from app.domain.errors import FileCountMismatchError, FileDeletedError
from app.domain.files import FileCard
from app.services import files as service
from app.services.auth import Actor
from test_files import upload

pytestmark = pytest.mark.usefixtures("auth_client")


async def aged(
    session: AsyncSession,
    actor: Actor,
    card: FileCard,
    *,
    added_days: int,
    opened_days: int | None = None,
) -> FileCard:
    """Сдвигает отметки файла назад; возвращает свежую карточку."""
    file = await session.get(File, card.id)
    assert file is not None
    now = datetime.now(UTC)
    file.created_at = now - timedelta(days=added_days)
    file.last_opened_at = None if opened_days is None else now - timedelta(days=opened_days)
    await session.flush()
    return await service.read_file(session, card.id, actor=actor)


async def test_an_image_gets_the_mark_by_the_term_and_a_document_never(
    db_session: AsyncSession, project: Project, main_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRACKER_FILE_UNOPENED_DAYS", raising=False)
    old = await upload(db_session, main_actor, project, name="old.png")
    young = await upload(db_session, main_actor, project, name="young.png")
    doc = await upload(db_session, main_actor, project, name="doc.pdf", mime_type="application/pdf")
    kept = await upload(db_session, main_actor, project, name="kept.png")
    assert (await aged(db_session, main_actor, old, added_days=91)).unopened is True
    assert (await aged(db_session, main_actor, young, added_days=89)).unopened is False
    assert (await aged(db_session, main_actor, doc, added_days=91)).unopened is False
    # Отсчёт от последнего открытия, а не от добавления.
    assert (
        await aged(db_session, main_actor, kept, added_days=300, opened_days=10)
    ).unopened is False

    picked = await service.list_files(db_session, actor=main_actor, unopened=True)
    assert [card.name for card in picked.items] == ["old.png"]
    everything = await service.list_files(db_session, actor=main_actor)
    assert len(everything.items) == 4  # трекер сам ничего не стёр и не спрятал
    assert not any(card.deleted for card in everything.items)


async def test_the_term_is_a_setting_and_a_change_moves_the_border(
    db_session: AsyncSession, project: Project, main_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = await upload(db_session, main_actor, project)
    assert (await aged(db_session, main_actor, card, added_days=31)).unopened is False
    monkeypatch.setenv("TRACKER_FILE_UNOPENED_DAYS", "30")
    assert (await service.read_file(db_session, card.id, actor=main_actor)).unopened is True
    monkeypatch.setenv("TRACKER_FILE_UNOPENED_DAYS", "40")
    assert (await service.read_file(db_session, card.id, actor=main_actor)).unopened is False


async def test_opening_resets_the_mark_and_a_tombstone_has_none(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    card = await upload(db_session, main_actor, project)
    assert (await aged(db_session, main_actor, card, added_days=200)).unopened is True
    opened = await service.open_file(db_session, card.id, actor=main_actor)
    assert opened.card.unopened is False
    await aged(db_session, main_actor, card, added_days=200)
    tombstone = await service.delete_file(db_session, card.id, actor=main_actor)
    assert tombstone.deleted and tombstone.unopened is False


async def test_deleting_the_picked_erases_bytes_and_wants_the_confirmed_count(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    old_a = await upload(db_session, main_actor, project, name="a.png")
    old_b = await upload(db_session, main_actor, project, name="b.png")
    young = await upload(db_session, main_actor, project, name="c.png")
    doc = await upload(db_session, main_actor, project, name="d.pdf", mime_type="application/pdf")
    await aged(db_session, main_actor, old_a, added_days=120)
    await aged(db_session, main_actor, old_b, added_days=95)
    await aged(db_session, main_actor, doc, added_days=500)

    with pytest.raises(FileCountMismatchError) as refused:
        await service.delete_matching(db_session, actor=main_actor, expected_count=3, unopened=True)
    assert refused.value.details == {"expected": 3, "actual": 2}
    listed = await service.list_files(db_session, actor=main_actor, include_deleted=True)
    assert not any(card.deleted for card in listed.items)  # отказ ничего не стёр

    deleted = await service.delete_matching(
        db_session, actor=main_actor, expected_count=2, unopened=True
    )
    assert {card.name for card in deleted} == {"a.png", "b.png"}
    assert all(card.deleted and card.deleted_by is not None for card in deleted)
    with pytest.raises(FileDeletedError):
        await service.open_file(db_session, old_a.id, actor=main_actor)
    for survivor in (young, doc):
        assert not (await service.read_file(db_session, survivor.id, actor=main_actor)).deleted


async def test_rest_filter_mark_and_delete_by_the_unopened_filter(
    client: AsyncClient, db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    old = await upload(db_session, main_actor, project, name="old.png")
    await upload(db_session, main_actor, project, name="new.png")
    await aged(db_session, main_actor, old, added_days=100)

    listed = (await client.get("/api/v1/files", params={"unopened": "true"})).json()["data"]
    assert [(c["name"], c["unopened"]) for c in listed] == [("old.png", True)]
    every: list[dict[str, Any]] = (await client.get("/api/v1/files")).json()["data"]
    assert {c["name"]: c["unopened"] for c in every} == {"old.png": True, "new.png": False}

    mismatch = await client.post(
        "/api/v1/files/delete", json={"expected_count": 2, "unopened": True}
    )
    assert (mismatch.status_code, mismatch.json()["error"]["code"]) == (409, "file_count_mismatch")
    done = await client.post("/api/v1/files/delete", json={"expected_count": 1, "unopened": True})
    assert (done.status_code, done.json()["data"]["deleted"]) == (200, 1)
    left = (await client.get("/api/v1/files")).json()["data"]
    assert [c["name"] for c in left] == ["new.png"]
