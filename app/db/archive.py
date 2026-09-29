"""Архив установки на стороне базы: строки таблиц в текст и обратно, схема на ревизии архива.

Здесь всё, что знает про PostgreSQL и Alembic, — и ничего о том, **что** переносится:
какие таблицы исключены и какие строки не едут, решает сценарий
(`app/services/archive.py`) по правилам `app/domain/archive.py`.

## Схема на ревизии архива — во временной схеме, а не в `public`

Архив снят на своей ревизии, и его строки ложатся только в схему той же ревизии. Её
строит тот же код, что обновляет живые установки: миграции Alembic от нуля до ревизии
архива, но во временной схеме `SCRATCH_SCHEMA`, — затем строки архива, затем миграции до
head, и только после этого строки переносятся в `public`. Таблицы `public` при этом не
пересоздаются: их OID прежние, и соседний процесс (`mcp`), держащий подготовленные
запросы, не ловит протухший кеш. Всё идёт в транзакции вызывающего: отказ на любом шаге
не оставляет ни временной схемы, ни полупринятых строк.

Миграции во временной схеме работают потому, что `search_path` на это время начинается
с неё: неквалифицированные имена, которыми пишут миграции (`CREATE TABLE tasks`, `DROP
INDEX ix_...`), находят и создают объекты там. `public` остаётся в пути вторым — ради
расширения `pg_trgm` и его классов операторов, которые живут там. Таблица версии Alembic
названа схемой явно (`version_table_schema`): поиск по пути нашёл бы `public.alembic_version`
установки и решил бы, что временная схема уже на head.
"""

import graphlib
import io
from collections.abc import Collection, Sequence
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

#: Временная схема приёма. Живёт внутри одной транзакции приёма и удаляется ею же.
SCRATCH_SCHEMA = "casefile_import"

#: Схема данных установки.
PUBLIC_SCHEMA = "public"

#: Таблица версии Alembic: ни выгружается, ни заменяется приёмом.
VERSION_TABLE = "alembic_version"

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _alembic_config() -> Config:
    """Конфиг Alembic без файла: `alembic.ini` настраивает логирование процесса, а этот
    конфиг живёт внутри работающего API, чьё логирование трогать нельзя."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def head_revision() -> str:
    """Последняя ревизия, которую знает этот Casefile."""
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert head is not None  # у проекта одна линия миграций и она не пуста
    return head


def is_known_revision(revision: str) -> bool:
    """Знает ли этот Casefile такую ревизию — то есть не новее ли архив приёмника."""
    try:
        return ScriptDirectory.from_config(_alembic_config()).get_revision(revision) is not None
    except CommandError:
        return False


async def current_revision(session: AsyncSession) -> str:
    """Ревизия схемы `public` — на ней снимается архив."""
    revision = await session.scalar(
        text(f"SELECT version_num FROM {PUBLIC_SCHEMA}.{VERSION_TABLE}")
    )
    assert revision is not None  # приложение не работает на базе без миграций
    return str(revision)


async def table_columns(session: AsyncSession, schema: str) -> dict[str, tuple[str, ...]]:
    """Таблицы схемы и их колонки в порядке объявления, без вычисляемых.

    Вычисляемые (`GENERATED ALWAYS AS ... STORED`) не выгружаются и не принимаются:
    `COPY` их не пишет, Postgres считает их сам. Колонки идентичности (`seq`) — обычные
    колонки для этой цели: `COPY ... FROM` пишет в них присланное значение.
    """
    rows = await session.execute(
        text(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = :schema AND t.table_type = 'BASE TABLE' "
            "  AND c.is_generated = 'NEVER' "
            "ORDER BY c.table_name, c.ordinal_position"
        ),
        {"schema": schema},
    )
    tables: dict[str, list[str]] = {}
    for table, column in rows:
        tables.setdefault(table, []).append(column)
    return {table: tuple(columns) for table, columns in tables.items()}


async def load_order(session: AsyncSession, schema: str, tables: Sequence[str]) -> list[str]:
    """Таблицы в порядке, где таблица идёт после всех, на кого ссылается внешним ключом.

    Строки ложатся с проверкой внешних ключей на каждой строке, поэтому родитель обязан
    лечь раньше ребёнка. Ссылка таблицы на саму себя порядок не задаёт и отбрасывается;
    строки внутри такой таблицы архив должен нести родителем вперёд.
    """
    edges = await session.execute(
        text(
            "SELECT child.relname, parent.relname FROM pg_constraint c "
            "JOIN pg_class child ON child.oid = c.conrelid "
            "JOIN pg_class parent ON parent.oid = c.confrelid "
            "JOIN pg_namespace n ON n.oid = child.relnamespace "
            "WHERE c.contype = 'f' AND n.nspname = :schema"
        ),
        {"schema": schema},
    )
    wanted = set(tables)
    graph: dict[str, set[str]] = {table: set() for table in sorted(wanted)}
    for child, parent in edges:
        if child in wanted and parent in wanted and child != parent:
            graph[child].add(parent)
    return list(graphlib.TopologicalSorter(graph).static_order())


#: Колонка, по которой строка называется при отборе (`referencing_rows`): первичный ключ
#: каждой таблицы данных (`app/db/base.py`, `BaseModel`).
ROW_ID = "id"


async def referencing_rows(
    session: AsyncSession, schema: str, table: str, column: str, value: str
) -> dict[str, set[str]]:
    """Строки, где `table.column = value`, и все строки, что ссылаются на них внешним
    ключом — прямо или через другие такие же; `id::text` по таблицам.

    Граф ссылок берётся из каталога Postgres, а не из перечня таблиц: таблица, заведённая
    позже и забытая в перечне, дала бы архив, который приём отклонит строкой со ссылкой
    на вырезанную. Обход идёт до неподвижной точки — строка, дошедшая до отбора по одной
    ссылке, тянет за собой свои. Каждая таблица на пути обязана иметь колонку `ROW_ID`;
    составной внешний ключ здесь не разбирается, и такой ключ в схеме — отказ, а не
    молча пропущенная ссылка.
    """
    edges = await session.execute(
        text(
            "SELECT child.relname, child_col.attname, parent.relname, parent_col.attname, "
            "  cardinality(c.conkey) "
            "FROM pg_constraint c "
            "JOIN pg_class child ON child.oid = c.conrelid "
            "JOIN pg_class parent ON parent.oid = c.confrelid "
            "JOIN pg_namespace n ON n.oid = child.relnamespace "
            "JOIN pg_attribute child_col "
            "  ON child_col.attrelid = c.conrelid AND child_col.attnum = c.conkey[1] "
            "JOIN pg_attribute parent_col "
            "  ON parent_col.attrelid = c.confrelid AND parent_col.attnum = c.confkey[1] "
            "WHERE c.contype = 'f' AND n.nspname = :schema"
        ),
        {"schema": schema},
    )
    references: list[tuple[str, str, str, str]] = []
    for child, child_column, parent, parent_column, width in edges:
        if width != 1:
            raise RuntimeError(f"composite foreign key {child} -> {parent} is not supported")
        references.append((child, child_column, parent, parent_column))

    found = await session.execute(
        text(
            f"SELECT {_ident(ROW_ID)}::text FROM {_qualified(schema, table)} "
            f"WHERE {_ident(column)} = :value"
        ),
        {"value": value},
    )
    reached: dict[str, set[str]] = {table: {row[0] for row in found}}
    frontier = {name: set(ids) for name, ids in reached.items() if ids}
    while frontier:
        grown: dict[str, set[str]] = {}
        for child, child_column, parent, parent_column in references:
            ids = frontier.get(parent)
            if not ids:
                continue
            rows = await session.execute(
                text(
                    f"SELECT c.{_ident(ROW_ID)}::text FROM {_qualified(schema, child)} c "
                    f"WHERE c.{_ident(child_column)} IN ("
                    f"  SELECT p.{_ident(parent_column)} FROM {_qualified(schema, parent)} p "
                    f"  WHERE p.{_ident(ROW_ID)}::text = ANY(:ids))"
                ),
                {"ids": sorted(ids)},
            )
            new = {row[0] for row in rows} - reached.setdefault(child, set())
            if new:
                reached[child] |= new
                grown.setdefault(child, set()).update(new)
        frontier = grown
    return {name: ids for name, ids in reached.items() if ids}


async def read_rows(
    session: AsyncSession,
    schema: str,
    table: str,
    columns: Sequence[str],
    *,
    only_null: str | None = None,
    skip_ids: Collection[str] = (),
) -> list[list[str | None]]:
    """Строки таблицы, каждое значение — `col::text`; `only_null` — колонка, которая у
    выгружаемых строк обязана быть `NULL` (так не едут токены сеансов); `skip_ids` —
    строки, которые не едут, по `ROW_ID` (`referencing_rows`).

    Время выводится в UTC (`SET LOCAL TimeZone` в `utc_session`): текст `timestamptz`
    зависит от часового пояса сеанса, и архив одной базы не должен зависеть от того, в
    каком поясе его сняли.
    """
    selected = ", ".join(f"{_ident(column)}::text" for column in columns)
    conditions: list[str] = []
    if only_null in columns:
        conditions.append(f"{_ident(only_null)} IS NULL")
    if skip_ids:
        conditions.append(f"NOT ({_ident(ROW_ID)}::text = ANY(:skip_ids))")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await session.execute(
        text(f"SELECT {selected} FROM {_qualified(schema, table)}{where}"),
        {"skip_ids": sorted(skip_ids)} if skip_ids else {},
    )
    return [list(row) for row in result]


async def use_utc(session: AsyncSession) -> None:
    """Часовой пояс сеанса — UTC до конца транзакции (`read_rows`)."""
    await session.execute(text("SET LOCAL TimeZone = 'UTC'"))


async def build_scratch(session: AsyncSession, revision: str) -> None:
    """Пустая временная схема на ревизии архива: миграции от нуля до `revision`.

    После вызова `search_path` начинается с временной схемы и остаётся таким до
    `replace_public_from_scratch` — между ними пишутся только квалифицированные имена.
    """
    await session.execute(text(f"DROP SCHEMA IF EXISTS {_ident(SCRATCH_SCHEMA)} CASCADE"))
    await session.execute(text(f"CREATE SCHEMA {_ident(SCRATCH_SCHEMA)}"))
    await session.execute(
        text(f"SET LOCAL search_path TO {_ident(SCRATCH_SCHEMA)}, {_ident(PUBLIC_SCHEMA)}")
    )
    await upgrade_scratch(session, revision)


async def upgrade_scratch(session: AsyncSession, revision: str) -> None:
    """Миграции временной схемы до `revision` — в транзакции вызывающего."""
    connection = await session.connection()
    await connection.run_sync(_upgrade, revision)


def _upgrade(connection: Connection, revision: str) -> None:
    config = _alembic_config()
    # `app/db/migrations/env.py` берёт готовое соединение отсюда, а не открывает своё:
    # миграции идут в транзакции приёма и откатываются вместе с ней.
    config.attributes["connection"] = connection
    config.attributes["version_table_schema"] = SCRATCH_SCHEMA
    command.upgrade(config, revision)


async def copy_rows(
    session: AsyncSession, schema: str, table: str, columns: Sequence[str], data: bytes
) -> asyncpg.PostgresError | None:
    """Кладёт строки текстового формата `COPY` в таблицу; ошибка Postgres — возвращается.

    Возвращается, а не бросается: отказ Postgres на строке архива — это отказ архива, и
    объяснять его обязан сценарий, знающий, какой архив и какая таблица. Транзакция
    после такой ошибки прервана, и продолжать её нельзя — только откатить.
    """
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    driver: asyncpg.Connection = raw.driver_connection  # type: ignore[assignment]
    try:
        # Файлоподобный объект, а не `bytes`: `bytes` asyncpg принимает за путь к файлу.
        await driver.copy_to_table(
            table, source=io.BytesIO(data), columns=list(columns), schema_name=schema, format="text"
        )
    except asyncpg.PostgresError as error:
        return error
    return None


async def restart_identities(session: AsyncSession, schema: str) -> None:
    """Счётчики колонок идентичности и последовательностей — за максимумом принятого.

    `COPY` пишет присланные значения в обход счётчика, и без этого шага следующая
    вставка получила бы номер, который уже занят: во временной схеме — строка, которую
    подшивает миграция, в `public` — первая новая запись дела.
    """
    columns = await session.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = :schema "
            "  AND (is_identity = 'YES' OR column_default LIKE 'nextval(%')"
        ),
        {"schema": schema},
    )
    for table, column in list(columns):
        qualified = _qualified(schema, table)
        await session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:table, :column), "
                f"COALESCE((SELECT max({_ident(column)}) FROM {qualified}), 0) + 1, false)"
            ),
            {"table": qualified, "column": column},
        )


async def replace_public_from_scratch(session: AsyncSession) -> dict[str, int]:
    """Заменяет строки `public` строками временной схемы и удаляет её; число строк по таблицам.

    Обе схемы в этот момент на head, и набор таблиц у них один — иначе это ошибка кода,
    а не архива. `TRUNCATE` не задевает триггер неизменяемости записей дела: он стоит на
    `UPDATE` и `DELETE` строк, а не на опустошении таблицы.
    """
    await session.execute(text("SET LOCAL search_path TO DEFAULT"))
    public = await table_columns(session, PUBLIC_SCHEMA)
    scratch = await table_columns(session, SCRATCH_SCHEMA)
    public.pop(VERSION_TABLE, None)
    scratch.pop(VERSION_TABLE, None)
    assert public == scratch, "public and scratch schemas differ at head"

    names = ", ".join(_qualified(PUBLIC_SCHEMA, table) for table in public)
    await session.execute(text(f"TRUNCATE {names}"))
    counts: dict[str, int] = {}
    for table in await load_order(session, PUBLIC_SCHEMA, list(public)):
        columns = ", ".join(_ident(column) for column in public[table])
        result = await session.execute(
            text(
                f"INSERT INTO {_qualified(PUBLIC_SCHEMA, table)} ({columns}) "
                f"OVERRIDING SYSTEM VALUE SELECT {columns} "
                f"FROM {_qualified(SCRATCH_SCHEMA, table)}"
            )
        )
        counts[table] = result.rowcount  # type: ignore[attr-defined]
    await restart_identities(session, PUBLIC_SCHEMA)
    await session.execute(text(f"DROP SCHEMA {_ident(SCRATCH_SCHEMA)} CASCADE"))
    return counts


async def count_rows(session: AsyncSession, table: str) -> int:
    """Число строк таблицы `public`."""
    return int(
        await session.scalar(text(f"SELECT count(*) FROM {_qualified(PUBLIC_SCHEMA, table)}")) or 0
    )


def _ident(name: str) -> str:
    """Имя в двойных кавычках: имена таблиц и колонок приходят из архива и из каталога."""
    return '"' + name.replace('"', '""') + '"'


def _qualified(schema: str, table: str) -> str:
    return f"{_ident(schema)}.{_ident(table)}"
