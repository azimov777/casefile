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
