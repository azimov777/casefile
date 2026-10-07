"""Архивы выпусков, менявших схему базы, принимаются в head без потерь (TRK-653).

Тесты миграций проверяют каждую на своём шаге, а тесты архива собирают старый архив
руками из данных head (`test_archive.py`, `archive_at`). Миграция, которая ломает строку,
бывшую только в старой схеме, прошла бы оба набора зелёной (Д4 из TRK-648#12). Здесь
данные — настоящие: в `tests/data/` лежит по архиву переноса на каждый выпуск, сменивший
схему (`archive-<тег>.json`). Это демо-данные, снятые на теге кодом того выпуска.

Каждый архив принимается в пустую установку тем же `POST /api/v1/installation/archive`,
что у человека: миграции доводят его от ревизии выпуска до head одной транзакцией. Затем
идёт сверка строка за строкой по `id`. Отпечаток строки — все её значения в текстовой
форме Postgres, той же, в какой их везёт архив. Каждая строка архива обязана стоять в
установке с теми же значениями. Исключения — перемены, которые миграции и правило
приёма делают намеренно (`_intended`), и строки, которые они добавляют (`_added`). Всё
прочее — потеря.

Архив выпуска снимает `scripts/snapshot-release-archive.sh <тег>`. Выпуск, меняющий
схему, добавляет свой архив (решение проекта TRK#49).
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import archive as store
from app.services.archive import MACHINE_KEY_NAMES
from test_archive import (
    ARCHIVE,
    DROPPED_COLUMNS,
    RENAMED_COLUMNS,
    RENAMED_TABLES,
    bearer,
    fresh_installation,
    wipe,
)

DATA = Path(__file__).parent / "data"
SNAPSHOT = Path(__file__).resolve().parents[1] / "scripts" / "snapshot-release-archive.sh"

Row = dict[str, str | None]


def _release(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in path.stem.removeprefix("archive-v").split("."))


#: Архивы выпусков по возрастанию версии.
ARCHIVES = sorted(DATA.glob("archive-v*.json"), key=_release)

# Ревизии миграций, которые меняют строки старых выпусков намеренно. Литералы, а не
# поиск по тексту миграций: тест держит то, что обещано людям с их данными.
#: Описание длиннее предела — в запись дела проекта «Описание до v0.4.0» (TRK-158).
LONG_DESCRIPTIONS = "b7d2f94c0e15"
#: Предел описания на той ревизии — литерал, как в самой миграции.
MAX_DESCRIPTION_LENGTH = 320
#: Ключи людей отозваны: человек входит паролем, ключи — агентам (TRK-469).
REVOKE_HUMAN_KEYS = "9e2c6b4f1a83"
#: Статус `waiting` снят: задача встаёт в `open` с записью `status_changed` (TRK-573).
DROP_WAITING = "a9cb1ec147c4"
#: Вопросы — в обсуждения: открытый вопрос дела задачи получает `answer` с исходом
#: `withdrawn` от трекера (TRK-671, решение TRK#51, п. 6).
WITHDRAW_TASK_QUESTIONS = "3b9f4d192289"
#: Тело такого ответа — литерал, как в самой миграции.
WITHDRAWN_BODY = (
    "Вопрос закрыт: вопросы теперь задаются в обсуждениях. "
    "Агенту — переспросить через обсуждение."
)


@dataclass(frozen=True, slots=True)
class Before:
    """Архив, каким его надо найти в head: строки по `id` под нынешними именами."""

    #: Таблица head → строки архива по `id`, колонки — под именами head.
    tables: dict[str, dict[str, Row]]
    #: Ревизии, которые приём прогоняет поверх архива.
    applied: frozenset[str]

    def rows(self, table: str) -> dict[str, Row]:
        return self.tables.get(table, {})


def _load(path: Path) -> dict[str, Any]:
    archive: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return archive


def _applied(revision: str) -> frozenset[str]:
    """Ревизии, которые приём прогоняет поверх архива этой ревизии, до head."""
    script = ScriptDirectory.from_config(store._alembic_config())
    return frozenset(
        step.revision
        for step in script.iterate_revisions(store.head_revision(), revision)
        if step.revision != revision
    )


def _rows(columns: list[str], rows: list[list[str | None]]) -> dict[str, Row]:
    keyed = [dict(zip(columns, row, strict=True)) for row in rows]
    by_id = {str(row["id"]): row for row in keyed if row["id"] is not None}
    assert len(by_id) == len(keyed), "a row without a unique id cannot be traced"
    return by_id


def _before(archive: dict[str, Any], present: dict[str, tuple[str, ...]]) -> Before:
    """Строки архива под именами head; колонка, пропавшая без объявления, — отказ сразу."""
    tables: dict[str, dict[str, Row]] = {}
    for table in archive["tables"]:
        name = table["name"]
        target = RENAMED_TABLES.get(name, name)
        assert target in present, f"table {name} of the archive is gone at head"
        renamed = {
            column: RENAMED_COLUMNS.get((name, column), column)
            for column in table["columns"]
            if (name, column) not in DROPPED_COLUMNS
        }
        gone = [column for column in renamed.values() if column not in present[target]]
        assert not gone, f"columns {gone} of {name} are gone at head"
        tables[target] = {
            key: {renamed[column]: value for column, value in row.items() if column in renamed}
            for key, row in _rows(table["columns"], table["rows"]).items()
        }
    return Before(tables=tables, applied=_applied(archive["schema_revision"]))


def _long(project: Row) -> bool:
    return len(project["description"] or "") > MAX_DESCRIPTION_LENGTH


def _intended(table: str, column: str, before: Row, after: Row, archive: Before) -> bool:
    """Перемена значения, которую миграции и правило приёма делают намеренно."""
    if table == "tasks" and DROP_WAITING in archive.applied and before["status"] == "waiting":
        # Ждущая задача встаёт в `open`, версия карточки растёт.
        return column in {"status", "version", "updated_at"} and after["status"] == "open"
    if table == "projects" and LONG_DESCRIPTIONS in archive.applied and _long(before):
        # Поле пустеет, текст уезжает записью в дело проекта (`_added`).
        return column in {"description", "updated_at"} and after["description"] == ""
    if table != "tokens" or before["revoked_at"] is not None or after["revoked_at"] is None:
        return False
    if before["name"] in MACHINE_KEY_NAMES:
        # Одноимённые ключи машины источника отзываются при приёме (CONCEPT.md, 5.5).
        return column in {"revoked_at", "updated_at"}
    owner = archive.rows("participants").get(str(before["participant_id"]))
    return (
        column == "revoked_at"
        and REVOKE_HUMAN_KEYS in archive.applied
        and owner is not None
        and owner["kind"] == "human"
        and after["kind"] == "key"
    )


def _open_task_questions(archive: Before) -> set[tuple[str, int]]:
    """Вопросы дел задач без ответа в архиве — по задаче и номеру: их снимает миграция."""
    entries = archive.rows("entries").values()
    answered = {
        (str(row["task_id"]), int(json.loads(row["payload"] or "{}")["question_no"]))
        for row in entries
        if row["type"] == "answer" and row["task_id"] is not None
    }
    return {
        (str(row["task_id"]), int(str(row["no"])))
        for row in entries
        if row["type"] == "question" and row["task_id"] is not None
    } - answered


def _added(table: str, row: Row, archive: Before) -> bool:
    """Строка, которой нет в архиве, но которую обязаны добавить приём или миграции."""
    if table == "tokens":
        # Ключи машины приёмника переживают приём (CONCEPT.md, 5.5).
        return row["name"] in MACHINE_KEY_NAMES and row["revoked_at"] is None
    if table != "entries" or row["created_by_kind"] != "tracker":
        return False
    if WITHDRAW_TASK_QUESTIONS in archive.applied and row["type"] == "answer":
        payload = json.loads(row["payload"] or "{}")
        question = (str(row["task_id"]), payload.get("question_no"))
        return (
            payload.get("outcome") == "withdrawn"
            and row["body"] == WITHDRAWN_BODY
            and question in _open_task_questions(archive)
        )
    task = archive.rows("tasks").get(str(row["task_id"]))
    if task is not None and DROP_WAITING in archive.applied and task["status"] == "waiting":
        return row["type"] == "status_changed" and row["title"] == (
            "Status changed: waiting -> open"
        )
    project = archive.rows("projects").get(str(row["project_id"]))
    if project is not None and LONG_DESCRIPTIONS in archive.applied and _long(project):
        return (row["type"], row["title"], row["body"]) == (
            "note",
            "Описание до v0.4.0",
            project["description"],
        )
    return False


def test_every_archive_is_a_distinct_release_on_the_migration_line() -> None:
    """Архивы идут по линии миграций в порядке выпусков, по одному на ревизию.

    Ревизия, которой head не знает, — архив не того репозитория; ревизии не по порядку
    выпусков — перепутанные теги; одна ревизия дважды — выпуск, который схему не менял.
    """
    assert ARCHIVES, "tests/data has no release archives"
    revisions = [_load(path)["schema_revision"] for path in ARCHIVES]
    assert all(store.is_known_revision(revision) for revision in revisions), revisions
    assert len(set(revisions)) == len(revisions), revisions
    for older, newer in pairwise(revisions):
        assert newer in _applied(older), f"{newer} does not follow {older}"


@pytest.mark.parametrize("path", ARCHIVES, ids=lambda path: path.stem.removeprefix("archive-"))
async def test_a_release_archive_comes_into_head_whole(
    client: AsyncClient, db_session: AsyncSession, path: Path
) -> None:
    archive = _load(path)
    await wipe(db_session)
    ui_secret, _ = await fresh_installation(db_session)

    response = await client.post(ARCHIVE, json={"data": archive}, headers=bearer(ui_secret))

    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert (report["schema_revision"], report["head_revision"]) == (
        archive["schema_revision"],
        store.head_revision(),
    )

    await store.use_utc(db_session)
    present = await store.table_columns(db_session, store.PUBLIC_SCHEMA)
    before = _before(archive, present)
    lost: list[str] = []
    changed: list[str] = []
    stray: list[str] = []
    stored: dict[str, dict[str, Row]] = {}
    for table, archived in before.tables.items():
        columns = present[table]
        rows = await store.read_rows(db_session, store.PUBLIC_SCHEMA, table, columns)
        stored[table] = _rows(list(columns), rows)
        for key, was in archived.items():
            now = stored[table].get(key)
            if now is None:
                lost.append(f"{table} {key}")
                continue
            changed += [
                f"{table}.{column} {key}: {value!r} -> {now[column]!r}"
                for column, value in was.items()
                if now[column] != value and not _intended(table, column, was, now, before)
            ]
        stray += [
            f"{table} {key}: {row}"
            for key, row in stored[table].items()
            if key not in archived and not _added(table, row, before)
        ]

    assert not lost, f"rows of the archive lost on the way to head: {lost}"
    assert not changed, f"values changed on the way to head: {changed}"
    assert not stray, f"rows nobody asked for: {stray}"
    assert len(stored["tasks"]) == len(before.rows("tasks"))
    waiting = [task for task in before.rows("tasks").values() if task["status"] == "waiting"]
    long = [project for project in before.rows("projects").values() if _long(project)]
    withdrawn = (
        _open_task_questions(before) if WITHDRAW_TASK_QUESTIONS in before.applied else set()
    )
    added = (
        (len(waiting) if DROP_WAITING in before.applied else 0)
        + (len(long) if LONG_DESCRIPTIONS in before.applied else 0)
        + len(withdrawn)
    )
    assert len(stored["entries"]) == len(before.rows("entries")) + added
    # Открытых вопросов в делах задач после приёма не остаётся (TRK-671).
    assert not _open_task_questions(Before(tables=stored, applied=before.applied))


def test_the_snapshot_script_runs_and_writes_where_this_test_reads() -> None:
    """Скрипт пересъёмки с битом запуска, разбирается и кладёт архив туда, где его ищут."""
    assert os.access(SNAPSHOT, os.X_OK), f"{SNAPSHOT} без бита запуска"
    bash = shutil.which("bash")
    assert bash is not None, "в образе нет bash — проверить синтаксис нечем"
    parsed = subprocess.run([bash, "-n", str(SNAPSHOT)], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
    assert "$root/tests/data/archive-$tag.json" in SNAPSHOT.read_text(encoding="utf-8")


@pytest.mark.parametrize("project", ["tracker", "casefile"])
def test_the_snapshot_script_keeps_off_the_owners_installations(project: str) -> None:
    """Проект compose `tracker` — дев-контур владельца, `casefile` — его установка.

    `down -v` скрипта унёс бы их базу, поэтому отказ — первым шагом, до git и Docker.
    """
    bash = shutil.which("bash")
    assert bash is not None
    refused = subprocess.run(
        [bash, str(SNAPSHOT), "v0.2.0"],
        capture_output=True,
        text=True,
        env={**os.environ, "SNAPSHOT_PROJECT": project},
    )
    assert refused.returncode == 2, refused.stderr
    assert project in refused.stderr
