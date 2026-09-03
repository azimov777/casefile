"""Дело: закрытый словарь типов записей и форма ссылки на запись.

Дело — упорядоченный список неизменяемых записей (`CONCEPT.md`, 3.4). Здесь только то,
что не зависит от базы: типы записей и формат ссылки `TRK-42#12`. Форма записи (`seq`,
`no`, автор, заголовок, тело, `payload`, `refs`) описана моделью в `app/db/models/entry.py`,
а правила по каждому типу агента (`summary`, `question`, `verdict`, ...) — задача 23.

## Словарь закрыт

Соглашения требуют держать типы записей одним перечислением и не заводить новых по
месту: новый тип записи — это изменение концепции, а не задачи. Тип служебной записи
при этом выводится из сценария в `services`, а не задаётся вызывающим кодом: два
независимых словаря имён разъехались бы, и новое действие молча осталось бы без записи.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.authors import Author


class EntryType(StrEnum):
    """Тип записи дела. Записи агента и человека — до `NOTE`, служебные — после."""

    SUMMARY = "summary"
    DECISION = "decision"
    ATTEMPT = "attempt"
    FINDING = "finding"
    ARTIFACT = "artifact"
    QUESTION = "question"
    ANSWER = "answer"
    VERDICT = "verdict"
    NOTE = "note"
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    SECTION_CHANGED = "section_changed"
    ASSIGNEE_CHANGED = "assignee_changed"
    LINK_ADDED = "link_added"
    LINK_REMOVED = "link_removed"


#: Записи, которые подшивает сам трекер в той же транзакции, что и изменение. Агент
#: подшить такую запись напрямую не может: задача 23 отвергает эти типы на входе.
SERVICE_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {
        EntryType.CREATED,
        EntryType.STATUS_CHANGED,
        EntryType.SECTION_CHANGED,
        EntryType.ASSIGNEE_CHANGED,
        EntryType.LINK_ADDED,
        EntryType.LINK_REMOVED,
    }
)

#: Записи агента и человека — всё, что не служебное.
AGENT_ENTRY_TYPES: frozenset[EntryType] = frozenset(EntryType) - SERVICE_ENTRY_TYPES

#: Номер первой записи в задаче. Сквозной `seq` выдаёт база, а `no` считается по задаче.
FIRST_ENTRY_NUMBER = 1

#: Заголовок — одна строка: это то, что видно в описи дела.
MAX_ENTRY_TITLE_LENGTH = 255

#: Разделитель ссылки на запись: `TRK-42#12` — двенадцатая запись задачи `TRK-42`.
ENTRY_REF_SEPARATOR = "#"


def format_entry_ref(task_key: str, no: int) -> str:
    """Ссылка на запись: ключ задачи и номер записи в ней."""
    return f"{task_key}{ENTRY_REF_SEPARATOR}{no}"


@dataclass(frozen=True, slots=True)
class EntryHeading:
    """Строка описи дела: то, что преемник видит о записи, не читая её тела.

    Ровно те поля, что названы в концепции (4.2): `no`, `type`, `author`, `created_at`,
    `title`. Тело и `payload` читаются точечно по номеру.
    """

    no: int
    type: EntryType
    author: Author
    created_at: datetime
    title: str
