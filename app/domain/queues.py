"""Очереди: ключ, нумерация задач, инварианты.

Чистый Python: ни ORM, ни HTTP. Ключ очереди и формат ключа задачи описаны здесь,
потому что ими пользуются и REST, и MCP, и генератор ключей задач из задачи 05.
"""

import re

from app.domain.errors import InvalidIssueKeyError, InvalidQueueKeyError

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

#: Предел длины ключа задачи: ключ очереди, разделитель и номер. Номер — `BIGINT`, то
#: есть не длиннее 19 цифр, и в такой ключ не упрётся ни одна реальная очередь. Нужен
#: только затем, чтобы у колонки была явная граница, а не `TEXT` без предела.
MAX_ISSUE_KEY_LENGTH = MAX_QUEUE_KEY_LENGTH + len(ISSUE_KEY_SEPARATOR) + 19


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


def parse_issue_key(key: str) -> tuple[str, int]:
    """Разбирает ключ задачи обратно: `TRK-123` → `("TRK", 123)`.

    Обратная к `format_issue_key` и живёт рядом с ней намеренно: разделитель один, и
    второй разбор по своей константе однажды разъехался бы с форматированием.

    Проверяются обе половины: ключ очереди — по шаблону очередей, номер — целое,
    начиная с первого выданного. Ссылка на задачу приезжает в значениях кастомных
    полей и в строке поиска, поэтому разбор обязан быть строгим: `TRK-0`, `TRK-1-2`
    и `TRK-01` — не ключи задач, и молча истолковать их нельзя.
    """
    queue_part, separator, number_part = key.strip().partition(ISSUE_KEY_SEPARATOR)
    if not _is_plain_number(number_part) or not separator:
        raise InvalidIssueKeyError(
            details={
                "key": key,
                "reason": "pattern_mismatch",
                "expected": f"<QUEUE>{ISSUE_KEY_SEPARATOR}<number>",
            },
        )
    number = int(number_part)
    if number < FIRST_ISSUE_NUMBER:
        raise InvalidIssueKeyError(
            details={"key": key, "reason": "number_out_of_range", "min": FIRST_ISSUE_NUMBER},
        )
    return validate_queue_key(queue_part), number


def _is_plain_number(part: str) -> bool:
    """Номер задачи — десятичные цифры ASCII без ведущих нулей.

    `isdigit()` в одиночку сюда не годится: он пропускает индийско-арабские цифры и
    надстрочные знаки, и `TRK-١٢٣` разобрался бы в 123. Ведущие нули отсекаются
    отдельно — иначе `TRK-007` и `TRK-7` указывали бы на одну задачу двумя способами.
    """
    if not part.isascii() or not part.isdigit():
        return False
    return part.lstrip("0") == part
