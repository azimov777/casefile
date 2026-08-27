"""Очереди: ключ, нумерация задач, инварианты.

Чистый Python: ни ORM, ни HTTP. Ключ очереди и формат ключа задачи описаны здесь,
потому что ими пользуются и REST, и MCP, и генератор ключей задач из задачи 05.
"""

import re

from app.domain.errors import InvalidQueueKeyError

# Ключ очереди — латиница в верхнем регистре, как требуют соглашения (`TRK`, `OPS`).
# Верхний регистр отличает его на глаз от ключей акторов, статусов и полей: те в нижнем.
# Цифры разрешены со второго символа, разделители — нет: ключ входит в ключ задачи
# (`TRK-123`), и любой дополнительный разделитель сделал бы разбор неоднозначным.
QUEUE_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,15}$"
MAX_QUEUE_KEY_LENGTH = 16

_QUEUE_KEY_RE = re.compile(QUEUE_KEY_PATTERN)

#: Разделитель ключа задачи. В ключе очереди его быть не может — см. шаблон выше.
ISSUE_KEY_SEPARATOR = "-"

#: Номер первой задачи в очереди. Счётчик хранит номер последней выданной, поэтому
#: пустая очередь держит 0, а первая задача получает 1.
FIRST_ISSUE_NUMBER = 1


def normalize_queue_key(key: str) -> str:
    """Приводит ключ к каноническому виду: без пробелов по краям, в верхнем регистре."""
    return key.strip().upper()


def validate_queue_key(key: str) -> str:
    """Проверяет ключ очереди и возвращает канонический вид.

    Бросает `InvalidQueueKeyError`: в `details` уходит шаблон, чтобы агент понял,
    как исправить запрос, не читая исходники.
    """
    normalized = normalize_queue_key(key)
    if not _QUEUE_KEY_RE.match(normalized):
        raise InvalidQueueKeyError(
            details={"key": key, "reason": "pattern_mismatch", "pattern": QUEUE_KEY_PATTERN},
        )
    return normalized


def format_issue_key(queue_key: str, number: int) -> str:
    """Собирает ключ задачи из ключа очереди и номера: `TRK` + `123` → `TRK-123`.

    Живёт здесь, а не в задаче про задачи: формат ключа — свойство нумерации очереди,
    и разбирать его обратно (`split`) должны по этой же константе-разделителю.
    """
    return f"{queue_key}{ISSUE_KEY_SEPARATOR}{number}"
