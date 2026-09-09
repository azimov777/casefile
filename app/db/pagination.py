"""Курсорная пагинация: одна реализация на весь проект.

Соглашения требуют, чтобы любая коллекция отдавалась с курсором, а не со смещением.
Причина не в моде: `OFFSET` заставляет базу прочитать и выбросить пропускаемые строки,
а при вставке между запросами страницы начинают терять и дублировать записи.

Ключ сортировки — пара `(created_at, id)`. Второй элемент нужен обязательно: у двух
записей может совпасть время создания, и без уникального довеска они провалятся между
страницами. PostgreSQL умеет сравнивать кортежи (`(a, b) > (:x, :y)`), поэтому условие
остаётся одним выражением и ложится на составной индекс.
"""

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.db.base import BaseModel

DEFAULT_PAGE_SIZE = 50
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 200


class InvalidCursorError(ValidationError):
    """Курсор не разбирается. Ошибка механизма, а не предметной области, поэтому живёт здесь."""

    code = "invalid_cursor"
    message = "Pagination cursor is malformed"


class InvalidPageSizeError(ValidationError):
    """Запрошен размер страницы вне допустимых границ."""

    code = "invalid_page_size"
    message = "Page size is out of range"


@dataclass(frozen=True, slots=True)
class Page[ItemT]:
    """Страница выборки: сами записи и курсор на следующую.

    `next_cursor is None` означает, что дальше ничего нет — из этого же выводится
    `has_more` в ответе API, чтобы два поля не могли разойтись.
    """

    items: list[ItemT]
    next_cursor: str | None


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    """Курсор — непрозрачная для клиента строка: внутри позиция в порядке сортировки."""
    payload = json.dumps({"created_at": created_at.isoformat(), "id": str(item_id)})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Разбирает курсор. Любая порча значения — `invalid_cursor`, а не пятисотка."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except (binascii.Error, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise InvalidCursorError(details={"cursor": cursor}) from exc


# Значение ключа сортировки уезжает клиенту в курсоре и возвращается обратно
# параметром запроса, поэтому его тип надо восстановить точно: строка
# `"2026-08-28T10:00:00+00:00"`, отданная драйверу вместо `datetime`, сравнится с
# колонкой `timestamptz` не так, как ожидалось, — или не сравнится вовсе. Отсюда метка
# типа рядом с каждым значением.


def encode_sort_cursor(values: Sequence[Any], item_id: uuid.UUID) -> str:
    """Курсор страницы, упорядоченной произвольным набором ключей.

    Второй вид курсора в проекте, и он живёт здесь по тому же правилу, что и
    `encode_cursor`: разбор курсора пишется один раз. Значения ключей сортировки хранятся
    вместе с типом, потому что восстановить `datetime` из строки «по виду» нельзя, не гадая.

    `item_id` — обязательный уникальный тайбрейкер. Без него две задачи с одинаковым
    значением ключа сортировки провалились бы между страницами или задвоились.
    """
    payload = {"k": [_encode_cursor_value(value) for value in values], "id": str(item_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def decode_sort_cursor(cursor: str, *, arity: int) -> tuple[list[Any], uuid.UUID]:
    """Разбирает курсор сортировки и проверяет, что он от того же порядка.

    Расхождение длины — это курсор от другой сортировки: клиент сменил `sort` посреди
    обхода. Продолжать с ним нельзя, и молча начать сначала — тоже: страница пришла бы
    не та, о которой клиент думает. Поэтому `invalid_cursor` с указанием ожидаемой длины.
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        keys = payload["k"]
        item_id = uuid.UUID(payload["id"])
    except (binascii.Error, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise InvalidCursorError(details={"cursor": cursor}) from exc
    if not isinstance(keys, list) or len(keys) != arity:
        raise InvalidCursorError(
            details={"cursor": cursor, "reason": "sort_mismatch", "expected_keys": arity},
        )
    return [_decode_cursor_value(cursor, item) for item in keys], item_id


def _encode_cursor_value(value: Any) -> list[Any]:
    """Значение ключа сортировки с меткой типа.

    Порядок проверок важен: `bool` — подкласс `int`, а `datetime` — подкласс `date`.
    Без явного порядка `True` вернулось бы из курсора единицей, а момент времени —
    календарной датой, и страница поехала бы на границе.
    """
    match value:
        case None:
            return ["n", None]
        case bool():
            return ["b", value]
        case int():
            return ["i", value]
        case float():
            return ["f", value]
        case str():
            return ["s", value]
        case datetime():
            return ["t", value.isoformat()]
        case date():
            return ["d", value.isoformat()]
        case uuid.UUID():
            return ["u", str(value)]
        case _:
            raise InvalidCursorError(
                details={"reason": "unsupported_sort_value", "type": type(value).__name__},
            )


def _decode_cursor_value(cursor: str, item: Any) -> Any:
    try:
        tag, raw = item
    except (TypeError, ValueError) as exc:
        raise InvalidCursorError(details={"cursor": cursor}) from exc
    try:
        match tag:
            case "n":
                return None
            case "b" | "i" | "f" | "s":
                return raw
            case "t":
                return datetime.fromisoformat(raw)
            case "d":
                return date.fromisoformat(raw)
            case "u":
                return uuid.UUID(raw)
            case _:
                raise InvalidCursorError(details={"cursor": cursor, "reason": "unknown_value_tag"})
    except (TypeError, ValueError) as exc:
        raise InvalidCursorError(details={"cursor": cursor}) from exc


def resolve_limit(limit: int | None) -> int:
    """Проверяет размер страницы и подставляет значение по умолчанию.

    Выход за границы — ошибка, а не тихое срезание до потолка. Срезание выглядит
    безобиднее, но означало бы, что один и тот же запрос REST отвергает (границы
    объявлены в параметре запроса), а MCP молча выполняет по-своему. Расхождение
    интерфейсов на одном и том же входе — ровно то, что проект запрещает.
    """
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if not MIN_PAGE_SIZE <= limit <= MAX_PAGE_SIZE:
        raise InvalidPageSizeError(
            details={"limit": limit, "min": MIN_PAGE_SIZE, "max": MAX_PAGE_SIZE},
        )
    return limit


async def paginate[ModelT: BaseModel](
    session: AsyncSession,
    statement: Select[tuple[ModelT]],
    model: type[ModelT],
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[ModelT]:
    """Применяет к запросу порядок, условие курсора и лимит.

    Запрашивается на одну запись больше нужного: наличие «лишней» строки — и есть
    признак того, что следующая страница существует. Считать `COUNT(*)` ради этого
    было бы вторым проходом по тем же данным.
    """
    size = resolve_limit(limit)
    if cursor is not None:
        created_at, item_id = decode_cursor(cursor)
        statement = statement.where(tuple_(model.created_at, model.id) > (created_at, item_id))

    statement = statement.order_by(model.created_at, model.id).limit(size + 1)
    rows = list((await session.scalars(statement)).unique())

    if len(rows) <= size:
        return Page(items=rows, next_cursor=None)

    page = rows[:size]
    last = page[-1]
    return Page(items=page, next_cursor=encode_cursor(last.created_at, last.id))
