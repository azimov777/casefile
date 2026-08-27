"""Задача: приоритет, теги, ограничения текстовых полей, запись об изменении.

Чистый Python: ни ORM, ни HTTP. Проверки живут здесь, а не в схемах запросов, потому
что тот же сценарий вызывают MCP и автоматика — они идут мимо FastAPI, и правило,
записанное только в схеме, для них не существует.

## Что здесь есть, а чего нет

Системные поля задачи — колонки (`docs/CONCEPT.md`), поэтому их форма проверяется
здесь. Кастомные поля описываются реестром и проверяются в `app/domain/fields.py`:
формат их хранения в `values JSONB` зафиксирован там, и дублировать его нельзя.

`IssueChange` — единица результата единой точки применения изменений
(`app/services/issues.py`). Задача 06 строит из этих записей журнал изменений и
полезную нагрузку события, поэтому «было» и «стало» здесь уже в том виде, в каком
уедут в JSON: ссылка на запись справочника — строкой (`open`, `TRK.open`), актор —
ключом, время — строкой ISO 8601. Класть сюда ORM-объекты нельзя: событие переживает
транзакцию, а объект — нет.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.domain.errors import (
    InvalidIssueDeadlineError,
    InvalidIssueDescriptionError,
    InvalidIssueSummaryError,
    InvalidIssueTagsError,
)

#: Название задачи — одна строка: оно показывается в списках, на карточках доски и в
#: уведомлениях, где перевод строки просто испортит вёрстку.
MAX_SUMMARY_LENGTH = 255

#: Потолок описания. Ограничение неочевидное, поэтому названо прямо: описание уезжает
#: в каждый ответ с задачей и в каждое событие, и мегабайтный текст сделал бы
#: неподъёмными и то, и другое.
MAX_DESCRIPTION_LENGTH = 65_536

#: Теги — плоские метки, а не иерархия: длинный тег означает, что нужно поле.
MAX_TAG_LENGTH = 64
MAX_TAGS = 50


class IssuePriority(StrEnum):
    """Приоритет задачи.

    Колонка с перечислением, а не справочник: в отличие от статусов и типов, набор
    приоритетов не описывает процесс команды и одинаков во всех очередях. Порядок
    членов — от низшего к высшему, на него опирается сортировка в задаче 12.
    """

    TRIVIAL = "trivial"
    MINOR = "minor"
    NORMAL = "normal"
    MAJOR = "major"
    BLOCKER = "blocker"


#: Приоритет по умолчанию: у задачи, заведённой без указания, он должен быть, иначе
#: сортировка и фильтры пришлось бы всюду учить обрабатывать пустое значение.
DEFAULT_PRIORITY = IssuePriority.NORMAL


class IssueField(StrEnum):
    """Системное поле задачи в записи об изменении.

    Значения совпадают с именами полей в API и входят в `SYSTEM_FIELD_KEYS` из
    `app/domain/fields.py` — то есть кастомное поле с таким ключом завести нельзя, и
    имя в журнале изменений однозначно: либо это системное поле, либо ссылка на
    кастомное (`severity`, `TRK.severity`). Совпадение стережёт тест.
    """

    SUMMARY = "summary"
    DESCRIPTION = "description"
    ISSUE_TYPE = "issue_type"
    STATUS = "status"
    RESOLUTION = "resolution"
    PRIORITY = "priority"
    ASSIGNEE = "assignee"
    FOLLOWERS = "followers"
    DEADLINE = "deadline"
    TAGS = "tags"


@dataclass(frozen=True, slots=True)
class IssueChange:
    """Одно фактическое изменение: какое поле, что было, что стало.

    «Фактическое» — ключевое слово: поле, переданное со значением, равным текущему,
    записи не даёт. Иначе журнал изменений заполнился бы строками «сменил приоритет с
    `normal` на `normal`», а автоматика из задачи 13 срабатывала бы на изменение,
    которого не было.
    """

    field: str
    before: Any
    after: Any


def validate_summary(summary: str) -> str:
    """Проверяет название задачи и возвращает канонический вид.

    Пустое название отвергается, а не заменяется заглушкой: задача без названия
    нечитаема в любом списке, а придумать его за пользователя нечем.
    """
    normalized = summary.strip()
    if not normalized:
        raise InvalidIssueSummaryError(details={"field": "summary", "reason": "required"})
    if "\n" in normalized or "\r" in normalized:
        raise InvalidIssueSummaryError(
            details={"field": "summary", "reason": "multiline_not_allowed"},
        )
    if len(normalized) > MAX_SUMMARY_LENGTH:
        raise InvalidIssueSummaryError(
            details={
                "field": "summary",
                "reason": "too_long",
                "max": MAX_SUMMARY_LENGTH,
                "got": len(normalized),
            },
        )
    return normalized


def validate_description(description: str) -> str:
    """Проверяет описание. Пустая строка допустима и означает «описания нет».

    Пустая строка, а не `NULL`: «описания нет» и «описание пустое» — одно состояние,
    и два способа его записать неизбежно разъехались бы у клиентов. Так же устроено
    описание очереди.
    """
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise InvalidIssueDescriptionError(
            details={
                "field": "description",
                "reason": "too_long",
                "max": MAX_DESCRIPTION_LENGTH,
                "got": len(description),
            },
        )
    return description.strip()


def validate_deadline(deadline: datetime | None) -> datetime | None:
    """Проверяет дедлайн и приводит его к UTC. `None` — законное «дедлайна нет».

    Время без зоны отвергается, а не домысливается: соглашения требуют ISO 8601 с
    таймзоной, и подстановка зоны за клиента дала бы сдвиг, который заметят через
    месяц — когда напоминание придёт не в тот день. Ровно так же поступает валидатор
    кастомных полей с типом `datetime`.

    Приведение к UTC — не косметика, и поймала эту мелочь живая проверка, а не тесты.
    `timestamptz` хранит момент в UTC, поэтому чтение задачи из базы всегда отдаёт
    `...Z`. А объект, только что созданный из запроса, держит зону клиента, и ответ на
    `POST` уходил с `+03:00`. Момент один, записи разные — клиент, сравнивающий ответы
    строкой, видит изменение там, где ничего не менялось.
    """
    if deadline is None:
        return None
    if deadline.tzinfo is None:
        raise InvalidIssueDeadlineError(
            details={
                "field": "deadline",
                "reason": "timezone_required",
                "expected": "ISO 8601 with a UTC offset",
            },
        )
    return deadline.astimezone(UTC)


def normalize_tags(tags: Iterable[str]) -> list[str]:
    """Приводит набор тегов к каноническому виду, сохраняя порядок.

    Повторы отбрасываются без учёта регистра, а вот сам регистр сохраняется: тег —
    пользовательские данные, и «Релиз» не должен превращаться в «релиз». Первое
    написание побеждает — иначе результат зависел бы от порядка, в котором клиент
    перечислил повторы.

    Пустой тег выбрасывается молча (это опечатка вида `["a", ""]`, а не запрос), а
    слишком длинный или многострочный отвергается: молча обрезать значение, которое
    потом станет фильтром, нельзя.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = tag.strip()
        if not value:
            continue
        if "\n" in value or "\r" in value:
            raise InvalidIssueTagsError(
                details={"field": "tags", "reason": "multiline_not_allowed", "tag": tag},
            )
        if len(value) > MAX_TAG_LENGTH:
            raise InvalidIssueTagsError(
                details={
                    "field": "tags",
                    "reason": "too_long",
                    "tag": value,
                    "max": MAX_TAG_LENGTH,
                    "got": len(value),
                },
            )
        folded = value.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(value)

    if len(normalized) > MAX_TAGS:
        raise InvalidIssueTagsError(
            details={
                "field": "tags",
                "reason": "too_many",
                "max": MAX_TAGS,
                "got": len(normalized),
            },
        )
    return normalized


def tags_differ(before: Sequence[str], after: Sequence[str]) -> bool:
    """Порядок тегов значим, поэтому сравниваются списки, а не множества.

    Перестановка тегов — тоже изменение: она видна пользователю в карточке задачи, и
    молча проигнорировать её значило бы отдать клиенту не то состояние, которое он
    прислал.
    """
    return list(before) != list(after)
