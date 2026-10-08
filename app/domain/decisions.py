"""Записи знания дела проекта и дела области — решения и заметки: статус, который
считается при чтении.

Решение — запись `decision` дела проекта (TRK#88) или дела области, заметка —
запись `finding` того же дела. Замена у них одна в обоих делах (решение TRK#57, раздел 5):
новая запись называет прежнюю того же типа в `supersedes`, и прежняя перестаёт
действовать. Отдельной сущности и хранимого статуса нет: запись действует, пока ни одна
более поздняя запись того же типа и того же дела не назвала её в `supersedes`. Так же, при
чтении, считается признак `blocked` у задачи — из связей, а не из колонки (TRK#158).
Выбор владельца — `TRK-554#6` (развилка 1а) для решений, TRK#48 — для заметок,
TRK#57 — для дела области.

Здесь только правило: из номеров, типов и `supersedes` получить преемника каждой записи.
Какие записи прочитать и как ответить на ссылку задачи, решает `app/services/decisions.py` —
домен в базу не ходит.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum

from app.domain.case import EntryType


class DecisionStatus(StrEnum):
    """Действует ли запись знания — решение или заметка дела проекта или области.

    Хранимым значением не бывает: только при чтении. Имя осталось от решений, первых
    записей с заменой; у заметки те же два значения (TRK#48).
    """

    IN_FORCE = "in_force"
    SUPERSEDED = "superseded"


def successors(entries: Iterable[tuple[int, EntryType, Sequence[int]]]) -> dict[int, int]:
    """Преемник каждой заменённой записи: номер записи → номер той, что её заменила.

    На вход — тройки «номер записи, её тип, номера, которые она заменяет» одного дела.
    Заменяет только более поздняя запись того же типа: решение — решение, заметка —
    заметку. Другое отклоняет проверка замены (`entry_fields_invalid`), и номер чужого
    типа в данных — обход проверки, а не замена.

    Заменить можно только действующую запись (`decision_not_in_force`,
    `finding_not_in_force`), поэтому у записи не больше одного преемника. Если в данных
    их всё же два — это обход проверки, а не рабочее состояние, — побеждает более раннее:
    оно заменило запись первым, а второе ссылалось на уже заменённую.
    """
    ordered = sorted(entries, key=lambda triple: triple[0])
    type_of = {no: entry_type for no, entry_type, _ in ordered}
    found: dict[int, int] = {}
    for no, entry_type, replaced in ordered:
        for old in replaced:
            if old < no and type_of.get(old) is entry_type:
                found.setdefault(old, no)
    return found


def status_of(no: int, successor_of: Mapping[int, int]) -> DecisionStatus:
    """Статус записи по уже собранной карте преемников."""
    return DecisionStatus.SUPERSEDED if no in successor_of else DecisionStatus.IN_FORCE
