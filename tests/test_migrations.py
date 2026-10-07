"""Миграции на данных: снятие статуса `review` (TRK-4).

Схему проверяют все остальные тесты — они идут на базе, накатанной миграциями. Здесь
проверяется то, чего не видно на пустой базе: **перенос строк**. Задача, стоявшая в
`review`, обязана оказаться в `in_progress`, а её дело — объяснять, почему статус
скакнул: без записи преемник читал бы задачу в работе с готовым выходом и не понимал бы,
куда делся обзор.

## Почему база своя

Общая тестовая база фикстур стоит на `head` весь прогон. Откатить её на одну ревизию
посреди набора значило бы уронить соседние тесты, которые в это время ходят в те же
таблицы. Поэтому здесь заводится отдельная база, накатывается до ревизии **перед**
миграцией, наполняется руками и доводится до `head`.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import UnauthorizedError
from app.domain.tokens import hash_token
from app.services.auth import authenticate
from conftest import _to_asyncpg_dsn, alembic_config

#: Ревизия, снимающая статус, и ревизия перед ней. Идентификаторы записаны литералами:
#: тест проверяет конкретную миграцию, и «предпоследняя ревизия» подставила бы завтра
#: другую.
REVISION = "f3b90c47ad15"
PREVIOUS_REVISION = "d4a7c1e93f28"


async def _recreate_database(url: str) -> None:
    """Сносит базу теста и создаёт заново: прогон начинается с чистого листа."""
    dsn = _to_asyncpg_dsn(url)
    server_dsn, _, database = dsn.rpartition("/")
    connection = await asyncpg.connect(f"{server_dsn}/postgres")
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


def _migrate(url: str, revision: str, *, down: bool = False) -> None:
    """Один шаг Alembic. Синхронная: внутри он поднимает свой цикл событий."""
    config = alembic_config(url)
    if down:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def migrate(url: str, revision: str, *, down: bool = False) -> None:
    # В отдельном потоке: в текущем уже крутится цикл событий pytest-asyncio, а Alembic
    # зовёт `asyncio.run`.
    await asyncio.to_thread(_migrate, url, revision, down=down)


@pytest.fixture
async def migration_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Своя база на ревизии перед снятием статуса."""
    url = f"{test_database_url}_migrations"
    await _recreate_database(url)
    await migrate(url, PREVIOUS_REVISION)

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_task_in_review(engine: AsyncEngine) -> None:
    """Очередь и задача в `review` с одной записью дела — состояние старой установки."""
    async with engine.begin() as connection:
        queue_id = await connection.scalar(
            text(
                "INSERT INTO queues (key, title, created_by_kind, created_by_signature) "
                "VALUES ('OLD', 'Старая очередь', 'agent', 'claude') RETURNING id"
            )
        )
        task_id = await connection.scalar(
            text(
                "INSERT INTO tasks (key, queue_id, title, description, status, "
                "created_by_kind, created_by_signature) "
                "VALUES ('OLD-1', :queue_id, 'Задача на обзоре', 'Выход готов', 'review', "
                "'agent', 'claude') RETURNING id"
            ),
            {"queue_id": queue_id},
        )
        await connection.execute(
            text(
                "INSERT INTO entries (task_id, no, type, title, payload, "
                "created_by_kind, created_by_signature) VALUES "
                "(:task_id, 1, 'created', 'Task created', '{}'::jsonb, 'agent', 'claude'), "
                "(:task_id, 2, 'status_changed', 'Status changed: in_progress -> review', "
                """'{"from": "in_progress", "to": "review", "reason": null}'::jsonb, """
                "'agent', 'claude')"
            ),
            {"task_id": task_id},
        )


async def test_a_task_in_review_moves_into_in_progress_and_the_case_says_why(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 4: перенос строк и запись, объясняющая скачок статуса."""
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)

    await migrate(url, "head")

    async with migration_engine.connect() as connection:
        status = await connection.scalar(text("SELECT status FROM tasks WHERE key = 'OLD-1'"))
        version = await connection.scalar(text("SELECT version FROM tasks WHERE key = 'OLD-1'"))
        row = (
            await connection.execute(
                text(
                    "SELECT no, payload, created_by_kind, created_by_signature FROM entries "
                    "WHERE task_id = (SELECT id FROM tasks WHERE key = 'OLD-1') "
                    "ORDER BY no DESC LIMIT 1"
                )
            )
        ).one()

    assert status == "in_progress"
    # Версия выросла: копия карточки у клиента после такой правки устарела.
    assert version == 2
    assert row.no == 3, "запись подшита следующим номером, не поверх чужого"
    assert row.created_by_kind == "tracker"
    assert row.created_by_signature is None, "трекер подписи не ставит (`CONCEPT.md`, 3.1)"
    assert row.payload["from"] == "review"
    assert row.payload["to"] == "in_progress"
    assert row.payload["reason"], "скачок статуса обязан быть объяснён"


async def test_the_old_entries_keep_review_in_their_payload(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Журнал не переписывается: старые записи о переходах остаются как есть.

    Правило дела важнее удобства чтения: запись неизменяема, и миграция, которая
    подчистила бы историю «ради консистентности», соврала бы о том, что было.
    """
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)

    await migrate(url, "head")

    async with migration_engine.connect() as connection:
        old = await connection.scalar(
            text("SELECT count(*) FROM entries WHERE payload->>'to' = 'review'")
        )

    assert old == 1


async def test_the_status_constraint_stops_accepting_review(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Значение снято на уровне схемы, а не только в коде."""
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)

    await migrate(url, "head")

    with pytest.raises(Exception, match="ck_tasks_task_status"):
        async with migration_engine.begin() as connection:
            await connection.execute(text("UPDATE tasks SET status = 'review' WHERE key = 'OLD-1'"))


async def test_the_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 4: `downgrade -1` и повторный `upgrade head` проходят.

    Данные назад не переводятся намеренно (см. докстринг `downgrade`), поэтому после
    отката задача остаётся в `in_progress`: проверяется здесь именно то, что схема
    ходит в обе стороны, а не то, что откат отменяет перенос.
    """
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)
    # До своей ревизии, а не до `head`: тест проверяет конкретную миграцию, и каждая
    # новая ревизия сверху делала бы `-1` шагом не туда. Раньше здесь стояло `head`,
    # и первая же следующая миграция это и вскрыла.
    await migrate(url, REVISION)

    await migrate(url, "-1", down=True)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        status = await connection.scalar(text("SELECT status FROM tasks WHERE key = 'OLD-1'"))
    assert revision == PREVIOUS_REVISION
    assert status == "in_progress"

    await migrate(url, REVISION)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == REVISION


# --- Тип записи `field_changed` -------------------------------------------------------

#: Ревизия, заводящая тип записи об изменении обвязки, и ревизия перед ней.
FIELD_CHANGED_REVISION = "a1c8f2d47b06"
FIELD_CHANGED_PREVIOUS = "f3b90c47ad15"


async def test_the_new_entry_type_is_refused_before_its_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """До миграции запись такого типа не проходит: список типов закреплён схемой.

    Это и есть довод за проверку в базе рядом с проверкой в коде: тип, забытый в
    миграции, скажет о себе отказом на вставке, а не тихо ляжет в дело.
    """
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)
    await migrate(url, FIELD_CHANGED_PREVIOUS)

    with pytest.raises(Exception, match="ck_entries_entry_type"):
        async with migration_engine.begin() as connection:
            await connection.execute(text(_INSERT_FIELD_CHANGED))


async def test_the_new_entry_type_passes_after_its_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """После миграции запись такого типа проходит."""
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)
    await migrate(url, FIELD_CHANGED_REVISION)

    async with migration_engine.begin() as connection:
        await connection.execute(text(_INSERT_FIELD_CHANGED))

    async with migration_engine.connect() as connection:
        filed = await connection.scalar(
            text("SELECT count(*) FROM entries WHERE type = 'field_changed'")
        )
    assert filed == 1


async def test_the_new_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Схема ходит в обе стороны, пока записей нового типа ещё нет.

    Записи здесь и не подшиваются: удалить их потом нельзя — дело неизменяемо на уровне
    триггера, — а откат с ними отказывается намеренно (проверяется соседним тестом).
    """
    url = f"{test_database_url}_migrations"
    await migrate(url, FIELD_CHANGED_REVISION)

    await migrate(url, "-1", down=True)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == FIELD_CHANGED_PREVIOUS

    await migrate(url, FIELD_CHANGED_REVISION)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == FIELD_CHANGED_REVISION


async def test_the_rollback_refuses_while_such_entries_exist(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат отказывается, пока такие записи подшиты, — и это верное поведение.

    Молча снести их нельзя: дело неизменяемо, и откат схемы историю не отменяет
    (`CONCEPT.md`, 3.4). Отказ говорит «откатывать уже поздно», а не ломает установку;
    альтернатива — потерять записи — хуже во всех отношениях.
    """
    url = f"{test_database_url}_migrations"
    await _seed_task_in_review(migration_engine)
    await migrate(url, FIELD_CHANGED_REVISION)

    async with migration_engine.begin() as connection:
        await connection.execute(text(_INSERT_FIELD_CHANGED))

    with pytest.raises(Exception, match="ck_entries_entry_type"):
        await migrate(url, "-1", down=True)


_INSERT_FIELD_CHANGED = """
INSERT INTO entries (
    task_id, no, type, title, body, payload, refs, created_by_kind, created_by_signature
)
SELECT
    tasks.id,
    COALESCE((SELECT MAX(entries.no) FROM entries WHERE entries.task_id = tasks.id), 0) + 1,
    'field_changed',
    'Field changed: priority',
    '',
    jsonb_build_object('field', 'priority', 'before', 'normal', 'after', 'high'),
    '[]'::jsonb,
    'tracker',
    NULL
FROM tasks
WHERE tasks.key = 'OLD-1'
"""


# --- Очередь становится проектом (TRK-152) -------------------------------------------

#: Ревизия, переименовавшая очередь в проект, и ревизия перед ней — последняя v0.3.
PROJECTS_REVISION = "3b8e6d2f9a41"
PROJECTS_PREVIOUS = "7f4089f291b8"


async def _seed_queues(engine: AsyncEngine) -> None:
    """Две очереди с задачами и дырой в нумерации — установка v0.3 с историей."""
    async with engine.begin() as connection:
        for key, last in (("OLD", 3), ("NEW", 1)):
            queue_id = await connection.scalar(
                text(
                    "INSERT INTO queues (key, title, last_task_number, created_by_kind, "
                    "created_by_signature) VALUES (:key, :key, :last, 'agent', 'claude') "
                    "RETURNING id"
                ),
                {"key": key, "last": last},
            )
            # У OLD номер 2 сгорел на откаченной транзакции: счётчик больше числа задач.
            for number in (1, 3) if key == "OLD" else (1,):
                await connection.execute(
                    text(
                        "INSERT INTO tasks (key, queue_id, title, description, "
                        "created_by_kind, created_by_signature) "
                        "VALUES (:task_key, :queue_id, 'Задача', 'Описание', 'agent', 'claude')"
                    ),
                    {"task_key": f"{key}-{number}", "queue_id": queue_id},
                )


async def _projects_state(engine: AsyncEngine, table: str, column: str) -> list[tuple]:
    """Ключ задачи, ключ её проекта и счётчик проекта — по порядку ключей."""
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                f"SELECT tasks.key, {table}.key, {table}.last_task_number FROM tasks "
                f"JOIN {table} ON {table}.id = tasks.{column} ORDER BY tasks.key"
            )
        )
        return [tuple(row) for row in rows]


async def test_queues_become_projects_with_the_same_keys_and_counters(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, PROJECTS_PREVIOUS)
    await _seed_queues(migration_engine)
    before = await _projects_state(migration_engine, "queues", "queue_id")

    await migrate(url, PROJECTS_REVISION)

    assert await _projects_state(migration_engine, "projects", "project_id") == before
    assert before == [
        ("NEW-1", "NEW", 1),
        ("OLD-1", "OLD", 3),
        ("OLD-3", "OLD", 3),
    ]
    async with migration_engine.connect() as connection:
        names = set(
            await connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid IN "
                    "('projects'::regclass, 'tasks'::regclass) "
                    "UNION SELECT indexname FROM pg_indexes WHERE tablename IN "
                    "('projects', 'tasks')"
                )
            )
        )
    assert not {name for name in names if "queue" in name}
    assert {
        "pk_projects",
        "uq_projects_key",
        "ck_projects_author_kind",
        "fk_tasks_project_id_projects",
        "ix_tasks_project_id_status",
        "ix_tasks_project_id_number",
    } <= names


async def test_the_projects_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, PROJECTS_PREVIOUS)
    await _seed_queues(migration_engine)
    before = await _projects_state(migration_engine, "queues", "queue_id")
    await migrate(url, PROJECTS_REVISION)

    await migrate(url, "-1", down=True)
    assert await _projects_state(migration_engine, "queues", "queue_id") == before

    await migrate(url, PROJECTS_REVISION)
    assert await _projects_state(migration_engine, "projects", "project_id") == before


# --- Дело проекта (TRK-156) -------------------------------------------------------------

#: Ревизия, давшая записи владельца «проект».
PROJECT_CASE_REVISION = "5c1d8e7a2b90"

_INSERT_PROJECT_ENTRY = """
INSERT INTO entries (project_id, no, type, title, created_by_kind, created_by_signature)
SELECT id, 1, 'note', 'Заметка проекта', 'agent', 'claude' FROM projects WHERE key = 'OLD'
"""


async def test_the_project_case_migration_keeps_task_entries_and_takes_project_ones(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, PROJECTS_PREVIOUS)
    await _seed_queues(migration_engine)
    await migrate(url, PROJECTS_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO entries (task_id, no, type, title, created_by_kind, "
                "created_by_signature) SELECT id, 1, 'created', 'Task created', 'agent', "
                "'claude' FROM tasks WHERE key = 'OLD-1'"
            )
        )

    await migrate(url, PROJECT_CASE_REVISION)

    async with migration_engine.begin() as connection:
        await connection.execute(text(_INSERT_PROJECT_ENTRY))
        owners = list(
            await connection.execute(
                text(
                    "SELECT (task_id IS NOT NULL), (project_id IS NOT NULL), no "
                    "FROM entries ORDER BY seq"
                )
            )
        )
    assert [tuple(row) for row in owners] == [(True, False, 1), (False, True, 1)]

    for both_or_none in (
        "INSERT INTO entries (no, type, title, created_by_kind, created_by_signature) "
        "VALUES (9, 'note', 'Ничья', 'agent', 'claude')",
        "INSERT INTO entries (task_id, project_id, no, type, title, created_by_kind, "
        "created_by_signature) SELECT tasks.id, tasks.project_id, 9, 'note', 'Обоих', "
        "'agent', 'claude' FROM tasks WHERE key = 'OLD-1'",
    ):
        with pytest.raises(Exception, match="ck_entries_one_owner"):
            async with migration_engine.begin() as connection:
                await connection.execute(text(both_or_none))


async def test_the_project_case_rollback_refuses_while_project_entries_exist(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, PROJECTS_PREVIOUS)
    await _seed_queues(migration_engine)
    await migrate(url, PROJECT_CASE_REVISION)

    # Без записей проекта откат и повтор проходят.
    await migrate(url, PROJECTS_REVISION, down=True)
    await migrate(url, PROJECT_CASE_REVISION)

    async with migration_engine.begin() as connection:
        await connection.execute(text(_INSERT_PROJECT_ENTRY))

    with pytest.raises(Exception, match="task_id"):
        await migrate(url, PROJECTS_REVISION, down=True)


# --- Описание проекта не длиннее 320 знаков (TRK-158) ---------------------------------

#: Ревизия переноса длинных описаний и ревизия перед ней (атрибуты проекта, TRK-157).
DESCRIPTION_REVISION = "b7d2f94c0e15"
DESCRIPTION_PREVIOUS = "8e4a61c3d2f7"

#: Длинное описание — кириллица с переносами и markdown: переезжает дословно.
LONG_DESCRIPTION = "Бэкенд трекера.\n\n- Код в `app/`, «соглашения» в docs/.\n" * 10
#: Ровно на пределе, кириллицей: 320 знаков — это 640 байт, и поле остаётся.
EXACT_DESCRIPTION = "ж" * 320


async def _seed_descriptions(engine: AsyncEngine) -> None:
    """Четыре проекта: длинное без дела, длинное с делом, на пределе и короткое."""
    async with engine.begin() as connection:
        for key, description in (
            ("LONG", LONG_DESCRIPTION),
            ("CASE", LONG_DESCRIPTION + " + дело"),
            ("EXACT", EXACT_DESCRIPTION),
            ("SHORT", "Коротко"),
        ):
            await connection.execute(
                text(
                    "INSERT INTO projects (key, title, description, created_by_kind, "
                    "created_by_signature) VALUES (:key, :key, :description, 'agent', 'claude')"
                ),
                {"key": key, "description": description},
            )
        # У CASE дело уже начато: база стояла на дереве с делом проекта (демо, атрибуты).
        for no in (1, 2):
            await connection.execute(
                text(
                    "INSERT INTO entries (project_id, no, type, title, created_by_kind, "
                    "created_by_signature) SELECT id, :no, 'note', 'Заметка', 'agent', "
                    "'claude' FROM projects WHERE key = 'CASE'"
                ),
                {"no": no},
            )


async def _descriptions(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT key, description FROM projects"))
        return dict(rows.tuples().all())


async def _moved_notes(engine: AsyncEngine) -> list[tuple]:
    """Записи «Описание до v0.4.0»: ключ проекта, номер, автор, тело, пустота `payload`
    и `refs`, есть ли `action_id`, `task_id`."""
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT projects.key, entries.no, entries.type, entries.created_by_kind, "
                "entries.created_by_signature, entries.body, entries.payload = '{}'::jsonb, "
                "entries.refs = '[]'::jsonb, entries.action_id IS NOT NULL, entries.task_id "
                "FROM entries JOIN projects ON projects.id = entries.project_id "
                "WHERE entries.title = 'Описание до v0.4.0' ORDER BY projects.key"
            )
        )
        return [tuple(row) for row in rows]


async def test_long_descriptions_move_into_the_project_case_word_for_word(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, DESCRIPTION_PREVIOUS)
    await _seed_descriptions(migration_engine)

    await migrate(url, DESCRIPTION_REVISION)

    assert await _descriptions(migration_engine) == {
        "LONG": "",
        "CASE": "",
        "EXACT": EXACT_DESCRIPTION,
        "SHORT": "Коротко",
    }
    common = ("note", "tracker", None)
    assert await _moved_notes(migration_engine) == [
        # Номер следующий за последним в деле: 1 и 2 уже заняты.
        ("CASE", 3, *common, LONG_DESCRIPTION + " + дело", True, True, True, None),
        # Дело было пустым — запись первая.
        ("LONG", 1, *common, LONG_DESCRIPTION, True, True, True, None),
    ]


async def test_the_schema_refuses_a_long_description_after_the_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, DESCRIPTION_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO projects (key, title, description, created_by_kind, "
                "created_by_signature) VALUES ('EXACT', 'x', :description, 'agent', 'claude')"
            ),
            {"description": EXACT_DESCRIPTION},
        )

    with pytest.raises(Exception, match="ck_projects_description_length"):
        async with migration_engine.begin() as connection:
            await connection.execute(text("UPDATE projects SET description = description || 'ж'"))


async def test_the_description_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат снимает ограничение и не трогает данные: записи неизменяемы, а текст в деле."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DESCRIPTION_PREVIOUS)
    await _seed_descriptions(migration_engine)
    await migrate(url, DESCRIPTION_REVISION)
    moved = await _moved_notes(migration_engine)

    await migrate(url, DESCRIPTION_PREVIOUS, down=True)
    assert await _moved_notes(migration_engine) == moved
    async with migration_engine.begin() as connection:
        await connection.execute(
            text("UPDATE projects SET description = :long WHERE key = 'SHORT'"),
            {"long": LONG_DESCRIPTION},
        )

    await migrate(url, DESCRIPTION_REVISION)
    notes = await _moved_notes(migration_engine)
    assert notes[:2] == moved
    assert [(key, no, body) for key, no, *_, body, _p, _r, _a, _t in notes[2:]] == [
        ("SHORT", 1, LONG_DESCRIPTION)
    ]


# --- Архив проекта (TRK-159) ----------------------------------------------------------

ARCHIVE_REVISION = "3f9a6c21d4b8"
ARCHIVE_PREVIOUS = DESCRIPTION_REVISION

_INSERT_PROJECT = text(
    "INSERT INTO projects (key, title, created_by_kind, created_by_signature) "
    "VALUES ('OLD', 'Старый', 'agent', 'claude')"
)
_INSERT_ARCHIVED = text(
    "INSERT INTO entries (project_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT id, 1, 'archived', 'Project archived', "
    """'{"reason": "Заброшен"}'::jsonb, 'human', 'owner' FROM projects WHERE key = 'OLD'"""
)


async def test_existing_projects_stay_active_after_the_archive_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Автоархива нет: у существующего проекта `archived_at` пуст, записи `archived`
    появляются в схеме только этой ревизией."""
    url = f"{test_database_url}_migrations"
    await migrate(url, ARCHIVE_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
    with pytest.raises(Exception, match="ck_entries_entry_type"):
        async with migration_engine.begin() as connection:
            await connection.execute(_INSERT_ARCHIVED)

    await migrate(url, ARCHIVE_REVISION)

    async with migration_engine.begin() as connection:
        archived_at = await connection.scalar(
            text("SELECT archived_at FROM projects WHERE key = 'OLD'")
        )
        await connection.execute(_INSERT_ARCHIVED)
    assert archived_at is None


async def test_the_archive_migration_rolls_back_and_refuses_while_archive_entries_exist(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат снимает колонку; с записью `archived` в деле он спотыкается о сужение типов —
    архивный проект не становится живым молча."""
    url = f"{test_database_url}_migrations"
    await migrate(url, ARCHIVE_REVISION)
    await migrate(url, ARCHIVE_PREVIOUS, down=True)
    await migrate(url, ARCHIVE_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_ARCHIVED)

    with pytest.raises(Exception, match="ck_entries_entry_type"):
        await migrate(url, ARCHIVE_PREVIOUS, down=True)


# --- Перенос задачи (TRK-172) ------------------------------------------------------------

MOVE_REVISION = "6d2e9b41c7f3"
MOVE_PREVIOUS = ARCHIVE_REVISION

_INSERT_TASK = text(
    "INSERT INTO tasks (key, project_id, title, description, created_by_kind, "
    "created_by_signature) SELECT 'OLD-1', id, 'Старая', 'd', 'agent', 'claude' "
    "FROM projects WHERE key = 'OLD'"
)
_INSERT_MOVED = text(
    "INSERT INTO entries (task_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT id, 1, 'moved', 'Moved: NEW-1 -> OLD-1', "
    """'{"from_project": "NEW", "to_project": "OLD", "from_key": "NEW-1", """
    """"to_key": "OLD-1", "reason": "r"}'::jsonb, 'agent', 'claude' """
    "FROM tasks WHERE key = 'OLD-1'"
)


async def test_existing_tasks_have_no_previous_keys_after_the_move_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """До ревизии переносов не было: у существующей задачи прежних ключей нет, а запись
    `moved` появляется в схеме только этой ревизией."""
    url = f"{test_database_url}_migrations"
    await migrate(url, MOVE_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_TASK)
    with pytest.raises(Exception, match="ck_entries_entry_type"):
        async with migration_engine.begin() as connection:
            await connection.execute(_INSERT_MOVED)

    await migrate(url, MOVE_REVISION)

    async with migration_engine.begin() as connection:
        previous = await connection.scalar(
            text("SELECT previous_keys FROM tasks WHERE key = 'OLD-1'")
        )
        await connection.execute(_INSERT_MOVED)
    assert previous == []


async def test_the_move_migration_rolls_back_and_refuses_while_moved_entries_exist(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат снимает колонку и индекс; с записью `moved` в деле он спотыкается о сужение
    типов — прежние ключи не перестают вести на задачу молча."""
    url = f"{test_database_url}_migrations"
    await migrate(url, MOVE_REVISION)
    await migrate(url, MOVE_PREVIOUS, down=True)
    await migrate(url, MOVE_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_TASK)
        await connection.execute(_INSERT_MOVED)

    with pytest.raises(Exception, match="ck_entries_entry_type"):
        await migrate(url, MOVE_PREVIOUS, down=True)


# --- Состояние знакомства учётной записи (TRK-369) ------------------------------------

#: Ревизия, заводящая состояние знакомства, и ревизия перед ней — последняя без него.
ONBOARDING_REVISION = "9a4d7c2f5e81"
ONBOARDING_PREVIOUS = MOVE_REVISION

_INSERT_OLD_ACCOUNT = text(
    "WITH person AS ("
    "  INSERT INTO participants (kind, name, description, created_by_kind, "
    "created_by_signature) VALUES ('human', 'old_owner', '', 'agent', 'claude') "
    "RETURNING id"
    ") "
    "INSERT INTO accounts (participant_id, email, is_admin, created_by_kind, "
    "created_by_signature) SELECT id, 'old_owner@localhost', true, 'agent', 'claude' "
    "FROM person"
)
_INSERT_NEW_ACCOUNT = text(
    "WITH person AS ("
    "  INSERT INTO participants (kind, name, description, created_by_kind, "
    "created_by_signature) VALUES ('human', 'new_owner', '', 'agent', 'claude') "
    "RETURNING id"
    ") "
    "INSERT INTO accounts (participant_id, email, is_admin, created_by_kind, "
    "created_by_signature) SELECT id, 'new_owner@localhost', true, 'agent', 'claude' "
    "FROM person"
)
_SELECT_ONBOARDING = (
    "SELECT onboarding_status, onboarding_hidden_all, onboarding_hidden "
    "FROM accounts WHERE email = :email"
)


async def test_an_existing_account_is_skipped_and_a_new_one_is_pending(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 4: учётная запись прежней ревизии получает `skipped`/`hidden_all:
    true`, заведённая после миграции — `pending` с пустыми подсказками."""
    url = f"{test_database_url}_migrations"
    await migrate(url, ONBOARDING_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_OLD_ACCOUNT)

    await migrate(url, ONBOARDING_REVISION)

    async with migration_engine.begin() as connection:
        old = (
            await connection.execute(text(_SELECT_ONBOARDING), {"email": "old_owner@localhost"})
        ).one()
        await connection.execute(_INSERT_NEW_ACCOUNT)
        new = (
            await connection.execute(text(_SELECT_ONBOARDING), {"email": "new_owner@localhost"})
        ).one()

    assert tuple(old) == ("skipped", True, [])
    assert tuple(new) == ("pending", False, [])


async def test_the_onboarding_status_constraint_stops_accepting_an_unknown_value(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Значение снято на уровне схемы, а не только в коде."""
    url = f"{test_database_url}_migrations"
    await migrate(url, ONBOARDING_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_OLD_ACCOUNT)

    with pytest.raises(Exception, match="ck_accounts_onboarding_status"):
        async with migration_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE accounts SET onboarding_status = 'lost' "
                    "WHERE email = 'old_owner@localhost'"
                )
            )


async def test_the_onboarding_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, ONBOARDING_REVISION)

    await migrate(url, "-1", down=True)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == ONBOARDING_PREVIOUS

    await migrate(url, ONBOARDING_REVISION)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == ONBOARDING_REVISION


# --- Наборы токена сняты (TRK-471) ----------------------------------------------------

#: Ревизия, снимающая `tokens.scope`, и ревизия перед ней.
SCOPE_REVISION = "5c81e3a7d92b"
SCOPE_PREVIOUS = "4c1e8a9d2b37"

_INSERT_SCOPED_TOKEN = text(
    "INSERT INTO tokens (participant_id, scope, name, token_hash, created_by_kind, "
    "created_by_signature) SELECT id, :scope, :name, :hash, 'agent', 'claude' "
    "FROM participants WHERE name = 'worker'"
)


async def test_a_token_issued_with_the_task_scope_works_after_the_scope_is_dropped(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Живые токены обоих наборов переживают миграцию: колонки нет, доступ остался.

    Токен `task` до миграции не звал `create_project`; после неё его держатель
    аутентифицируется тем же секретом и получает полного агента. Состав `tools/list` и
    вызов `create_project` таким токеном проверены в `tests/test_mcp_tools.py` на схеме
    этой же ревизии.
    """
    url = f"{test_database_url}_migrations"
    await migrate(url, SCOPE_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO participants (kind, name, description, created_by_kind, "
                "created_by_signature) VALUES ('agent', 'worker', '', 'agent', 'claude')"
            )
        )
        for scope in ("task", "main"):
            await connection.execute(
                _INSERT_SCOPED_TOKEN,
                {"scope": scope, "name": scope, "hash": hash_token(f"trk_{scope}")},
            )

    await migrate(url, SCOPE_REVISION)

    async with migration_engine.connect() as connection:
        columns = await connection.scalars(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'tokens'")
        )
        assert "scope" not in set(columns)
        constraints = await connection.scalars(
            text("SELECT conname FROM pg_constraint WHERE conname = 'ck_tokens_token_scope'")
        )
        assert list(constraints) == []
    # Аутентификация читает строку нынешней моделью: у неё есть `kind` (TRK-470) и
    # `owner_id` участника (TRK-476), поэтому схему доводят до head — ключи обоих
    # наборов становятся ключами вида `key`.
    await migrate(url, "head")
    async with AsyncSession(migration_engine) as session:
        for scope in ("task", "main"):
            actor = await authenticate(session, f"trk_{scope}")
            assert actor.participant is not None
            assert actor.participant.name == "worker"


async def test_the_scope_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, SCOPE_REVISION)

    await migrate(url, SCOPE_PREVIOUS, down=True)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == SCOPE_PREVIOUS

    await migrate(url, SCOPE_REVISION)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == SCOPE_REVISION


# --- Вид строки доступа (TRK-470) ------------------------------------------------------

#: Ревизия, заводящая `tokens.kind`, и ревизия перед ней — снятие наборов (TRK-471).
TOKEN_KIND_REVISION = "bb05bcd1d657"
TOKEN_KIND_PREVIOUS = "5c81e3a7d92b"


async def _insert_old_token(
    connection: AsyncConnection, name: str, token_hash: str, expires_at: datetime | None
) -> None:
    """Строка `tokens` ревизии перед видом: без вида, наборов к ней уже нет."""
    await connection.execute(
        text(
            "INSERT INTO tokens (name, token_hash, expires_at, created_by_kind) "
            "VALUES (:name, :hash, :expires_at, 'tracker')"
        ),
        {"name": name, "hash": token_hash, "expires_at": expires_at},
    )


async def test_token_kinds_are_filled_from_the_deadline_and_the_name(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 4: сеанс, `local-ui`, `oauth: x` и ключ — `session`, `session`,
    `oauth`, `key`; откат на ревизию раньше проходит."""
    url = f"{test_database_url}_migrations"
    await migrate(url, TOKEN_KIND_PREVIOUS)
    rows = {
        "browser-session": datetime(2030, 1, 1, tzinfo=UTC),
        "local-ui": None,
        "oauth: x": None,
        "ci": None,
    }
    async with migration_engine.begin() as connection:
        for number, (name, expires_at) in enumerate(rows.items()):
            await _insert_old_token(connection, name, f"{number:064d}", expires_at)

    await migrate(url, TOKEN_KIND_REVISION)

    async with migration_engine.connect() as connection:
        kinds = dict((await connection.execute(text("SELECT name, kind FROM tokens"))).all())
    assert [kinds[name] for name in rows] == ["session", "session", "oauth", "key"]

    await migrate(url, TOKEN_KIND_PREVIOUS, down=True)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        columns = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'tokens' AND column_name = 'kind'"
            )
        )
    assert revision == TOKEN_KIND_PREVIOUS
    assert columns == 0


async def test_the_token_kind_constraint_refuses_an_unknown_kind(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, TOKEN_KIND_PREVIOUS)
    async with migration_engine.begin() as connection:
        await _insert_old_token(connection, "ci", "f" * 64, None)
    await migrate(url, TOKEN_KIND_REVISION)

    with pytest.raises(Exception, match="ck_tokens_token_kind"):
        async with migration_engine.begin() as connection:
            await connection.execute(text("UPDATE tokens SET kind = 'cookie'"))


# --- Хозяин участника-агента (TRK-476) -------------------------------------------------

OWNER_REVISION = "7d3a5e1b9c42"
OWNER_PREVIOUS = "bb05bcd1d657"


async def test_existing_participants_have_no_owner_after_the_owner_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, OWNER_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO participants (kind, name, description, created_by_kind, "
                "created_by_signature) VALUES ('agent', 'claude', '', 'agent', 'claude')"
            )
        )

    await migrate(url, OWNER_REVISION)

    async with migration_engine.connect() as connection:
        owners = list(await connection.scalars(text("SELECT owner_id FROM participants")))
    assert owners == [None]


async def test_the_owner_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, OWNER_REVISION)

    await migrate(url, OWNER_PREVIOUS, down=True)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        columns = set(
            await connection.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'participants'"
                )
            )
        )
    assert revision == OWNER_PREVIOUS
    assert "owner_id" not in columns

    await migrate(url, OWNER_REVISION)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == OWNER_REVISION


# --- Ключи людей отзываются (TRK-472) --------------------------------------------------

REVOKE_HUMAN_KEYS_REVISION = "9e2c6b4f1a83"
REVOKE_HUMAN_KEYS_PREVIOUS = "7d3a5e1b9c42"


async def test_only_the_live_keys_of_people_are_revoked(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 4: из сеанса человека, `local-ui`, `bootstrap`, ключа агента и
    общего ключа отозван только `bootstrap`; остальные проходят `authenticate`."""
    url = f"{test_database_url}_migrations"
    await migrate(url, REVOKE_HUMAN_KEYS_PREVIOUS)
    # имя, вид, срок, участник (None — общий)
    rows = [
        ("browser-session", "session", datetime(2031, 1, 1, tzinfo=UTC), "owner"),
        ("local-ui", "session", None, "owner"),
        ("bootstrap", "key", None, "owner"),
        ("agent-key", "key", None, "worker"),
        ("shared-key", "key", None, None),
    ]
    secrets = {name: f"trk_{number:060d}" for number, (name, *_rest) in enumerate(rows)}
    async with migration_engine.begin() as connection:
        for participant_kind, name in (("human", "owner"), ("agent", "worker")):
            await connection.execute(
                text(
                    "INSERT INTO participants (kind, name, description, created_by_kind, "
                    "created_by_signature) VALUES (:kind, :name, '', 'tracker', 'tracker')"
                ),
                {"kind": participant_kind, "name": name},
            )
        for name, token_kind, expires_at, participant in rows:
            await connection.execute(
                text(
                    "INSERT INTO tokens (name, token_hash, kind, expires_at, participant_id, "
                    "created_by_kind) VALUES (:name, :hash, :kind, :expires_at, "
                    "(SELECT id FROM participants WHERE name = :participant), 'tracker')"
                ),
                {
                    "name": name,
                    "hash": hash_token(secrets[name]),
                    "kind": token_kind,
                    "expires_at": expires_at,
                    "participant": participant,
                },
            )

    await migrate(url, REVOKE_HUMAN_KEYS_REVISION)

    async with migration_engine.connect() as connection:
        result = await connection.execute(text("SELECT name, revoked_at IS NOT NULL FROM tokens"))
        revoked = dict(result.all())
    assert revoked == {
        "browser-session": False,
        "local-ui": False,
        "bootstrap": True,
        "agent-key": False,
        "shared-key": False,
    }
    async with AsyncSession(migration_engine) as session:
        for name in ("browser-session", "local-ui", "agent-key", "shared-key"):
            await authenticate(session, secrets[name], label="checker")
        with pytest.raises(UnauthorizedError, match="unknown or revoked"):
            await authenticate(session, secrets["bootstrap"])


async def test_the_revoke_human_keys_migration_rolls_back_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    url = f"{test_database_url}_migrations"
    await migrate(url, REVOKE_HUMAN_KEYS_REVISION)

    await migrate(url, REVOKE_HUMAN_KEYS_PREVIOUS, down=True)
    await migrate(url, REVOKE_HUMAN_KEYS_REVISION)

    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == REVOKE_HUMAN_KEYS_REVISION


# --- Решения проекта у задачи (TRK-554) ----------------------------------------------------

#: Ревизия, заводящая `tasks.decisions`, и ревизия перед ней.
TASK_DECISIONS_REVISION = "4b8e1d6a2c57"
TASK_DECISIONS_PREVIOUS = REVOKE_HUMAN_KEYS_REVISION


async def test_existing_tasks_cite_no_decisions_after_the_decisions_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """До ревизии ссылаться было нечем: у существующей задачи список решений пуст, а откат
    снимает колонку и снова применяется."""
    url = f"{test_database_url}_migrations"
    await migrate(url, TASK_DECISIONS_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_TASK)

    await migrate(url, TASK_DECISIONS_REVISION)
    async with migration_engine.connect() as connection:
        decisions = await connection.scalar(text("SELECT decisions FROM tasks WHERE key = 'OLD-1'"))
    assert decisions == []

    await migrate(url, TASK_DECISIONS_PREVIOUS, down=True)
    async with migration_engine.connect() as connection:
        columns = set(
            await connection.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'tasks'"
                )
            )
        )
    assert "decisions" not in columns
    await migrate(url, TASK_DECISIONS_REVISION)


# --- Статус `waiting` снят (TRK-573) --------------------------------------------------------

#: Ревизия, снимающая статус ожидания, и ревизия перед ней.
DROP_WAITING_REVISION = "a9cb1ec147c4"
DROP_WAITING_PREVIOUS = "4b8e2d7c1f90"

_INSERT_TASKS_WAITING_AND_OPEN = text(
    "INSERT INTO tasks (key, project_id, title, description, status, created_by_kind, "
    "created_by_signature) SELECT rows.key, projects.id, rows.title, 'd', rows.status, 'agent', "
    "'claude' "
    "FROM projects, (VALUES ('OLD-1', 'Ждёт владельца', 'waiting'), "
    "('OLD-2', 'Свободная', 'open')) AS rows (key, title, status) WHERE projects.key = 'OLD'"
)
_INSERT_WAITING_HISTORY = text(
    "INSERT INTO entries (task_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT tasks.id, rows.no, rows.type, rows.title, "
    "CAST(rows.payload AS jsonb), 'agent', 'claude' FROM tasks, (VALUES "
    "(1, 'created', 'Task created', '{}'), "
    "(2, 'status_changed', 'Status changed: in_progress -> waiting', "
    """'{"from": "in_progress", "to": "waiting", "reason": "Жду ответа на OLD-1#3"}')) """
    "AS rows (no, type, title, payload) WHERE tasks.key = 'OLD-1'"
)


async def _seed_waiting(engine: AsyncEngine) -> None:
    """Проект, задача в `waiting` с историей и задача в `open` — установка до TRK-573."""
    async with engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_TASKS_WAITING_AND_OPEN)
        await connection.execute(_INSERT_WAITING_HISTORY)


async def test_a_waiting_task_moves_into_open_and_its_case_names_the_task(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 2 TRK-573: `waiting → open` записью от трекера с причиной.

    Запись подшита следующим номером, без подписи, своим `action_id`, причина называет
    TRK-573; версия выросла. Задачу не в `waiting` миграция не трогает, а старая запись
    о входе в `waiting` остаётся как была — журнал неизменяем.
    """
    url = f"{test_database_url}_migrations"
    await migrate(url, DROP_WAITING_PREVIOUS)
    await _seed_waiting(migration_engine)

    await migrate(url, DROP_WAITING_REVISION)

    async with migration_engine.connect() as connection:
        tasks = {
            row.key: (row.status, row.version)
            for row in await connection.execute(text("SELECT key, status, version FROM tasks"))
        }
        rows = list(
            await connection.execute(
                text(
                    "SELECT tasks.key, entries.no, entries.type, entries.title, entries.payload, "
                    "entries.created_by_kind, entries.created_by_signature, entries.action_id "
                    "FROM entries JOIN tasks ON tasks.id = entries.task_id ORDER BY entries.seq"
                )
            )
        )

    assert tasks == {"OLD-1": ("open", 2), "OLD-2": ("open", 1)}
    assert [(row.key, row.no, row.type) for row in rows] == [
        ("OLD-1", 1, "created"),
        ("OLD-1", 2, "status_changed"),
        ("OLD-1", 3, "status_changed"),
    ]
    entry = rows[-1]
    assert entry.title == "Status changed: waiting -> open"
    assert entry.created_by_kind == "tracker"
    assert entry.created_by_signature is None, "трекер подписи не ставит (`CONCEPT.md`, 3.1)"
    assert entry.action_id is not None
    assert entry.payload["from"] == "waiting"
    assert entry.payload["to"] == "open"
    assert "TRK-573" in entry.payload["reason"]
    assert rows[1].payload["to"] == "waiting", "старая запись не переписана"


async def test_the_status_constraint_refuses_waiting_after_the_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 2 TRK-573: значение снято на уровне схемы, а не только в коде."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DROP_WAITING_PREVIOUS)
    await _seed_waiting(migration_engine)
    await migrate(url, DROP_WAITING_REVISION)

    with pytest.raises(Exception, match="ck_tasks_task_status"):
        async with migration_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tasks (key, project_id, title, description, status, "
                    "created_by_kind, created_by_signature) SELECT 'OLD-3', id, 'Новая', 'd', "
                    "'waiting', 'agent', 'claude' FROM projects WHERE key = 'OLD'"
                )
            )
    with pytest.raises(Exception, match="ck_tasks_task_status"):
        async with migration_engine.begin() as connection:
            await connection.execute(
                text("UPDATE tasks SET status = 'waiting' WHERE key = 'OLD-2'")
            )


async def test_the_waiting_migration_rolls_back_only_the_constraint(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат возвращает `waiting` в ограничение и не переводит задачи назад; подъём снова идёт."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DROP_WAITING_PREVIOUS)
    await _seed_waiting(migration_engine)
    await migrate(url, DROP_WAITING_REVISION)

    await migrate(url, DROP_WAITING_PREVIOUS, down=True)
    async with migration_engine.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        status = await connection.scalar(text("SELECT status FROM tasks WHERE key = 'OLD-1'"))
        # Ограничение снова принимает статус: откат вернул именно его.
        await connection.execute(text("UPDATE tasks SET status = 'waiting' WHERE key = 'OLD-2'"))
    assert revision == DROP_WAITING_PREVIOUS
    assert status == "open"

    await migrate(url, DROP_WAITING_REVISION)
    async with migration_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        statuses = set(await connection.scalars(text("SELECT status FROM tasks")))
    assert revision == DROP_WAITING_REVISION
    assert statuses == {"open"}


# --- Направления (TRK-555) ---------------------------------------------------------------

#: Ревизия направлений и ревизия перед ней.
DIRECTIONS_REVISION = "3cc02e043842"
DIRECTIONS_PREVIOUS = DROP_WAITING_REVISION

_INSERT_DIRECTION = text(
    "INSERT INTO directions (project_id, key, title, created_by_kind, created_by_signature) "
    "SELECT id, 'promotion', 'Популяризация', 'agent', 'claude' FROM projects WHERE key = 'OLD'"
)
_INSERT_DIRECTION_ENTRY = text(
    "INSERT INTO entries (direction_id, no, type, title, created_by_kind, created_by_signature) "
    "SELECT id, 1, 'created', 'Direction created', 'agent', 'claude' FROM directions"
)


async def test_a_direction_entry_has_exactly_one_owner_after_the_directions_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Запись направления держит пустыми `task_id` и `project_id`; запись без владельца и
    запись двух владельцев отклоняет `ck_entries_one_owner` о трёх колонках."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DIRECTIONS_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)

    await migrate(url, DIRECTIONS_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_DIRECTION)
        await connection.execute(_INSERT_DIRECTION_ENTRY)
        owners = list(
            await connection.execute(
                text(
                    "SELECT (task_id IS NULL), (project_id IS NULL), (direction_id IS NULL) "
                    "FROM entries"
                )
            )
        )
    assert [tuple(row) for row in owners] == [(True, True, False)]

    for wrong in (
        "INSERT INTO entries (no, type, title, created_by_kind, created_by_signature) "
        "VALUES (9, 'note', 'Ничья', 'agent', 'claude')",
        "INSERT INTO entries (project_id, direction_id, no, type, title, created_by_kind, "
        "created_by_signature) SELECT project_id, id, 9, 'note', 'Обоих', 'agent', 'claude' "
        "FROM directions",
    ):
        with pytest.raises(Exception, match="ck_entries_one_owner"):
            async with migration_engine.begin() as connection:
                await connection.execute(text(wrong))
    with pytest.raises(Exception, match="uq_directions_project_id_key"):
        async with migration_engine.begin() as connection:
            await connection.execute(_INSERT_DIRECTION)


async def test_the_directions_rollback_refuses_while_direction_entries_exist(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Без записей направлений откат и повтор проходят; с ними откат отказывает на
    проверке владельца: запись без владельца базе не нужна, а удалить её нельзя."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DIRECTIONS_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
    await migrate(url, DIRECTIONS_REVISION)

    await migrate(url, DIRECTIONS_PREVIOUS, down=True)
    await migrate(url, DIRECTIONS_REVISION)

    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_DIRECTION)
        await connection.execute(_INSERT_DIRECTION_ENTRY)

    with pytest.raises(Exception, match="ck_entries_one_owner"):
        await migrate(url, DIRECTIONS_PREVIOUS, down=True)


# --- Направление — область (TRK-675) ------------------------------------------------------

#: Ревизия переименования и ревизия перед ней.
AREAS_REVISION = "ed61a83a9be0"
AREAS_PREVIOUS = "29c012062376"

_INSERT_DIRECTION_HISTORY = text(
    "INSERT INTO entries (direction_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT directions.id, rows.no, rows.type, rows.title, "
    "CAST(rows.payload AS jsonb), 'agent', 'claude' FROM directions, (VALUES "
    """(2, 'archived', 'Direction archived', '{"reason": "Пауза"}'), """
    """(3, 'restored', 'Direction restored', '{"reason": "Снова в работе"}'), """
    "(4, 'note', 'Direction of the work', '{}')) AS rows (no, type, title, payload)"
)
_INSERT_DIRECTION_ATTRIBUTE = text(
    "INSERT INTO direction_attributes (direction_id, name, value) "
    "SELECT id, 'repo', 'casefile' FROM directions"
)
_INSERT_TASK_IN_DIRECTION = text(
    "INSERT INTO tasks (key, project_id, title, description, status, created_by_kind, "
    "created_by_signature, direction_id) SELECT 'OLD-1', projects.id, 'Задача в направлении', 'd', "
    "'open', 'agent', 'claude', directions.id FROM projects JOIN directions "
    "ON directions.project_id = projects.id WHERE projects.key = 'OLD'"
)
_INSERT_TASK_FIELD_HISTORY = text(
    "INSERT INTO entries (task_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT tasks.id, rows.no, rows.type, rows.title, "
    "CAST(rows.payload AS jsonb), 'agent', 'claude' FROM tasks, (VALUES "
    "(1, 'created', 'Task created', '{}'), "
    "(2, 'field_changed', 'Field changed: direction', "
    """'{"field": "direction", "before": null, "after": "OLD/promotion"}'), """
    "(3, 'field_changed', 'Field changed: priority', "
    """'{"field": "priority", "before": "normal", "after": "high"}')) """
    "AS rows (no, type, title, payload) WHERE tasks.key = 'OLD-1'"
)

#: Записи дела после переименования — те же байты: записи неизменяемы, и прежнее слово
#: в нагрузке и заголовках остаётся как написано (решение — дело TRK-675).
_ENTRIES_AS_WRITTEN = [
    ("OLD-1", 1, "created", "Task created", {}),
    (
        "OLD-1",
        2,
        "field_changed",
        "Field changed: direction",
        {"field": "direction", "before": None, "after": "OLD/promotion"},
    ),
    (
        "OLD-1",
        3,
        "field_changed",
        "Field changed: priority",
        {"field": "priority", "before": "normal", "after": "high"},
    ),
    ("OLD/promotion", 1, "created", "Direction created", {}),
    ("OLD/promotion", 2, "archived", "Direction archived", {"reason": "Пауза"}),
    ("OLD/promotion", 3, "restored", "Direction restored", {"reason": "Снова в работе"}),
    ("OLD/promotion", 4, "note", "Direction of the work", {}),
]


async def _seed_direction_with_history(engine: AsyncEngine) -> None:
    """Направление с атрибутом и делом и задача в нём с правкой поля — установка до TRK-675."""
    async with engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_DIRECTION)
        await connection.execute(_INSERT_DIRECTION_ENTRY)
        await connection.execute(_INSERT_DIRECTION_HISTORY)
        await connection.execute(_INSERT_DIRECTION_ATTRIBUTE)
        await connection.execute(_INSERT_TASK_IN_DIRECTION)
        await connection.execute(_INSERT_TASK_FIELD_HISTORY)


async def _schema_names_with(connection: AsyncConnection, word: str) -> list[str]:
    """Таблицы, колонки, ограничения и индексы схемы `public`, в чьём имени есть слово."""
    rows = await connection.execute(
        text(
            "SELECT 'table ' || table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :pattern "
            "UNION ALL SELECT 'column ' || table_name || '.' || column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name LIKE :pattern "
            "UNION ALL SELECT 'constraint ' || conname FROM pg_constraint "
            "JOIN pg_namespace ON pg_namespace.oid = pg_constraint.connamespace "
            "WHERE nspname = 'public' AND conname LIKE :pattern "
            "UNION ALL SELECT 'index ' || indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname LIKE :pattern"
        ),
        {"pattern": f"%{word}%"},
    )
    return sorted(rows.scalars())


async def _entries_by_owner(connection: AsyncConnection, area: str) -> list[tuple[Any, ...]]:
    """Записи задач и дела области: владелец — ключ задачи или адрес, номер, тип, текст."""
    rows = await connection.execute(
        text(
            "SELECT coalesce(tasks.key, projects.key || '/' || owner.key) AS owner, "
            "entries.no, entries.type, entries.title, entries.payload FROM entries "
            "LEFT JOIN tasks ON tasks.id = entries.task_id "
            f"LEFT JOIN {area}s AS owner ON owner.id = entries.{area}_id "
            "LEFT JOIN projects ON projects.id = owner.project_id "
            "ORDER BY owner.key NULLS FIRST, entries.no"
        )
    )
    return [tuple(row) for row in rows]


async def test_directions_become_areas_with_their_rows_and_names(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка TRK-675: таблицы, колонки и имена объектов — `area`, строки те же.

    Направление, его атрибут и задача в нём доходят до `areas`, `area_attributes` и
    `tasks.area_id` с теми же ключами, записи дела — теми же байтами. Ни одного имени
    со словом `direction` в схеме не остаётся, а проверка одного владельца и номер
    внутри области держат новую колонку.
    """
    url = f"{test_database_url}_migrations"
    await migrate(url, AREAS_PREVIOUS)
    await _seed_direction_with_history(migration_engine)

    await migrate(url, AREAS_REVISION)

    async with migration_engine.connect() as connection:
        areas = list(
            await connection.execute(
                text(
                    "SELECT projects.key, areas.key, areas.title FROM areas "
                    "JOIN projects ON projects.id = areas.project_id"
                )
            )
        )
        attributes = list(
            await connection.execute(
                text(
                    "SELECT areas.key, name, value FROM area_attributes "
                    "JOIN areas ON areas.id = area_attributes.area_id"
                )
            )
        )
        tasks = list(
            await connection.execute(
                text(
                    "SELECT tasks.key, areas.key FROM tasks JOIN areas ON areas.id = tasks.area_id"
                )
            )
        )
        entries = await _entries_by_owner(connection, "area")
        leftovers = await _schema_names_with(connection, "direction")

    assert [tuple(row) for row in areas] == [("OLD", "promotion", "Популяризация")]
    assert [tuple(row) for row in attributes] == [("promotion", "repo", "casefile")]
    assert [tuple(row) for row in tasks] == [("OLD-1", "promotion")]
    assert entries == _ENTRIES_AS_WRITTEN
    assert leftovers == []

    with pytest.raises(Exception, match="ck_entries_one_owner"):
        async with migration_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO entries (project_id, area_id, no, type, title, "
                    "created_by_kind, created_by_signature) SELECT project_id, id, 9, 'note', "
                    "'Обоих', 'agent', 'claude' FROM areas"
                )
            )
    with pytest.raises(Exception, match="uq_entries_area_id_no"):
        async with migration_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO entries (area_id, no, type, title, created_by_kind, "
                    "created_by_signature) SELECT id, 1, 'note', 'Повтор номера', 'agent', "
                    "'claude' FROM areas"
                )
            )


async def test_the_areas_rollback_brings_the_direction_names_back(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат возвращает прежние имена, записи остаются как были; подъём снова идёт."""
    url = f"{test_database_url}_migrations"
    await migrate(url, AREAS_PREVIOUS)
    await _seed_direction_with_history(migration_engine)
    async with migration_engine.connect() as connection:
        seeded = await _entries_by_owner(connection, "direction")
    await migrate(url, AREAS_REVISION)

    await migrate(url, AREAS_PREVIOUS, down=True)
    async with migration_engine.connect() as connection:
        rolled_back = await _entries_by_owner(connection, "direction")
        leftovers = await _schema_names_with(connection, "area")
    assert seeded == rolled_back == _ENTRIES_AS_WRITTEN
    assert leftovers == []

    await migrate(url, AREAS_REVISION)
    async with migration_engine.connect() as connection:
        assert await _entries_by_owner(connection, "area") == _ENTRIES_AS_WRITTEN


# --- Обсуждения (TRK-669) -----------------------------------------------------------------

#: Ревизия обсуждений и ревизия перед ней.
DISCUSSIONS_REVISION = "5d0c8e3a71b4"
DISCUSSIONS_PREVIOUS = AREAS_REVISION

_INSERT_DISCUSSION = text(
    "INSERT INTO discussions (project_id, number, title, created_by_kind, "
    "created_by_signature) SELECT id, 1, 'Хранить ли дела вечно?', 'agent', 'claude' "
    "FROM projects WHERE key = 'OLD'"
)
_INSERT_DISCUSSION_ENTRY = text(
    "INSERT INTO entries (discussion_id, no, type, title, created_by_kind, "
    "created_by_signature) SELECT id, 1, 'created', 'Discussion created', 'agent', 'claude' "
    "FROM discussions"
)


async def test_a_discussion_entry_has_exactly_one_owner_after_the_discussions_migration(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Запись обсуждения держит пустыми три других колонки владельца; запись двух
    владельцев отклоняет `ck_entries_one_owner` о четырёх колонках; номер обсуждения
    уникален в проекте, статус — `open` по умолчанию, типы записей обсуждения проходят."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DISCUSSIONS_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)

    await migrate(url, DISCUSSIONS_REVISION)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_DISCUSSION)
        await connection.execute(_INSERT_DISCUSSION_ENTRY)
        await connection.execute(
            text(
                "INSERT INTO entries (discussion_id, no, type, title, payload, "
                "created_by_kind, created_by_signature) SELECT id, 2, 'conclusion', 'Да', "
                """'{"decided": "Да", "superseded": "ничего", "open": "ничего"}'::jsonb, """
                "'agent', 'claude' FROM discussions"
            )
        )
        owners = list(
            await connection.execute(
                text(
                    "SELECT (task_id IS NULL), (project_id IS NULL), (area_id IS NULL), "
                    "(discussion_id IS NULL) FROM entries ORDER BY no"
                )
            )
        )
        status = await connection.scalar(text("SELECT status FROM discussions"))
    assert [tuple(row) for row in owners] == [(True, True, True, False)] * 2
    assert status == "open"

    with pytest.raises(Exception, match="ck_entries_one_owner"):
        async with migration_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO entries (project_id, discussion_id, no, type, title, "
                    "created_by_kind, created_by_signature) SELECT project_id, id, 9, 'note', "
                    "'Обоих', 'agent', 'claude' FROM discussions"
                )
            )
    with pytest.raises(Exception, match="uq_discussions_project_id_number"):
        async with migration_engine.begin() as connection:
            await connection.execute(_INSERT_DISCUSSION)


async def test_the_discussions_rollback_refuses_while_discussion_entries_exist(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Без записей обсуждений откат и повтор проходят; с ними откат отказывает: запись
    без владельца базе не нужна, а удалить её нельзя."""
    url = f"{test_database_url}_migrations"
    await migrate(url, DISCUSSIONS_PREVIOUS)
    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
    await migrate(url, DISCUSSIONS_REVISION)

    await migrate(url, DISCUSSIONS_PREVIOUS, down=True)
    await migrate(url, DISCUSSIONS_REVISION)

    async with migration_engine.begin() as connection:
        await connection.execute(_INSERT_DISCUSSION)
        await connection.execute(_INSERT_DISCUSSION_ENTRY)

    with pytest.raises(Exception, match="ck_entries_one_owner"):
        await migrate(url, DISCUSSIONS_PREVIOUS, down=True)


# --- Вопросы — в обсуждения: открытые вопросы дел задач снимаются (TRK-671) ---------------

#: Ревизия, снимающая открытые вопросы дел задач, и ревизия перед ней.
WITHDRAW_QUESTIONS_REVISION = "3b9f4d192289"
WITHDRAW_QUESTIONS_PREVIOUS = DISCUSSIONS_REVISION

#: Тело записи снятия — дословно из решения владельца (TRK-667#17, п. 2).
WITHDRAWN_BODY = (
    "Вопрос закрыт: вопросы теперь задаются в обсуждениях. "
    "Агенту — переспросить через обсуждение."
)

_INSERT_TASKS_WITH_QUESTIONS = text(
    "INSERT INTO tasks (key, project_id, title, description, status, created_by_kind, "
    "created_by_signature) SELECT rows.key, projects.id, rows.title, 'd', rows.status, 'agent', "
    "'claude' FROM projects, (VALUES ('OLD-1', 'Два открытых', 'open'), "
    "('OLD-2', 'Закрыта с открытым', 'done'), ('OLD-3', 'Без вопросов', 'open')) "
    "AS rows (key, title, status) WHERE projects.key = 'OLD'"
)
#: Дело OLD-1: открытый блокирующий (#2), отвеченный (#3, ответ #4), снятый (#5, ответ #6)
#: и открытый неблокирующий (#7). Дело OLD-2: открытый вопрос (#2) у закрытой задачи.
_INSERT_QUESTION_HISTORY = text(
    "INSERT INTO entries (task_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT tasks.id, rows.no, rows.type, rows.title, "
    "CAST(rows.payload AS jsonb), 'agent', 'claude' FROM tasks JOIN (VALUES "
    "('OLD-1', 1, 'created', 'Task created', '{}'), "
    """('OLD-1', 2, 'question', 'Держит?', '{"addressees": ["owner"], "blocking": true}'), """
    """('OLD-1', 3, 'question', 'Ответят?', '{"addressees": ["owner"], "blocking": false}'), """
    """('OLD-1', 4, 'answer', 'Answer to OLD-1#3', '{"question_no": 3}'), """
    """('OLD-1', 5, 'question', 'Снят?', '{"addressees": ["owner"], "blocking": true}'), """
    "('OLD-1', 6, 'answer', 'Answer to OLD-1#5: withdrawn', "
    """'{"question_no": 5, "outcome": "withdrawn", "replaced_by": null}'), """
    """('OLD-1', 7, 'question', 'Попутный?', '{"addressees": ["owner"], "blocking": false}'), """
    "('OLD-2', 1, 'created', 'Task created', '{}'), "
    """('OLD-2', 2, 'question', 'Забыт?', '{"addressees": ["owner"], "blocking": true}'), """
    "('OLD-3', 1, 'created', 'Task created', '{}')) "
    "AS rows (key, no, type, title, payload) ON tasks.key = rows.key"
)
_INSERT_DISCUSSION_QUESTION = text(
    "INSERT INTO entries (discussion_id, no, type, title, payload, created_by_kind, "
    "created_by_signature) SELECT id, 2, 'question', 'Вопрос обсуждения', "
    """'{"addressees": ["owner"], "blocking": true}'::jsonb, 'agent', 'claude' FROM discussions"""
)

#: Открытые вопросы дел задач — то же правило, что у выдачи (`_unanswered`).
_OPEN_TASK_QUESTIONS = text(
    "SELECT count(*) FROM entries AS question WHERE question.type = 'question' "
    "AND question.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM entries AS reply "
    "WHERE reply.task_id = question.task_id AND reply.type = 'answer' "
    "AND (reply.payload ->> 'question_no')::integer = question.no)"
)


async def _seed_task_questions(engine: AsyncEngine) -> None:
    """Установка до TRK-671: открытые, отвеченные и снятые вопросы в делах задач и открытый
    вопрос в деле обсуждения."""
    async with engine.begin() as connection:
        await connection.execute(_INSERT_PROJECT)
        await connection.execute(_INSERT_TASKS_WITH_QUESTIONS)
        await connection.execute(_INSERT_QUESTION_HISTORY)
        await connection.execute(_INSERT_DISCUSSION)
        await connection.execute(_INSERT_DISCUSSION_ENTRY)
        await connection.execute(_INSERT_DISCUSSION_QUESTION)


async def _task_entries(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as connection:
        return list(
            await connection.execute(
                text(
                    "SELECT tasks.key, entries.no, entries.type, entries.title, entries.body, "
                    "entries.payload, entries.created_by_kind, entries.created_by_signature, "
                    "entries.action_id FROM entries JOIN tasks ON tasks.id = entries.task_id "
                    "ORDER BY entries.seq"
                )
            )
        )


async def test_the_migration_withdraws_exactly_the_open_questions_of_task_cases(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Обзорная проверка 1 TRK-671: каждый открытый вопрос дела задачи — и у закрытой
    задачи — получает `answer` с исходом `withdrawn` от трекера с телом из решения
    владельца; отвеченные, снятые и вопросы обсуждений не трогаются; открытых не остаётся."""
    url = f"{test_database_url}_migrations"
    await migrate(url, WITHDRAW_QUESTIONS_PREVIOUS)
    await _seed_task_questions(migration_engine)
    async with migration_engine.connect() as connection:
        open_before = await connection.scalar(_OPEN_TASK_QUESTIONS)
    before = await _task_entries(migration_engine)

    await migrate(url, WITHDRAW_QUESTIONS_REVISION)

    after = await _task_entries(migration_engine)
    async with migration_engine.connect() as connection:
        open_after = await connection.scalar(_OPEN_TASK_QUESTIONS)
        discussion = list(
            await connection.execute(
                text("SELECT no, type FROM entries WHERE discussion_id IS NOT NULL ORDER BY no")
            )
        )

    added = after[len(before) :]
    assert [tuple(row) for row in after[: len(before)]] == [tuple(row) for row in before]
    assert (open_before, len(added), open_after) == (3, 3, 0)
    assert [(row.key, row.no, row.title) for row in added] == [
        ("OLD-1", 8, "Answer to OLD-1#2: withdrawn"),
        ("OLD-1", 9, "Answer to OLD-1#7: withdrawn"),
        ("OLD-2", 3, "Answer to OLD-2#2: withdrawn"),
    ]
    assert [row.payload for row in added] == [
        {"question_no": 2, "outcome": "withdrawn", "replaced_by": None},
        {"question_no": 7, "outcome": "withdrawn", "replaced_by": None},
        {"question_no": 2, "outcome": "withdrawn", "replaced_by": None},
    ]
    assert {(row.type, row.body, row.created_by_kind) for row in added} == {
        ("answer", WITHDRAWN_BODY, "tracker")
    }
    assert {row.created_by_signature for row in added} == {None}
    assert len({row.action_id for row in added}) == 3
    assert [tuple(row) for row in discussion] == [(1, "created"), (2, "question")]


async def test_the_withdrawal_rolls_back_without_touching_the_case_and_reapplies(
    migration_engine: AsyncEngine, test_database_url: str
) -> None:
    """Откат ничего не снимает (дело неизменяемо), повторный подъём ничего не добавляет:
    снятых вопросов он уже не находит открытыми."""
    url = f"{test_database_url}_migrations"
    await migrate(url, WITHDRAW_QUESTIONS_PREVIOUS)
    await _seed_task_questions(migration_engine)
    await migrate(url, WITHDRAW_QUESTIONS_REVISION)
    once = await _task_entries(migration_engine)

    await migrate(url, WITHDRAW_QUESTIONS_PREVIOUS, down=True)
    await migrate(url, WITHDRAW_QUESTIONS_REVISION)

    assert [tuple(row) for row in await _task_entries(migration_engine)] == [
        tuple(row) for row in once
    ]
