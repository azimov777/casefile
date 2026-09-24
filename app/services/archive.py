"""Перенос установки: выгрузка архива и его приём в пустую установку (TRK-100).

Человек забирает свои дела на другую машину или на свой сервер без shell и без
знания Postgres: одна выгрузка и один приём по запросу (`docs/moving.md`). Ничего по
расписанию: трекер копий не хранит, это операция человека, а не автоматика
(`docs/CONCEPT.md`, «Принципы»). Ручная процедура оператора с shell (`pg_dump`,
`docs/backup-restore.md`) остаётся рядом как есть — она про копию базы, а не про переезд.

## Кто вправе

Обе операции открыты только администратору (`ensure_admin`): в архиве хеши паролей
всех людей и хеши всех токенов, а приём заменяет людей установки (`docs/CONCEPT.md`,
5.4). MCP их не знает: перенос — действие человека.

## Что едет и что нет

Едет всё, что лежит в таблицах, кроме названного в `app/domain/archive.py`:
таблицы версии и ключей идемпотентности, и токенов сеансов браузера — кука сеанса
принадлежит адресу источника и на приёмник не попадёт никогда (`SESSION_COLUMN`).
Учётные записи едут с хешами паролей — человек входит той же почтой и тем же паролем;
токены агентов едут с хешами — агент подключается тем же токеном (как в TRK-96).

## Ключи машины приёмника переживают приём

Интерфейс приёмника держит свой ключ `local-ui` в томе, агент этой машины — свой
`local-agent` (`app/services/setup.py`). Приём заменил бы их строки строками источника,
и интерфейс потерял бы доступ до следующего подъёма контура. Поэтому их строки
переподшиваются к участнику архива с тем же именем — а если такого в архиве нет,
переезжает и сам участник приёмника. Одноимённые ключи источника отзываются: их
секреты лежат в томах другой машины. Ключу интерфейса, как и при подъёме, достаётся
учётная запись администратора (`ensure_admin_account`): у архива, снятого до учётных
записей, её нет.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import archive as store
from app.db.locks import lock_changes
from app.db.models.account import Account
from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.token import Token
from app.db.repositories import ParticipantRepository
from app.domain.archive import (
    ARCHIVE_FORMAT_VERSION,
    EXCLUDED_TABLES,
    Archive,
    ArchiveFormat,
    ArchiveTable,
    check_archive,
    copy_text,
)
from app.domain.errors import (
    ArchiveInvalidError,
    ArchiveRevisionUnknownError,
    InstallationNotEmptyError,
)
from app.services.accounts import ensure_admin
from app.services.auth import Actor
from app.services.setup import (
    DEFAULT_AGENT_TOKEN_NAME,
    DEFAULT_LOCAL_TOKEN_NAME,
    ensure_admin_account,
)

#: Колонка токена, заполненная только у сеанса браузера (`Token.is_session`): строки,
#: где она не пуста, не выгружаются.
SESSION_COLUMN = "expires_at"

#: Ключи машины: токены, секреты которых установка держит в своих томах.
MACHINE_KEY_NAMES = (DEFAULT_LOCAL_TOKEN_NAME, DEFAULT_AGENT_TOKEN_NAME)


async def export_installation(session: AsyncSession, *, actor: Actor) -> Archive:
    """Архив установки целиком, снятый в одной точке времени.

    Очередь изменений (`lock_changes`) держит все пишущие сценарии, пока идёт чтение:
    иначе запись дела, подшитая между чтением задач и записей, дала бы архив, которого
    никогда не было.
    """
    await ensure_admin(session, actor, action="installation.export")
    await lock_changes(session)
    # Строки читаются сырым SQL мимо сессии: несохранённое в ней должно быть в базе.
    await session.flush()
    await store.use_utc(session)

    revision = await store.current_revision(session)
    tables: list[ArchiveTable] = []
    for name, columns in (await store.table_columns(session, store.PUBLIC_SCHEMA)).items():
        if name in EXCLUDED_TABLES:
            continue
        only_null = SESSION_COLUMN if name == Token.__tablename__ else None
        rows = await store.read_rows(
            session, store.PUBLIC_SCHEMA, name, columns, only_null=only_null
        )
        tables.append(ArchiveTable(name=name, columns=columns, rows=rows))
    return Archive(
        format=ArchiveFormat.INSTALLATION,
        format_version=ARCHIVE_FORMAT_VERSION,
        schema_revision=revision,
        app_version=__version__,
        exported_at=datetime.now(UTC),
        tables=tuple(tables),
    )


@dataclass(frozen=True, slots=True)
class ImportedTable:
    """Сколько строк таблицы стоит в установке после приёма."""

    name: str
    rows: int


@dataclass(frozen=True, slots=True)
class ArchiveImport:
    """Итог приёма: что принято, до какой ревизии доведено, что стало с доступами."""

    schema_revision: str
    head_revision: str
    tables: tuple[ImportedTable, ...]
    #: Сколько строк приёмника заменено архивом — его участники, токены и учётные записи
    #: до приёма. Всё это теперь из архива, кроме ключей машины (`machine_keys`).
    replaced: Mapping[str, int]
    #: Имена ключей машины приёмника, переживших приём.
    machine_keys: tuple[str, ...]
    #: Сколько одноимённых ключей источника отозвано.
    revoked_source_keys: int


@dataclass(frozen=True, slots=True)
class _MachineKey:
    """Строка ключа машины и строка его участника — как они лежали у приёмника."""

    token: dict[str, Any]
    participant: dict[str, Any]


async def import_installation(
    session: AsyncSession, *, actor: Actor, archive: Archive
) -> ArchiveImport:
    """Заменяет данные пустой установки архивом, доводя его схему до head.

    Отказы: форма документа (`archive_format_unsupported`, `archive_invalid`), архив
    новее приёмника (`archive_revision_unknown`), у приёмника есть проекты
    (`installation_not_empty`). Любой отказ — в том числе строка, которую не принял
    Postgres, — не оставляет в приёмнике ничего: всё идёт одной транзакцией вызывающего.
    """
    await ensure_admin(session, actor, action="installation.import")
    check_archive(archive)
    await lock_changes(session)

    head = store.head_revision()
    if not store.is_known_revision(archive.schema_revision):
        raise ArchiveRevisionUnknownError(
            details={"schema_revision": archive.schema_revision, "head": head}
        )
    projects = await session.scalar(select(func.count()).select_from(Project)) or 0
    if projects:
        raise InstallationNotEmptyError(details={"projects": projects})

    machine_keys = await _machine_keys(session)
    replaced = {
        table: await store.count_rows(session, table)
        for table in (Participant.__tablename__, Token.__tablename__, Account.__tablename__)
    }
    # Всё, что сессия держит несохранённым (отметку использования токена запроса), уходит
    # в базу сейчас: после замены строк такой `UPDATE` не нашёл бы свою строку.
    await session.flush()

    await store.build_scratch(session, archive.schema_revision)
    await _load(session, archive)
    await store.restart_identities(session, store.SCRATCH_SCHEMA)
    await store.upgrade_scratch(session, "head")
    counts = await store.replace_public_from_scratch(session)
    # Объекты, прочитанные до замены, описывают строки, которых больше нет.
    session.expunge_all()

    revoked = await _restore_machine_keys(session, machine_keys)
    # Пересчёт, а не число перенесённых строк: ключи машины и учётная запись администратора
    # легли после переноса, и ответ называет то, что в установке стоит теперь.
    return ArchiveImport(
        schema_revision=archive.schema_revision,
        head_revision=head,
        tables=tuple(
            [
                ImportedTable(name=name, rows=await store.count_rows(session, name))
                for name in counts
            ]
        ),
        replaced=replaced,
        machine_keys=tuple(sorted({key.token["name"] for key in machine_keys})),
        revoked_source_keys=revoked,
    )


async def _load(session: AsyncSession, archive: Archive) -> None:
    """Строки архива — во временную схему, сверив таблицы и колонки со схемой ревизии."""
    expected = {
        name: columns
        for name, columns in (await store.table_columns(session, store.SCRATCH_SCHEMA)).items()
        if name not in EXCLUDED_TABLES
    }
    given = {table.name: table for table in archive.tables}
    for name in given.keys() - expected.keys():
        raise ArchiveInvalidError(details={"table": name, "reason": "unknown_table"})
    for name in expected.keys() - given.keys():
        raise ArchiveInvalidError(details={"table": name, "reason": "missing_table"})
    for name, table in given.items():
        if set(table.columns) != set(expected[name]):
            raise ArchiveInvalidError(
                details={
                    "table": name,
                    "reason": "column_mismatch",
                    "expected": list(expected[name]),
                    "actual": list(table.columns),
                }
            )

    for name in await store.load_order(session, store.SCRATCH_SCHEMA, list(given)):
        table = given[name]
        if not table.rows:
            continue
        error = await store.copy_rows(
            session, store.SCRATCH_SCHEMA, name, table.columns, copy_text(table.rows)
        )
        if error is not None:
            raise ArchiveInvalidError(
                details={"table": name, "reason": "rejected_row", "error": str(error)}
            )


async def _machine_keys(session: AsyncSession) -> list[_MachineKey]:
    """Неотозванные ключи машины приёмника со строками их участников."""
    tokens = Token.__table__
    participants = Participant.__table__
    rows = await session.execute(
        select(tokens).where(
            tokens.c.name.in_(MACHINE_KEY_NAMES),
            tokens.c.revoked_at.is_(None),
            tokens.c.expires_at.is_(None),
            tokens.c.participant_id.is_not(None),
        )
    )
    keys: list[_MachineKey] = []
    for token in rows.mappings():
        participant = (
            (
                await session.execute(
                    select(participants).where(participants.c.id == token["participant_id"])
                )
            )
            .mappings()
            .one()
        )
        keys.append(_MachineKey(token=dict(token), participant=dict(participant)))
    return keys


async def _restore_machine_keys(session: AsyncSession, keys: Sequence[_MachineKey]) -> int:
    """Возвращает ключи машины приёмника; сколько одноимённых ключей источника отозвано."""
    tokens = Token.__table__
    revoked = 0
    if keys:
        result = await session.execute(
            update(tokens)
            .where(
                tokens.c.name.in_({key.token["name"] for key in keys}),
                tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        revoked = result.rowcount  # type: ignore[attr-defined]

    repository = ParticipantRepository(session)
    for key in keys:
        participant = await repository.get_by_name(key.participant["name"])
        if participant is None:
            await session.execute(insert(Participant.__table__).values(**key.participant))
            participant = await repository.get_by_name(key.participant["name"])
            assert participant is not None  # только что вставлен
        await session.execute(
            insert(tokens).values(**{**key.token, "participant_id": participant.id})
        )
        if key.token["name"] == DEFAULT_LOCAL_TOKEN_NAME:
            await ensure_admin_account(session, participant)
    return revoked
