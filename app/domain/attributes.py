"""Атрибуты проекта: имя, значение и причина.

Атрибут — справочный факт проекта «имя → значение» (`CONCEPT.md`, 3.2): где лежит
репозиторий, какая ветка главная. Не поле процесса: трекер не отбирает по нему задачи и
значение не толкует, поэтому правил у значения два — это текст и он не длиннее предела.

## Имя хранится как прислано, сравнивается в нижнем регистре

В отличие от ключа проекта, имя не канонизируется: `repoURL` остаётся `repoURL`, как его
завели. Но `repourl` — тот же атрибут: уникальность и поиск идут по нижнему регистру
(индекс `(project_id, lower(name))`). Переименования нет — написание, присланное позже,
хранимое не меняет: снять и завести заново, обе записи с причиной.

Шаблон — латиница, цифры, `_` и `-`. Имя стоит в адресе REST
(`/projects/{key}/attributes/{name}`), и символ, требующий экранирования, делал бы адрес
неоднозначным. Только ASCII — и потому нижний регистр в Python и в PostgreSQL один и тот
же.

## Причина

Заведение причины не требует, изменение и снятие — требуют: факт меняют не молча, и
преемник видит, почему прежнее значение перестало быть верным. Пробелы по краям
снимаются, пустая строка — это «причины нет».
"""

import re

from app.domain.errors import (
    AttributeReasonRequiredError,
    AttributeValueTooLongError,
    InvalidAttributeNameError,
)

#: Имя атрибута: латиница, цифры, `_` и `-`, от 1 до `MAX_ATTRIBUTE_NAME_LENGTH` знаков.
ATTRIBUTE_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_ATTRIBUTE_NAME_RE = re.compile(ATTRIBUTE_NAME_PATTERN)

#: Верхняя граница длины имени по шаблону: под неё задана колонка `project_attributes.name`.
MAX_ATTRIBUTE_NAME_LENGTH = 64

#: Предел значения в знаках (кодовых точках), а не в байтах (`CONCEPT.md`, 3.2).
MAX_ATTRIBUTE_VALUE_LENGTH = 1_000

#: Предел причины изменения и снятия — тот же, что у причины перехода статуса.
MAX_ATTRIBUTE_REASON_LENGTH = 65_536


def validate_attribute_name(name: str) -> str:
    """Проверяет имя и возвращает его как прислано: регистр не меняется."""
    if not _ATTRIBUTE_NAME_RE.match(name):
        raise InvalidAttributeNameError(
            details={"name": name, "reason": "pattern_mismatch", "pattern": ATTRIBUTE_NAME_PATTERN}
        )
    return name


def attribute_lookup_name(name: str) -> str:
    """Имя для сравнения: нижний регистр. Уникальность в базе — по тому же выражению."""
    return name.lower()


def validate_attribute_value(value: str) -> str:
    """Значение хранится как прислано; проверяется только длина."""
    if len(value) > MAX_ATTRIBUTE_VALUE_LENGTH:
        raise AttributeValueTooLongError(
            details={"length": len(value), "max_length": MAX_ATTRIBUTE_VALUE_LENGTH}
        )
    return value


def normalize_attribute_reason(reason: str | None) -> str | None:
    """Причина без пробелов по краям; пустая становится `None` — причины нет."""
    if reason is None:
        return None
    return reason.strip() or None


def require_attribute_reason(reason: str | None, *, name: str, action: str) -> str:
    """Причина изменения или снятия: непустая, иначе `attribute_reason_required`."""
    normalized = normalize_attribute_reason(reason)
    if normalized is None:
        raise AttributeReasonRequiredError(details={"name": name, "action": action})
    return normalized
