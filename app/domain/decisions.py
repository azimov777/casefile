"""Решения проекта: статус, который считается при чтении (`CONCEPT.md`, 3.2).

Решение проекта — запись `decision` дела проекта. Отдельной сущности и хранимого статуса
нет: решение действует, пока ни одно более позднее решение того же проекта не назвало его
в `supersedes`. Так же, при чтении, считается признак `blocked` у задачи — из связей, а не
из колонки (`CONCEPT.md`, 4.3). Выбор владельца — `TRK-554#6` (развилка 1а).

Здесь только правило: из номеров и `supersedes` получить преемника каждого решения. Какие
записи прочитать и как ответить на ссылку задачи, решает `app/services/decisions.py` —
домен в базу не ходит.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum


class DecisionStatus(StrEnum):
    """Действует ли решение проекта. Хранимым значением не бывает: только при чтении."""

    IN_FORCE = "in_force"
    SUPERSEDED = "superseded"


def successors(decisions: Iterable[tuple[int, Sequence[int]]]) -> dict[int, int]:
    """Преемник каждого заменённого решения: номер решения → номер того, что его заменило.

    На вход — пары «номер решения, номера, которые оно заменяет». Заменить можно только
    действующее решение (`decision_not_in_force`), поэтому у решения не больше одного
    преемника. Если в данных их всё же два — это обход проверки, а не рабочее состояние, —
    побеждает более раннее: оно заменило решение первым, а второе ссылалось на уже
    заменённое.
    """
    found: dict[int, int] = {}
    for no, replaced in sorted(decisions, key=lambda pair: pair[0]):
        for old in replaced:
            if old < no:
                found.setdefault(old, no)
    return found


def status_of(no: int, successor_of: Mapping[int, int]) -> DecisionStatus:
    """Статус решения по уже собранной карте преемников."""
    return DecisionStatus.SUPERSEDED if no in successor_of else DecisionStatus.IN_FORCE
