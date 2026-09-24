"""Проекты: правила ключа.

Проект — единственный уровень группировки (`CONCEPT.md`, 3.2). Его ключ даёт задачам
номера (`TRK-42`), поэтому он неизменяем: переименование задним числом порвало бы все
уже записанные ссылки на задачи.

Канонический вид ключа — **верхний** регистр, в отличие от имён участников. Это не
украшение: ключ проекта видно в ключе задачи, и там он обязан читаться как ключ, а не
как слово. Регистр на входе при этом не важен — как и у имён, ключ канонизируется, а не
отвергается, чтобы `trk` при существующем `TRK` дал «ключ занят», а не «неверная форма».
"""

import re

from app.domain.errors import InvalidProjectKeyError

#: Ключ проекта: латиница и цифры, без разделителей — он идёт в ключ задачи перед дефисом.
PROJECT_KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9]{1,15}$"
_PROJECT_KEY_RE = re.compile(PROJECT_KEY_PATTERN)

#: Верхняя граница длины ключа по шаблону: под неё заданы колонка `projects.key` и
#: предел длины ключа задачи (`app/domain/tasks.py`).
MAX_PROJECT_KEY_LENGTH = 16


def normalize_project_key(key: str) -> str:
    """Канонический вид ключа: без пробелов по краям, в верхнем регистре."""
    return key.strip().upper()


def validate_project_key(key: str) -> str:
    """Проверяет ключ и возвращает канонический вид."""
    normalized = normalize_project_key(key)
    if not _PROJECT_KEY_RE.match(normalized):
        raise InvalidProjectKeyError(
            details={"key": key, "reason": "pattern_mismatch", "pattern": PROJECT_KEY_PATTERN},
        )
    return normalized
