"""Перенос установки: выгрузка архива и приём в пустую установку (TRK-100, `docs/moving.md`).

Источник и приёмник здесь — одна тестовая база по очереди: установка наполняется,
выгружается, опустошается `TRUNCATE` (как свежая база другой машины), поднимается
сценариями подъёма (`ensure_local_token`, `ensure_agent_token` — как делает `install.sh`)
и принимает архив. Всё это в транзакции теста и откатывается после него.

Отказы, которые прерывают транзакцию на стороне Postgres (строка, которую не принял
`COPY`), зовут сценарий внутри боевой границы `transaction`: в REST её держит
`get_session`, а в тестах сессия подменена без границы, и прерванная транзакция
досталась бы следующему запросу теста.
"""

from typing import Any

import pytest
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import archive as store
from app.db.models.entry import Entry
from app.db.models.link import Link
from app.db.models.participant import Participant
from app.db.models.task import Task
from app.db.models.token import Token
from app.db.repositories import AccountRepository
from app.db.session import transaction
from app.domain.archive import EXCLUDED_TABLES, Archive, ArchiveFormat, ArchiveTable, copy_text
from app.domain.errors import ArchiveInvalidError
from app.domain.participants import ParticipantKind
from app.domain.passwords import hash_password
from app.domain.tokens import TokenScope
from app.services import archive as archive_service
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from app.services.setup import ensure_agent_token, ensure_local_token

ARCHIVE = "/api/v1/installation/archive"
PASSWORD = "correct horse battery staple"


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def count(session: AsyncSession, model: type[Any]) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def populate(client: AsyncClient) -> None:
    """Очередь, две задачи со связью, записи дела разных типов — через REST, как агент."""
    project = await client.post(
        "/api/v1/projects", json={"key": "TRK", "title": "Трекер", "description": "Бэкенд"}
    )
    assert project.status_code == 201, project.text
    for title in ("Первая", "Вторая"):
        created = await client.post(
            "/api/v1/tasks",
            json={"project": "TRK", "title": title, "description": "tab\there"},
        )
        assert created.status_code == 201, created.text
    for entry in (
        {"type": "decision", "title": "Выбран вариант", "body": "line\nbreak \\ backslash\r"},
        {"type": "finding", "title": "Факт", "body": ""},
    ):
        added = await client.post("/api/v1/tasks/TRK-1/entries", json=entry)
        assert added.status_code == 201, added.text
    linked = await client.post(
        "/api/v1/tasks/TRK-1/links", json={"kind": "blocks", "other": "TRK-2"}
    )
    assert linked.status_code == 201, linked.text


async def wipe(session: AsyncSession) -> None:
    """База другой машины: все таблицы данных пусты, схема та же."""
    tables = await store.table_columns(session, store.PUBLIC_SCHEMA)
    names = ", ".join(f'public."{name}"' for name in tables if name != store.VERSION_TABLE)
    await session.execute(text(f"TRUNCATE {names}"))
    session.expunge_all()


async def fresh_installation(session: AsyncSession) -> tuple[str, str]:
    """Пустая установка, поднятая как `install.sh`: секреты ключа интерфейса и агента."""
    ui = await ensure_local_token(session, known_secret=None)
    agent = await ensure_agent_token(session, known_secret=None)
    assert ui.secret is not None and agent.secret is not None
    return ui.secret, agent.secret


async def sign_in(client: AsyncClient, email: str, password: str) -> Any:
    return await client.post(
        "/api/v1/session",
        json={"email": email, "password": password},
        headers={"Authorization": ""},
    )


def as_archive(data: dict[str, Any]) -> Archive:
    return Archive(
        format=ArchiveFormat(data["format"]),
        format_version=data["format_version"],
        schema_revision=data["schema_revision"],
        app_version=data["app_version"],
        exported_at=data["exported_at"],
        tables=tuple(
            ArchiveTable(name=table["name"], columns=tuple(table["columns"]), rows=table["rows"])
            for table in data["tables"]
        ),
    )


def table(archive: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(item for item in archive["tables"] if item["name"] == name)
    return found


# --- Выгрузка ----------------------------------------------------------------------


async def test_the_export_carries_every_table_but_the_excluded_ones(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    await populate(auth_client)

    response = await auth_client.get(ARCHIVE)

    assert response.status_code == 200, response.text
    archive = response.json()["data"]
    assert archive["format"] == "casefile.installation-archive"
    assert archive["format_version"] == 1
    assert archive["schema_revision"] == store.head_revision()
    names = {item["name"] for item in archive["tables"]}
    present = set(await store.table_columns(db_session, store.PUBLIC_SCHEMA))
    assert names == present - set(EXCLUDED_TABLES)
    assert len(table(archive, "tasks")["rows"]) == 2
    assert len(table(archive, "links")["rows"]) == 1
    assert len(table(archive, "entries")["rows"]) == await count(db_session, Entry)


async def test_browser_sessions_stay_behind(
    auth_client: AsyncClient, db_session: AsyncSession, owner: Participant
) -> None:
    """Токен сеанса браузера не выгружается: кука принадлежит адресу источника."""
    account = await AccountRepository(db_session).get_by_participant(owner.id)
    assert account is not None
    account.password_hash = hash_password(PASSWORD, n=16, r=1, p=1).render()
    await db_session.flush()
    signed = await sign_in(auth_client, "owner@localhost", PASSWORD)
    assert signed.status_code == 200, signed.text
    sessions = await db_session.scalar(
        select(func.count()).select_from(Token).where(Token.expires_at.is_not(None))
    )
    assert sessions == 1

    archive = (await auth_client.get(ARCHIVE)).json()["data"]

    tokens = table(archive, "tokens")
    expires = tokens["columns"].index("expires_at")
    assert tokens["rows"]
    assert all(row[expires] is None for row in tokens["rows"])
    assert len(tokens["rows"]) == await count(db_session, Token) - 1


@pytest.mark.parametrize("scope", [TokenScope.TASK, TokenScope.MAIN])
async def test_only_an_administrator_exports_and_imports(
    client: AsyncClient, db_session: AsyncSession, scope: TokenScope
) -> None:
    """Агент с любым набором — нет: в архиве хеши паролей и токенов всех людей."""
    agent = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=agent, scope=scope, name="helper"
    )
    expected = "permission_denied" if scope is TokenScope.TASK else "admin_required"

    exported = await client.get(ARCHIVE, headers=bearer(issued.secret))
    imported = await client.post(ARCHIVE, json={"data": {}}, headers=bearer(issued.secret))

    assert exported.status_code == 403
    assert exported.json()["error"]["code"] == expected
    # Тело проверяется раньше прав — пустой архив отклонён формой, до сценария.
    assert imported.status_code == 422


# --- Приём -------------------------------------------------------------------------


async def test_a_fresh_installation_takes_the_archive_whole(
    auth_client: AsyncClient, db_session: AsyncSession, owner: Participant
) -> None:
    """Дела, авторы, время, люди и токены агентов переезжают; ключи машины — приёмника."""
    await populate(auth_client)
    account = await AccountRepository(db_session).get_by_participant(owner.id)
    assert account is not None
    account.password_hash = hash_password(PASSWORD, n=16, r=1, p=1).render()
    await db_session.flush()
    helper = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )
    personal = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=helper, scope=TokenScope.TASK, name="own"
    )
    source_ui, source_agent = await fresh_installation(db_session)
    signed = await sign_in(auth_client, "owner@localhost", PASSWORD)
    source_session = signed.json()["data"]["token"]
    auth_client.cookies.clear()
    before = (await auth_client.get("/api/v1/tasks/TRK-1")).json()["data"]
    entries_before = (await auth_client.get("/api/v1/tasks/TRK-1/entries")).json()["data"]
    max_seq = await db_session.scalar(select(func.max(Entry.seq)))
    archive = (await auth_client.get(ARCHIVE)).json()["data"]

    await wipe(db_session)
    target_ui, target_agent = await fresh_installation(db_session)
    response = await auth_client.post(ARCHIVE, json={"data": archive}, headers=bearer(target_ui))

    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["schema_revision"] == report["head_revision"] == store.head_revision()
    assert report["machine_keys"] == ["local-agent", "local-ui"]
    assert report["revoked_source_keys"] == 2
    assert report["replaced"] == {"participants": 2, "tokens": 2, "accounts": 1}
    rows = {item["name"]: item["rows"] for item in report["tables"]}
    assert rows["tasks"] == 2 and rows["links"] == 1
    assert (await count(db_session, Task), await count(db_session, Link)) == (2, 1)

    # Дело читается целиком, с прежними авторами и временем.
    ui = bearer(target_ui)
    assert (await auth_client.get("/api/v1/tasks/TRK-1", headers=ui)).json()["data"] == before
    entries_after = await auth_client.get("/api/v1/tasks/TRK-1/entries", headers=ui)
    assert entries_after.json()["data"] == entries_before

    # Доступы — ровно как записано в `docs/moving.md`.
    async def who(secret: str) -> Any:
        return await auth_client.get("/api/v1/bootstrap", headers=bearer(secret))

    assert (await who(target_ui)).json()["data"]["participant"]["name"] == "owner"
    assert (await who(target_agent)).json()["data"]["participant"]["name"] == "agent"
    assert (await who(personal.secret)).json()["data"]["participant"]["name"] == "helper"
    for gone in (source_ui, source_agent, source_session):
        assert (await who(gone)).status_code == 401
    signed_again = await sign_in(auth_client, "owner@localhost", PASSWORD)
    assert signed_again.status_code == 200, signed_again.text

    # Новая запись дела получает номер ленты после принятых, а не поверх них.
    added = await auth_client.post(
        "/api/v1/tasks/TRK-2/entries", json={"type": "note", "title": "После переезда"}, headers=ui
    )
    assert added.status_code == 201, added.text
    assert added.json()["data"]["seq"] > (max_seq or 0)
    # Временной схемы после приёма нет.
    left = await db_session.scalar(
        text("SELECT count(*) FROM pg_namespace WHERE nspname = :name"),
        {"name": store.SCRATCH_SCHEMA},
    )
    assert left == 0


async def test_an_installation_with_projects_refuses_the_archive(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    await populate(auth_client)
    archive = (await auth_client.get(ARCHIVE)).json()["data"]

    response = await auth_client.post(ARCHIVE, json={"data": archive})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "installation_not_empty"
    assert response.json()["error"]["details"] == {"projects": 1}
    assert await count(db_session, Task) == 2


async def test_an_archive_from_a_newer_casefile_is_refused(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Назад миграции не идут: ревизия, которой приёмник не знает, — отказ с названной ревизией."""
    archive = (await auth_client.get(ARCHIVE)).json()["data"]

    response = await auth_client.post(
        ARCHIVE, json={"data": {**archive, "schema_revision": "ffffffffffff"}}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "archive_revision_unknown"
    assert error["details"] == {"schema_revision": "ffffffffffff", "head": store.head_revision()}


#: Ревизия последнего выпуска v0.3 — последняя, где проект звался очередью.
#: Литерал, а не «ревизия перед head»: тест держит формат архивов, которые уже лежат у
#: людей, и следующая миграция не должна подменить его другим.
V0_3_REVISION = "7f4089f291b8"

#: Имена v0.3, которые ревизия `3b8e6d2f9a41` переименовала (`CONCEPT.md`, «Архив v0.3»).
#: Старое имя — как оно лежит в архиве, новое — как его читать из нынешней базы.
RENAMED_TABLES = {"queues": "projects"}
RENAMED_COLUMNS = {("tasks", "queue_id"): "project_id"}


async def archive_at(client: AsyncClient, session: AsyncSession, revision: str) -> dict[str, Any]:
    """Архив ревизии `revision` — таким, каким его снял бы тот Casefile.

    Таблицы и колонки — схемы той ревизии (её строит тот же `build_scratch`), строки — из
    наполненной базы на head. Имена, переименованные после той ревизии, читаются из базы
    нынешними, а в архив уходят прежними.
    """
    await store.build_scratch(session, revision)
    old_tables = await store.table_columns(session, store.SCRATCH_SCHEMA)
    await session.execute(text(f"DROP SCHEMA {store.SCRATCH_SCHEMA} CASCADE"))
    await session.execute(text("SET LOCAL search_path TO DEFAULT"))
    tables = []
    for name, columns in old_tables.items():
        if name in EXCLUDED_TABLES:
            continue
        current = [RENAMED_COLUMNS.get((name, column), column) for column in columns]
        rows = await store.read_rows(
            session, store.PUBLIC_SCHEMA, RENAMED_TABLES.get(name, name), current
        )
        if name == "entries" and "project_id" not in columns:
            # Записей дела проекта (TRK-156) до их ревизии не было: архив той версии их
            # не содержит, а в схеме той ревизии у записи без задачи нет владельца.
            owner = list(columns).index("task_id")
            rows = [row for row in rows if row[owner] is not None]
        tables.append({"name": name, "columns": list(columns), "rows": rows})
    return {
        **(await client.get(ARCHIVE)).json()["data"],
        "schema_revision": revision,
        "tables": tables,
    }


async def test_an_archive_of_an_older_revision_is_brought_up_to_head(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Архив ревизии до head принимается: миграции приёмника доводят его строки до своей схемы."""
    await populate(auth_client)
    script = ScriptDirectory.from_config(store._alembic_config())
    head = script.get_revision(store.head_revision())
    assert head is not None and isinstance(head.down_revision, str)
    previous = head.down_revision
    archive = await archive_at(auth_client, db_session, previous)

    await wipe(db_session)
    target_ui, _ = await fresh_installation(db_session)
    response = await auth_client.post(ARCHIVE, json={"data": archive}, headers=bearer(target_ui))

    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["schema_revision"] == previous
    assert report["head_revision"] == store.head_revision()
    assert await count(db_session, Task) == 2
    me = await auth_client.get("/api/v1/bootstrap", headers=bearer(target_ui))
    assert me.status_code == 200, me.text
    # Ключу интерфейса достаётся учётная запись администратора, как при подъёме.
    assert me.json()["data"]["account"]["is_admin"] is True


async def test_an_archive_of_v0_3_brings_its_queues_in_as_projects(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Архив v0.3 несёт таблицу `queues` и колонку `tasks.queue_id` — и принимается.

    Отличать старый формат отдельным кодом не нужно: архив называет свою ревизию,
    временная схема строится на ней, и строки доходят до `projects` той же миграцией,
    что переименовала таблицу у работающих установок.
    """
    await populate(auth_client)
    archive = await archive_at(auth_client, db_session, V0_3_REVISION)
    assert "queues" in {item["name"] for item in archive["tables"]}
    assert "projects" not in {item["name"] for item in archive["tables"]}
    assert "queue_id" in table(archive, "tasks")["columns"]

    await wipe(db_session)
    target_ui, _ = await fresh_installation(db_session)
    response = await auth_client.post(ARCHIVE, json={"data": archive}, headers=bearer(target_ui))

    assert response.status_code == 200, response.text
    assert "projects" in {item["name"] for item in response.json()["data"]["tables"]}
    task = await auth_client.get("/api/v1/tasks/TRK-2", headers=bearer(target_ui))
    assert task.status_code == 200, task.text
    assert task.json()["data"]["task"]["project"] == {
        "key": "TRK",
        "title": "Трекер",
        "description": "Бэкенд",
    }
    project = await auth_client.get("/api/v1/projects/TRK", headers=bearer(target_ui))
    assert project.status_code == 200, project.text
    assert project.json()["data"]["last_task_number"] == 2


async def test_a_long_queue_description_of_a_v0_3_archive_moves_into_the_project_case(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Описание очереди длиннее 320 знаков уезжает записью «Описание до v0.4.0» (TRK-158).

    Правило то же, что при обновлении живой установки (`CONCEPT.md`, 5.5): архив доходит
    до head теми же миграциями, и перенос делает ревизия `b7d2f94c0e15`. Длинное описание
    вписывается в архив руками — на head его уже не завести.
    """
    await populate(auth_client)
    archive = await archive_at(auth_client, db_session, V0_3_REVISION)
    queues = table(archive, "queues")
    column = queues["columns"].index("description")
    long = "Очередь бэкенда: код в app/, соглашения в docs/. " * 8
    assert len(long) > 320
    [row] = queues["rows"]
    row[column] = long

    await wipe(db_session)
    target_ui, _ = await fresh_installation(db_session)
    response = await auth_client.post(ARCHIVE, json={"data": archive}, headers=bearer(target_ui))
    assert response.status_code == 200, response.text

    project = await auth_client.get("/api/v1/projects/TRK", headers=bearer(target_ui))
    assert project.json()["data"]["description"] == ""
    entries = await auth_client.get("/api/v1/projects/TRK/entries", headers=bearer(target_ui))
    assert entries.status_code == 200, entries.text
    [note] = entries.json()["data"]
    assert (note["no"], note["type"], note["title"]) == (1, "note", "Описание до v0.4.0")
    assert note["body"] == long
    assert note["author"] == {"kind": "tracker", "signature": None}


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda data: data["tables"].pop(), "missing_table"),
        (
            lambda data: data["tables"].append({"name": "nope", "columns": ["id"], "rows": []}),
            "unknown_table",
        ),
        (lambda data: data["tables"][0]["columns"].__setitem__(0, "nope"), "column_mismatch"),
        (lambda data: data["tables"].append(dict(data["tables"][0])), "duplicate_table"),
    ],
)
async def test_a_malformed_archive_is_refused_whole(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    mutate: Any,
    reason: str,
) -> None:
    await populate(auth_client)
    archive = (await auth_client.get(ARCHIVE)).json()["data"]
    await wipe(db_session)
    await fresh_installation(db_session)
    await db_session.commit()
    mutate(archive)

    with pytest.raises(ArchiveInvalidError) as refused:
        async with transaction(db_session):
            await archive_service.import_installation(
                db_session, actor=TRACKER_ACTOR, archive=as_archive(archive)
            )

    assert refused.value.details["reason"] == reason
    assert await count(db_session, Task) == 0
    assert await count(db_session, Participant) == 2


async def test_a_value_postgres_rejects_leaves_the_installation_untouched(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    await populate(auth_client)
    archive = (await auth_client.get(ARCHIVE)).json()["data"]
    tasks = table(archive, "tasks")
    tasks["rows"][0][tasks["columns"].index("created_at")] = "not a time"
    await wipe(db_session)
    ui_secret, _ = await fresh_installation(db_session)
    await db_session.commit()

    with pytest.raises(ArchiveInvalidError) as refused:
        async with transaction(db_session):
            await archive_service.import_installation(
                db_session, actor=TRACKER_ACTOR, archive=as_archive(archive)
            )

    assert refused.value.details["reason"] == "rejected_row"
    assert refused.value.details["table"] == "tasks"
    assert await count(db_session, Task) == 0
    me = await auth_client.get("/api/v1/bootstrap", headers=bearer(ui_secret))
    assert me.status_code == 200


def test_copy_text_escapes_what_the_format_reads_as_markup() -> None:
    assert copy_text([["a\tb", None, "c\nd\\e\rf", ""]]) == b"a\\tb\t\\N\tc\\nd\\\\e\\rf\t\n"
