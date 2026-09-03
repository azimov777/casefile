"""Очереди: правила ключа.

Очередь — единственный уровень группировки (`CONCEPT.md`, 3.2). Её ключ даёт задачам
номера (`TRK-42`), поэтому он неизменяем: переименование задним числом порвало бы все
уже записанные ссылки на задачи.

Канонический вид ключа — **верхний** регистр, в отличие от имён участников. Это не
украшение: ключ очереди видно в ключе задачи, и там он обязан читаться как ключ, а не
как слово. Регистр на входе при этом не важен — как и у имён, ключ канонизируется, а не
отвергается, чтобы `trk` при существующем `TRK` дал «ключ занят», а не «неверная форма».
"""

import re

from app.domain.errors import InvalidQueueKeyError

#: Ключ очереди: латиница и цифры, без разделителей — он идёт в ключ задачи перед дефисом.
QUEUE_KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9]{1,15}$"
_QUEUE_KEY_RE = re.compile(QUEUE_KEY_PATTERN)


def normalize_queue_key(key: str) -> str:
    """Канонический вид ключа: без пробелов по краям, в верхнем регистре."""
    return key.strip().upper()


def validate_queue_key(key: str) -> str:
    """Проверяет ключ и возвращает канонический вид."""
    normalized = normalize_queue_key(key)
    if not _QUEUE_KEY_RE.match(normalized):
        raise InvalidQueueKeyError(
            details={"key": key, "reason": "pattern_mismatch", "pattern": QUEUE_KEY_PATTERN},
        )
    return normalized
