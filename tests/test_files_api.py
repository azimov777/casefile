"""REST файлов (TRK-736): загрузка, выдача байтов, карточка, список, замена, удаление
одного, выбранных и по отбору, вложения к записям задачи, проекта и обсуждения.

Правила файлов проверены в `tests/test_files.py` на сценариях; здесь — транспорт:
`multipart/form-data`, оболочка ответа, выдача байтов мимо неё, коды отказов.
"""

import hashlib
import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.session import transaction
from app.domain.errors import FileDeletedError
from app.services import discussions as discussions_service
from app.services import files as files_service
from app.services import projects as projects_service
from app.services.auth import Actor

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
PDF = b"%PDF-1.7\n" + b"0123456789" * 50 + b"\n%%EOF"

pytestmark = pytest.mark.usefixtures("auth_client")


async def upload(
    client: AsyncClient,
    data: bytes = PNG,
    *,
    name: str = "scheme.png",
    mime: str = "image/png",
    project: str = "TRK",
    **headers: str,
) -> Response:
    return await client.post(
        "/api/v1/files",
        data={"project": project},
        files={"file": (name, data, mime)},
        headers=headers,
    )


async def uploaded(client: AsyncClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
    response = await upload(client, *args, **kwargs)
    assert response.status_code == 201, response.text
    card: dict[str, Any] = response.json()["data"]
    return card


async def test_upload_returns_a_card_in_the_envelope(client: AsyncClient, project: Project) -> None:
    response = await upload(client)

    assert response.status_code == 201
    card = response.json()["data"]
    assert card["project_key"] == "TRK"
    assert card["name"] == "scheme.png"
    assert card["mime_type"] == "image/png"
    assert card["size_bytes"] == len(PNG)
    assert card["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert card["deleted"] is False
    assert card["added_by"]["signature"] == "owner"
    assert (card["entries"], card["tasks"]) == (0, 0)
    assert card["last_opened_at"] is None


async def test_the_name_field_overrides_the_part_filename(
    client: AsyncClient, project: Project
) -> None:
    response = await client.post(
        "/api/v1/files",
        data={"project": "trk", "name": "renamed.png"},
        files={"file": ("scheme.png", PNG, "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["name"] == "renamed.png"


async def test_download_returns_the_same_bytes_without_the_envelope(
    client: AsyncClient, project: Project
) -> None:
    card = await uploaded(client, name="схема.png")

    response = await client.get(f"/api/v1/files/{card['id']}/content")

    assert response.status_code == 200
    assert response.content == PNG
    assert hashlib.sha256(response.content).hexdigest() == card["sha256"]
    assert response.headers["content-type"] == "image/png"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''%D1%81%D1%85%D0%B5%D0%BC%D0%B0.png" in disposition
    assert response.headers["x-content-type-options"] == "nosniff"
    opened = (await client.get(f"/api/v1/files/{card['id']}")).json()["data"]
    assert opened["last_opened_at"] is not None


async def test_reading_the_card_does_not_count_as_opening(
    client: AsyncClient, project: Project
) -> None:
    card = await uploaded(client)

    again = (await client.get(f"/api/v1/files/{card['id']}")).json()["data"]

    assert again["last_opened_at"] is None


async def test_upload_refuses_a_file_over_the_limit_and_stores_nothing(
    client: AsyncClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "file_max_bytes", 100)

    response = await upload(client, b"x" * 101)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert error["details"] == {"size": 101, "max_bytes": 100}
    listing = (await client.get("/api/v1/files")).json()
    assert listing["data"] == []
    # Ровно на пределе — проходит.
    assert (await upload(client, b"x" * 100)).status_code == 201


async def test_upload_refuses_an_archived_project(
    client: AsyncClient, db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")

    response = await upload(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_archived"


async def test_upload_refuses_an_unknown_project_and_a_bad_name(
    client: AsyncClient, project: Project
) -> None:
    unknown = await upload(client, project="NOPE")
    bad_name = await upload(client, name="a/b.png")
    bad_type = await client.post(
        "/api/v1/files",
        data={"project": "TRK"},
        files={"file": ("x.png", PNG, "not a type")},
    )

    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "project_not_found")
    assert (bad_name.status_code, bad_name.json()["error"]["code"]) == (422, "file_fields_invalid")
    assert (bad_type.status_code, bad_type.json()["error"]["code"]) == (422, "file_fields_invalid")


async def test_upload_without_the_file_part_is_a_validation_error(
    client: AsyncClient, project: Project
) -> None:
    response = await client.post("/api/v1/files", data={"project": "TRK"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_upload_is_idempotent(client: AsyncClient, project: Project) -> None:
    key = {"Idempotency-Key": str(uuid.uuid4())}

    first = await upload(client, **key)
    second = await upload(client, **key)
    other = await upload(client, PDF, name="a.pdf", mime="application/pdf", **key)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "idempotency_key_reused"
    assert len((await client.get("/api/v1/files")).json()["data"]) == 1


async def test_unknown_and_deleted_files(client: AsyncClient, project: Project) -> None:
    missing = str(uuid.uuid4())
    for method, path in (
        ("GET", f"/api/v1/files/{missing}"),
        ("GET", f"/api/v1/files/{missing}/content"),
        ("DELETE", f"/api/v1/files/{missing}"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "file_not_found"
    replace = await client.put(
        f"/api/v1/files/{missing}/content", files={"file": ("x.png", PNG, "image/png")}
    )
    assert replace.status_code == 404

    card = await uploaded(client)
    assert (await client.delete(f"/api/v1/files/{card['id']}")).status_code == 200
    for method, path in (
        ("GET", f"/api/v1/files/{card['id']}/content"),
        ("DELETE", f"/api/v1/files/{card['id']}"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 409, (method, path)
        assert response.json()["error"]["code"] == "file_deleted"
    replace = await client.put(
        f"/api/v1/files/{card['id']}/content", files={"file": ("x.png", PNG, "image/png")}
    )
    assert replace.status_code == 409
    assert replace.json()["error"]["code"] == "file_deleted"


async def test_replace_keeps_the_reference_and_changes_the_content(
    client: AsyncClient, project: Project
) -> None:
    card = await uploaded(client)

    response = await client.put(
        f"/api/v1/files/{card['id']}/content",
        data={"name": "contract.pdf"},
        files={"file": ("ignored.bin", PDF, "application/pdf")},
    )

    assert response.status_code == 200
    replaced = response.json()["data"]
    assert replaced["id"] == card["id"]
    assert replaced["name"] == "contract.pdf"
    assert replaced["mime_type"] == "application/pdf"
    assert replaced["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert replaced["replaced_by"]["signature"] == "owner"
    assert replaced["replaced_at"] is not None
    served = await client.get(f"/api/v1/files/{card['id']}/content")
    assert served.content == PDF


async def test_replace_refuses_over_the_limit_and_an_archived_project(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    main_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = await uploaded(client)
    monkeypatch.setattr(get_settings(), "file_max_bytes", 100)

    big = await client.put(
        f"/api/v1/files/{card['id']}/content", files={"file": ("x.png", b"x" * 500, "image/png")}
    )
    assert (big.status_code, big.json()["error"]["code"]) == (422, "file_too_large")
    assert (await client.get(f"/api/v1/files/{card['id']}/content")).content == PNG

    monkeypatch.undo()
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")
    frozen = await client.put(
        f"/api/v1/files/{card['id']}/content", files={"file": ("x.png", PNG, "image/png")}
    )
    assert (frozen.status_code, frozen.json()["error"]["code"]) == (409, "project_archived")
    # Чтение и выдача архивному проекту не помеха.
    assert (await client.get(f"/api/v1/files/{card['id']}/content")).content == PNG


async def test_delete_leaves_a_tombstone(client: AsyncClient, project: Project) -> None:
    card = await uploaded(client)

    response = await client.delete(f"/api/v1/files/{card['id']}")

    assert response.status_code == 200
    tombstone = response.json()["data"]
    assert tombstone["deleted"] is True
    assert tombstone["deleted_by"]["signature"] == "owner"
    assert tombstone["name"] == card["name"]
    assert tombstone["sha256"] == card["sha256"]
    after = (await client.get(f"/api/v1/files/{card['id']}")).json()["data"]
    assert after["deleted"] is True
    assert after["size_bytes"] == card["size_bytes"]


async def test_delete_refuses_an_archived_project(
    client: AsyncClient, db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    card = await uploaded(client)
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")

    response = await client.delete(f"/api/v1/files/{card['id']}")

    assert (response.status_code, response.json()["error"]["code"]) == (409, "project_archived")


async def test_list_searches_filters_and_sorts(client: AsyncClient, project: Project) -> None:
    small = await uploaded(client, b"abc", name="Notes.txt", mime="text/plain")
    medium = await uploaded(client, PDF, name="contract.pdf", mime="application/pdf")
    big = await uploaded(client, PNG, name="scheme.png")

    async def names(**params: Any) -> list[str]:
        response = await client.get("/api/v1/files", params=params)
        assert response.status_code == 200
        return [card["name"] for card in response.json()["data"]]

    # Все три файла загружены в одной транзакции теста: `created_at` у них одно, и порядок
    # «по добавлению» между ними не проверяется — только состав.
    assert sorted(await names()) == ["Notes.txt", "contract.pdf", "scheme.png"]
    assert await names(sort="size") == ["scheme.png", "contract.pdf", "Notes.txt"]
    assert await names(sort="size", descending="false") == [
        "Notes.txt",
        "contract.pdf",
        "scheme.png",
    ]
    assert await names(sort="type", descending="false") == [
        "contract.pdf",
        "scheme.png",
        "Notes.txt",
    ]
    assert await names(q="NOTES") == ["Notes.txt"]
    assert await names(mime_type="image") == ["scheme.png"]
    assert await names(mime_type="application/pdf") == ["contract.pdf"]
    assert sorted(await names(project="TRK", sort="added", descending="false")) == [
        "Notes.txt",
        "contract.pdf",
        "scheme.png",
    ]
    assert {small["size_bytes"], medium["size_bytes"], big["size_bytes"]} == {
        3,
        len(PDF),
        len(PNG),
    }
    # Открытие сдвигает файл в сортировке «по последнему открытию».
    await client.get(f"/api/v1/files/{small['id']}/content")
    assert (await names(sort="opened"))[0] == "Notes.txt"


async def test_list_pages_by_cursor_and_hides_tombstones(
    client: AsyncClient, project: Project
) -> None:
    cards = [await uploaded(client, bytes([i]) * (i + 1), name=f"f{i}.bin") for i in range(5)]
    await client.delete(f"/api/v1/files/{cards[0]['id']}")

    first = (await client.get("/api/v1/files", params={"limit": 2, "sort": "size"})).json()
    second = (
        await client.get(
            "/api/v1/files",
            params={"limit": 2, "sort": "size", "cursor": first["meta"]["next_cursor"]},
        )
    ).json()
    with_deleted = (await client.get("/api/v1/files", params={"include_deleted": "true"})).json()

    assert [c["name"] for c in first["data"]] == ["f4.bin", "f3.bin"]
    assert first["meta"]["has_more"] is True
    assert [c["name"] for c in second["data"]] == ["f2.bin", "f1.bin"]
    assert second["meta"]["has_more"] is False
    assert len(with_deleted["data"]) == 5


async def test_list_hides_archived_projects_unless_named(
    client: AsyncClient, db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    await uploaded(client)
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OLD", title="Старый", description="Старый проект"
    )
    await uploaded(client, name="old.png", project="OLD")
    await projects_service.archive_project(db_session, other, actor=main_actor, reason="Архив")

    everything = (await client.get("/api/v1/files")).json()["data"]
    named = (await client.get("/api/v1/files", params={"project": "OLD"})).json()["data"]

    assert [c["name"] for c in everything] == ["scheme.png"]
    assert [c["name"] for c in named] == ["old.png"]


async def test_list_rejects_an_unknown_parameter_and_a_bad_sort(
    client: AsyncClient, project: Project
) -> None:
    assert (await client.get("/api/v1/files", params={"colour": "red"})).status_code == 422
    assert (await client.get("/api/v1/files", params={"sort": "beauty"})).status_code == 422


async def test_delete_selected_removes_all_or_none(client: AsyncClient, project: Project) -> None:
    one = await uploaded(client, name="one.png")
    two = await uploaded(client, name="two.png")
    gone = await uploaded(client, name="gone.png")
    await client.delete(f"/api/v1/files/{gone['id']}")

    refused = await client.post("/api/v1/files/delete", json={"ids": [gone["id"], one["id"]]})
    unknown = await client.post(
        "/api/v1/files/delete", json={"ids": [str(uuid.uuid4()), two["id"]]}
    )
    done = await client.post(
        "/api/v1/files/delete", json={"ids": [one["id"], two["id"], one["id"]]}
    )

    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "file_deleted")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "file_not_found")
    assert done.status_code == 200
    body = done.json()["data"]
    assert body["deleted"] == 2
    assert [c["name"] for c in body["files"]] == ["one.png", "two.png"]
    assert all(c["deleted"] for c in body["files"])


async def test_a_refused_bulk_delete_leaves_no_tombstones(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Границу транзакции HTTP-тест подменяет сессией теста без отката, поэтому атомарность
    проверена на боевой границе (`transaction`): отказ на втором файле откатывает первый."""
    first = await files_service.upload_file(
        db_session, actor=main_actor, project="TRK", name="a.png", data=PNG, mime_type="image/png"
    )
    second = await files_service.upload_file(
        db_session, actor=main_actor, project="TRK", name="b.png", data=PNG, mime_type="image/png"
    )
    await files_service.delete_file(db_session, second.id, actor=main_actor)
    await db_session.commit()

    with pytest.raises(FileDeletedError):
        async with transaction(db_session):
            await files_service.delete_files(db_session, [first.id, second.id], actor=main_actor)

    assert not (await files_service.read_file(db_session, first.id, actor=main_actor)).deleted


async def test_delete_by_filter_needs_the_confirmed_count(
    client: AsyncClient, project: Project
) -> None:
    for index in range(3):
        await uploaded(client, name=f"shot{index}.png")
    doc = await uploaded(client, PDF, name="doc.pdf", mime="application/pdf")

    mismatch = await client.post(
        "/api/v1/files/delete", json={"expected_count": 2, "mime_type": "image"}
    )
    assert (mismatch.status_code, mismatch.json()["error"]["code"]) == (409, "file_count_mismatch")
    assert mismatch.json()["error"]["details"] == {"expected": 2, "actual": 3}
    assert len((await client.get("/api/v1/files")).json()["data"]) == 4  # ничего не удалено

    done = await client.post(
        "/api/v1/files/delete", json={"expected_count": 3, "mime_type": "image"}
    )
    assert done.status_code == 200
    assert done.json()["data"]["deleted"] == 3
    remaining = (await client.get("/api/v1/files")).json()["data"]
    assert [c["id"] for c in remaining] == [doc["id"]]


async def test_delete_all_with_an_empty_filter(client: AsyncClient, project: Project) -> None:
    await uploaded(client, name="a.png")
    await uploaded(client, PDF, name="b.pdf", mime="application/pdf")

    wrong = await client.post("/api/v1/files/delete", json={"expected_count": 0})
    done = await client.post("/api/v1/files/delete", json={"expected_count": 2})

    assert wrong.status_code == 409
    assert done.json()["data"]["deleted"] == 2
    assert (await client.get("/api/v1/files")).json()["data"] == []


async def test_delete_body_must_choose_one_way(client: AsyncClient, project: Project) -> None:
    card = await uploaded(client)
    for body in (
        {},
        {"ids": []},
        {"ids": [card["id"]], "expected_count": 1},
        {"ids": [card["id"]], "q": "x"},
        {"ids": ["not-an-id"]},
    ):
        response = await client.post("/api/v1/files/delete", json=body)
        assert response.status_code == 422, body


async def test_delete_by_filter_refuses_a_named_archived_project(
    client: AsyncClient, db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    await uploaded(client)
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Архив")

    response = await client.post(
        "/api/v1/files/delete", json={"expected_count": 1, "project": "TRK"}
    )

    assert (response.status_code, response.json()["error"]["code"]) == (409, "project_archived")
    # Без названного проекта файлы архивных проектов в отбор не входят: число 0.
    empty = await client.post("/api/v1/files/delete", json={"expected_count": 0})
    assert empty.status_code == 200


# --- Вложения -------------------------------------------------------------------------


async def test_a_task_entry_attaches_files_and_every_read_carries_the_cards(
    client: AsyncClient, project: Project, task: Task
) -> None:
    png = await uploaded(client)
    pdf = await uploaded(client, PDF, name="a.pdf", mime="application/pdf")

    created = await client.post(
        f"/api/v1/tasks/{task.key}/entries",
        json={"type": "note", "title": "Схема", "files": [pdf["id"], png["id"]]},
    )

    assert created.status_code == 201, created.text
    entry = created.json()["data"]
    assert [f["name"] for f in entry["files"]] == ["a.pdf", "scheme.png"]
    assert entry["files"][0]["entries"] == 1
    assert entry["files"][0]["tasks"] == 1
    listed = (await client.get(f"/api/v1/tasks/{task.key}/entries")).json()["data"]
    one = (await client.get(f"/api/v1/tasks/{task.key}/entries/{entry['no']}")).json()["data"]
    journal = (await client.get("/api/v1/journal", params={"types": "note"})).json()["data"]
    assert [f["id"] for f in one["files"]] == [pdf["id"], png["id"]]
    assert [f["id"] for f in next(e for e in listed if e["no"] == entry["no"])["files"]] == [
        pdf["id"],
        png["id"],
    ]
    assert [f["id"] for f in next(e for e in journal if e["no"] == entry["no"])["files"]] == [
        pdf["id"],
        png["id"],
    ]
    # Запись без вложений несёт пустой список.
    plain = await client.post(
        f"/api/v1/tasks/{task.key}/entries", json={"type": "note", "title": "Без файлов"}
    )
    assert plain.json()["data"]["files"] == []


async def test_entries_show_the_current_content_and_the_tombstone(
    client: AsyncClient, project: Project, task: Task
) -> None:
    card = await uploaded(client)
    entry = (
        await client.post(
            f"/api/v1/tasks/{task.key}/entries",
            json={"type": "note", "title": "Схема", "files": [card["id"]]},
        )
    ).json()["data"]
    await client.put(
        f"/api/v1/files/{card['id']}/content",
        data={"name": "n.pdf"},
        files={"file": ("n.pdf", PDF, "application/pdf")},
    )

    replaced = (await client.get(f"/api/v1/tasks/{task.key}/entries/{entry['no']}")).json()["data"]
    await client.delete(f"/api/v1/files/{card['id']}")
    deleted = (await client.get(f"/api/v1/tasks/{task.key}/entries/{entry['no']}")).json()["data"]

    assert replaced["files"][0]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert deleted["files"][0]["deleted"] is True
    assert deleted["files"][0]["name"] == "n.pdf"


async def test_attaching_refuses_unknown_deleted_and_too_many_files(
    client: AsyncClient, project: Project, task: Task
) -> None:
    card = await uploaded(client)
    await client.delete(f"/api/v1/files/{card['id']}")
    path = f"/api/v1/tasks/{task.key}/entries"

    unknown = await client.post(
        path, json={"type": "note", "title": "x", "files": [str(uuid.uuid4())]}
    )
    deleted = await client.post(path, json={"type": "note", "title": "x", "files": [card["id"]]})
    many = await client.post(
        path, json={"type": "note", "title": "x", "files": [str(uuid.uuid4()) for _ in range(11)]}
    )
    repeated = await client.post(
        path, json={"type": "note", "title": "x", "files": [card["id"], card["id"]]}
    )

    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "file_not_found")
    assert (deleted.status_code, deleted.json()["error"]["code"]) == (409, "file_deleted")
    assert many.status_code == 422
    assert (repeated.status_code, repeated.json()["error"]["code"]) == (
        422,
        "entry_fields_invalid",
    )
    listed = (await client.get(path)).json()["data"]
    assert all(entry["title"] != "x" for entry in listed)


async def test_project_and_discussion_entries_attach_files(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    task: Task,
    main_actor: Actor,
) -> None:
    card = await uploaded(client)
    discussion = await discussions_service.create_discussion(
        db_session,
        actor=main_actor,
        project=project,
        title="Вопрос",
        opening="note",
        body="",
        refs=[],
        tasks=[],
    )

    in_project = await client.post(
        "/api/v1/projects/TRK/entries",
        json={"type": "note", "title": "Файл приложен", "files": [card["id"]]},
    )
    in_discussion = await client.post(
        f"/api/v1/discussions/{discussion.address}/entries",
        json={"type": "note", "title": "Файл приложен", "files": [card["id"]]},
    )
    listed_project = (await client.get("/api/v1/projects/TRK/entries")).json()["data"]
    listed_discussion = (
        await client.get(f"/api/v1/discussions/{discussion.address}/entries")
    ).json()["data"]
    one_project = (
        await client.get(f"/api/v1/projects/TRK/entries/{in_project.json()['data']['no']}")
    ).json()["data"]

    assert in_project.status_code == in_discussion.status_code == 201
    assert in_project.json()["data"]["files"][0]["id"] == card["id"]
    assert in_discussion.json()["data"]["files"][0]["id"] == card["id"]
    assert any(e["files"] for e in listed_project)
    assert any(e["files"] for e in listed_discussion)
    assert one_project["files"][0]["id"] == card["id"]
    reference = (await client.get(f"/api/v1/files/{card['id']}")).json()["data"]
    assert reference["entries"] == 2
    assert reference["tasks"] == 0


async def test_a_remark_with_a_file_shows_it_in_the_remarks_list_and_the_task(
    client: AsyncClient, project: Project, task: Task
) -> None:
    card = await uploaded(client)
    remark = await client.post(
        f"/api/v1/tasks/{task.key}/entries",
        json={"type": "remark", "title": "Скриншот", "files": [card["id"]]},
    )
    assert remark.status_code == 201, remark.text

    listed = (await client.get("/api/v1/remarks")).json()["data"]
    package = (await client.get(f"/api/v1/tasks/{task.key}")).json()["data"]

    assert [f["id"] for f in listed[0]["files"]] == [card["id"]]
    assert [f["id"] for f in package["remarks"][0]["files"]] == [card["id"]]
