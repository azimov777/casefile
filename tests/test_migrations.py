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

import asyncpg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

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
