"""Архив установки: форма документа, что в него не входит, и строка `COPY` из его значений.

Архив — это строки таблиц базы в текстовой форме Postgres, с именами колонок и ревизией
схемы, на которой их сняли (`docs/moving.md`, TRK-100). Форма не знает ни одной таблицы
поимённо, кроме исключённых ниже: таблицы и колонки приезжают из самой базы, а типы
значений разбирает Postgres при приёме. Поэтому одна и та же форма годится для архива,
снятого на любой ревизии схемы, и выгрузка одного пространства (TRK-107) станет отбором
строк по колонке, а не новым форматом.

Зачем текстовая форма, а не JSON-типы: `col::text` и ввод `COPY ... FROM STDIN` —
пара функций вывода и ввода одного типа, и значение проходит через неё без потерь,
каким бы тип ни был (`timestamptz`, `jsonb`, `uuid`, `bigint`). Перевод в типы JSON
потребовал бы знать тип каждой колонки на каждой ревизии.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.errors import ArchiveFormatUnsupportedError, ArchiveInvalidError
from app.domain.tasks import TASK_KEY_SEPARATOR
from app.domain.tutorial import TUTORIAL_PROJECT_KEY


class ArchiveFormat(StrEnum):
    """Что за документ перед нами. Значение одно: других архивов у трекера нет."""

    INSTALLATION = "casefile.installation-archive"


#: Версия раскладки самого документа — `tables`, `columns`, `rows`, текстовые значения.
#: Схема базы тут ни при чём: её называет `schema_revision`, и разные ревизии архив
#: переживает миграциями приёмника. Версия растёт, только если меняется раскладка.
ARCHIVE_FORMAT_VERSION = 1

#: Таблицы, которых в архиве нет никогда, с причиной.
EXCLUDED_TABLES: dict[str, str] = {
    "alembic_version": (
        "The archive names its schema revision in schema_revision; the receiving "
        "installation keeps its own version table"
    ),
    "idempotency_keys": (
        "Kept for a day with whole responses of creating calls, and the response to issuing "
        "a token holds its secret (app/db/models/idempotency.py)"
    ),
}


#: Проекты, которых в архиве нет, по ключу, с причиной. Вместе с проектом не едут все
#: строки, что ссылаются на него внешним ключом, прямо или через другие: его задачи,
#: их дела и связи — в том числе связи с задачами других проектов, — дело и атрибуты
#: проекта (`app/services/archive.py`).
EXCLUDED_PROJECTS: dict[str, str] = {
    TUTORIAL_PROJECT_KEY: (
        "The tutorial project the installation seeds for itself, recognized by its key "
        "(TRK-384); the receiving installation seeds its own. A project START made by a "
        "person before 0.6.0 stays behind too: the owner accepted this risk"
    ),
}


def without_excluded_keys(previous_keys: str | None) -> str | None:
    """Прежние ключи задачи (текст `jsonb`) без ключей исключённых проектов.

    Задача, унесённая из `START` в другой проект, помнит `START-N`. На приёмнике
    `START` нет, и засев, заведя его заново, выдал бы `START-1` второй раз — ключ,
    которым уже названа эта задача (`CONCEPT.md`, 3.3: ключ одной задачи другой не
    выдаётся). Остальные прежние ключи и их порядок остаются; значение без таких ключей
    возвращается как было, байт в байт.
    """
    if previous_keys is None:
        return None
    keys = json.loads(previous_keys)
    kept = [key for key in keys if key.rpartition(TASK_KEY_SEPARATOR)[0] not in EXCLUDED_PROJECTS]
    return previous_keys if len(kept) == len(keys) else json.dumps(kept, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class ArchiveTable:
    """Строки одной таблицы: значения в порядке `columns`, `None` — это `NULL`."""

    name: str
    columns: tuple[str, ...]
    rows: Sequence[Sequence[str | None]]


@dataclass(frozen=True, slots=True)
class Archive:
    """Архив целиком: откуда он и что в нём."""

    format: ArchiveFormat
    format_version: int
    schema_revision: str
    app_version: str
    exported_at: datetime
    tables: tuple[ArchiveTable, ...]


def check_archive(archive: Archive) -> None:
    """Отказ, если документ не архив этой раскладки или сам себе противоречит.

    Проверяется форма, а не соответствие схеме: какие таблицы и колонки должны быть на
    ревизии архива, знает только база приёмника (`app/services/archive.py`).
    """
    if archive.format is not ArchiveFormat.INSTALLATION or (
        archive.format_version != ARCHIVE_FORMAT_VERSION
    ):
        raise ArchiveFormatUnsupportedError(
            details={
                "format": str(archive.format),
                "format_version": archive.format_version,
                "supported": {
                    "format": ArchiveFormat.INSTALLATION.value,
                    "format_version": ARCHIVE_FORMAT_VERSION,
                },
            }
        )
    seen: set[str] = set()
    for table in archive.tables:
        if table.name in seen:
            raise ArchiveInvalidError(details={"table": table.name, "reason": "duplicate_table"})
        seen.add(table.name)
        if table.name in EXCLUDED_TABLES:
            raise ArchiveInvalidError(details={"table": table.name, "reason": "excluded_table"})
        if len(set(table.columns)) != len(table.columns) or not table.columns:
            raise ArchiveInvalidError(details={"table": table.name, "reason": "bad_columns"})
        width = len(table.columns)
        for index, row in enumerate(table.rows):
            if len(row) != width:
                raise ArchiveInvalidError(
                    details={
                        "table": table.name,
                        "row": index,
                        "reason": "row_width",
                        "expected": width,
                        "actual": len(row),
                    }
                )


def copy_text(rows: Iterable[Sequence[str | None]]) -> bytes:
    """Строки в текстовом формате `COPY ... FROM STDIN` (разделитель — табуляция).

    Экранируются ровно четыре символа, которые формат иначе прочёл бы как разметку:
    обратная косая черта, табуляция, перевод строки и возврат каретки; `NULL` — это `\\N`.
    Остальное Postgres читает как есть, и значение, полученное `col::text`, возвращается
    в колонку тем же значением (документация Postgres, `COPY`, «Text Format»).
    """
    lines = ["\t".join(_copy_field(value) for value in row) + "\n" for row in rows]
    return "".join(lines).encode()


def _copy_field(value: str | None) -> str:
    if value is None:
        return "\\N"
    return (
        value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    )
