"""Файлы: правила имени, типа и размера, порядок списка и карточка файла.

Файл — строка установки с байтами и историей (решение владельца TRK~8#4, итог TRK~8#5):
у него ровно один проект, имя, тип MIME, размер, sha256 и четыре отметки — кто и когда
добавил, заменил, последний раз открыл, удалил. Замена кладёт новые байты под ту же
ссылку, прежние не хранятся. Удаление стирает байты и оставляет надгробие: имя, размер,
sha256 и отметку «кто и когда удалил». Запись дела ссылается на файл и при чтении
показывает его текущую карточку — или надгробие.

Чистый Python: ни ORM, ни HTTP, ни чтения настроек. Предел размера приходит аргументом —
его значение живёт в настройках установки (`TRACKER_FILE_MAX_BYTES`).
"""

import hashlib
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from app.domain.authors import Author
from app.domain.errors import FileTooLargeError
from app.domain.fields import FieldProblem

#: Предельная длина имени и типа — под колонки таблицы `files`.
MAX_FILE_NAME_LENGTH = 255
MAX_MIME_TYPE_LENGTH = 255

#: Сколько файлов можно приложить к одной записи дела.
MAX_ENTRY_FILES = 10

#: Тип, когда клиент его не назвал.
DEFAULT_MIME_TYPE = "application/octet-stream"

#: Тип MIME по RFC 6838 в упрощённом виде: `тип/подтип`, параметры (`; charset=…`) не хранятся.
_MIME_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")

#: Знаки, которых в имени файла нет: управляющие и разделители пути.
_BAD_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f/\\]")


#: Изображения: только они получают признак «давно не открывали» (TRK~8#12). Остальное —
#: документы, которые не удаляются и не помечаются никогда.
IMAGE_MIME_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def is_image(mime_type: str) -> bool:
    """Изображение в смысле срока: PNG, JPEG, GIF или WebP."""
    return mime_type in IMAGE_MIME_TYPES


def unopened_cutoff(now: datetime, days: int) -> datetime:
    """Граница признака: не открытое с этого момента или раньше изображение — «давно»."""
    return now - timedelta(days=days)


def is_unopened(
    *,
    mime_type: str,
    added_at: datetime,
    last_opened_at: datetime | None,
    deleted: bool,
    cutoff: datetime,
) -> bool:
    """Признак «изображение давно не открывали»: вычисляется на чтении, нигде не хранится.

    Отсчёт — от последнего открытия, а у не открывавшегося файла — от добавления. У
    документа и у надгробия признака нет.
    """
    if deleted or not is_image(mime_type):
        return False
    return (last_opened_at or added_at) <= cutoff


class FileSort(StrEnum):
    """По чему упорядочен список файлов. Направление — отдельно (`descending`)."""

    ADDED = "added"
    OPENED = "opened"
    SIZE = "size"
    TYPE = "type"


@dataclass(frozen=True, slots=True)
class FileCard:
    """Карточка файла без байтов: живого или надгробия (`deleted_at` не пуст).

    У надгробия остаются имя, тип, размер и sha256 — какой файл был и что было бы
    видно на записях дела, — и кто и когда его удалил. `unopened` — признак «изображение
    давно не открывали» (срок — настройка `file_unopened_days`). Число ссылок считается на чтении:
    `entries` — записей дела, которые прикладывают файл, `tasks` — различных задач среди них.
    """

    id: uuid.UUID
    project_key: str
    name: str
    mime_type: str
    size_bytes: int
    sha256: str
    added_by: Author
    added_at: datetime
    replaced_by: Author | None
    replaced_at: datetime | None
    last_opened_at: datetime | None
    deleted_by: Author | None
    deleted_at: datetime | None
    entries: int
    tasks: int
    unopened: bool = False

    @property
    def deleted(self) -> bool:
        """«Файл удалён»: байтов нет, осталось надгробие."""
        return self.deleted_at is not None


def normalize_file_name(value: Any) -> str:
    """Имя файла: непустая строка без разделителей пути и управляющих знаков.

    Крайние пробелы снимаются; имя хранится как прислано, без смены регистра. Только имя,
    а не путь: разделитель в имени — отказ, а не молчаливая обрезка до последнего звена.
    """
    if not isinstance(value, str):
        raise FieldProblem("not_text")
    name = value.strip()
    if not name:
        raise FieldProblem("required")
    if len(name) > MAX_FILE_NAME_LENGTH:
        raise FieldProblem("too_long", max=MAX_FILE_NAME_LENGTH, got=len(name))
    if _BAD_NAME_CHARS.search(name) or name in {".", ".."}:
        raise FieldProblem("bad_characters")
    return name


def normalize_mime_type(value: Any) -> str:
    """Тип MIME: `тип/подтип` в нижнем регистре; параметры после `;` отбрасываются.

    Не назван (`None` или пустая строка) — `application/octet-stream`.
    """
    if value is None:
        return DEFAULT_MIME_TYPE
    if not isinstance(value, str):
        raise FieldProblem("not_text")
    mime = value.split(";", 1)[0].strip().lower()
    if not mime:
        return DEFAULT_MIME_TYPE
    if len(mime) > MAX_MIME_TYPE_LENGTH:
        raise FieldProblem("too_long", max=MAX_MIME_TYPE_LENGTH, got=len(mime))
    if not _MIME_RE.match(mime):
        raise FieldProblem("not_a_mime_type")
    return mime


def check_file_size(size: int, max_bytes: int) -> None:
    """Отказ `file_too_large`, если файл больше предела установки."""
    if size > max_bytes:
        raise FileTooLargeError(details={"size": size, "max_bytes": max_bytes})


def sha256_hex(data: bytes) -> str:
    """Контрольная сумма содержимого: 64 шестнадцатеричных знака."""
    return hashlib.sha256(data).hexdigest()


def normalize_file_ids(value: Any) -> list[uuid.UUID]:
    """Список файлов записи: идентификаторы без повторов, не больше `MAX_ENTRY_FILES`.

    Принимает `UUID` и строки; порядок сохраняется — это порядок вложений в записи.
    Что файлы существуют и не удалены, проверяет сценарий: домен в базу не ходит.
    """
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise FieldProblem("not_a_list")
    items = list(value)
    if len(items) > MAX_ENTRY_FILES:
        raise FieldProblem("too_many", max=MAX_ENTRY_FILES, got=len(items))
    ids: list[uuid.UUID] = []
    for position, item in enumerate(items):
        try:
            file_id = item if isinstance(item, uuid.UUID) else uuid.UUID(str(item))
        except ValueError as error:
            raise FieldProblem("not_an_id", position=position) from error
        if file_id in ids:
            raise FieldProblem("duplicate", position=position)
        ids.append(file_id)
    return ids
