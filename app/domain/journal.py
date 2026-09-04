"""Лента журнала: границы ожидания, фильтр хвоста и разбор курсора потока.

Отдельной таблицы событий в трекере нет: журнал всех записей дела и есть лента для
внешнего мира, а сквозной номер `seq` — её курсор (`CONCEPT.md`, 4.1). Здесь лежит то,
что можно проверить и посчитать без базы, — и потому одинаково для REST, для потока SSE
и для инструмента MCP (задача 28).

## Почему потолок ожидания объявлен дважды

`MAX_WAIT_SECONDS` попадает и в схему параметра запроса (`le=` у `wait`), и в проверку
`resolve_wait`. Это не дубль по недосмотру, а то же правило, что у размера страницы
(`app/db/pagination.py`, `resolve_limit`): параметр запроса даёт потолок в OpenAPI и
отсекает мусор на входе, а проверка в домене работает для MCP, который мимо FastAPI не
проходит. Разойтись им негде — обе стороны читают эту константу.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.case import EntryType
from app.domain.errors import InvalidJournalCursorError, JournalWaitTooLongError

#: Номер, с которого начинается журнал. `seq` выдаётся с единицы, поэтому «ничего ещё
#: не читал» — это ноль, а не `None`: у курсора ленты нет состояния «неизвестно».
JOURNAL_START = 0

#: Ожидание по умолчанию: не ждать. Лента прежде всего читается хвостом, и вызов,
#: молча висящий полминуты, был бы неожиданностью для того, кто просто листает журнал.
DEFAULT_WAIT_SECONDS = 0.0

#: Потолок долгого ожидания. Ограничение существует не ради базы — ждущий соединение не
#: держит, — а ради прокси и клиентов: запрос, висящий дольше минуты, обрывается
#: где-нибудь по дороге, и обрыв неотличим от «ничего не случилось».
MAX_WAIT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class JournalFilter:
    """Чем сужен хвост журнала. Один и тот же у ленты и у потока.

    Хранит идентификаторы, а не ключи и не объекты ORM: поток живёт часами и переживает
    десятки сессий, а отсоединённая от сессии задача — источник ленивой загрузки в самом
    неудобном месте. Разрешает ключи в идентификаторы сценарий
    (`app/services/journal.py`, `resolve_filter`), потому что для этого нужна база.

    `types is None` — «все типы», `types == ()` — «ни одного»: клиент, отобравший
    нулевой набор типов, обязан получить пустую ленту, а не всю.
    """

    task_id: uuid.UUID | None = None
    queue_id: uuid.UUID | None = None
    types: tuple[EntryType, ...] | None = None


def resolve_wait(seconds: float | None) -> float:
    """Проверяет запрошенное ожидание и подставляет значение по умолчанию.

    Выход за потолок — отказ, а не срезание: попросивший десять минут и получивший
    минуту истолковал бы пустой ответ как «за десять минут ничего не произошло».
    Отрицательное значение — то же самое ожидание, что и ноль, но просить его нельзя:
    молча исправленный запрос скрывает ошибку в клиенте.
    """
    if seconds is None:
        return DEFAULT_WAIT_SECONDS
    if seconds < 0 or seconds > MAX_WAIT_SECONDS:
        raise JournalWaitTooLongError(
            details={"wait": seconds, "min": 0, "max": MAX_WAIT_SECONDS},
        )
    return float(seconds)


def parse_last_event_id(raw: str | None) -> int | None:
    """Разбирает `Last-Event-ID` потока — сквозной номер последней принятой записи.

    Кадр потока несёт `seq` в поле `id:`, поэтому обратно приезжает то же число.
    Несуществующий номер законен и отказом не является: записи постоянны, догнать можно
    с любого номера, а «слишком старого» курсора у ленты не бывает — в отличие от
    очереди событий, которую чистили по сроку хранения.

    Отказ здесь ровно один — значение, которое не является неотрицательным целым.
    Молча начать поток с конца в этом случае нельзя: клиент решил бы, что за время
    обрыва ничего не случилось.
    """
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise InvalidJournalCursorError(details={"last_event_id": raw}) from exc
    if value < JOURNAL_START:
        raise InvalidJournalCursorError(
            details={"last_event_id": raw, "reason": "negative", "min": JOURNAL_START},
        )
    return value


def resolve_after(after: int | None, cursor_seq: int | None) -> int:
    """Позиция, с которой читается хвост: побеждает больший из двух источников.

    Источника два, и они не дубль. `after` задаёт клиент — это его курсор ленты, тот же
    номер, что уезжает в `id:` кадра потока. `cursor` приезжает из `meta.next_cursor`
    предыдущей страницы и продолжает обход. Действуют оба сразу: больший означает «уже
    прочитано дальше», и откатывать чтение назад молча нельзя — страница пришла бы не
    та, о которой клиент думает.
    """
    candidates = [value for value in (after, cursor_seq) if value is not None]
    return max(candidates) if candidates else JOURNAL_START


def resolve_types(types: Sequence[EntryType] | None) -> tuple[EntryType, ...] | None:
    """Набор типов ленты. `None` остаётся `None`, список превращается в кортеж.

    Кортеж, а не список: фильтр — значение, которое поток носит с собой часами, и
    изменяемый список в нём означал бы фильтр, который может поменяться по дороге.
    """
    return None if types is None else tuple(types)
