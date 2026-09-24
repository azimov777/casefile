"""Проекты: правила ключа и описания.

Проект — единственный уровень группировки (`CONCEPT.md`, 3.2). Его ключ даёт задачам
номера (`TRK-42`), поэтому он неизменяем: переименование задним числом порвало бы все
уже записанные ссылки на задачи.

Канонический вид ключа — **верхний** регистр, в отличие от имён участников. Это не
украшение: ключ проекта видно в ключе задачи, и там он обязан читаться как ключ, а не
как слово. Регистр на входе при этом не важен — как и у имён, ключ канонизируется, а не
отвергается, чтобы `trk` при существующем `TRK` дал «ключ занят», а не «неверная форма».

Описание — короткое «что это»: оно едет в карточке каждой задачи проекта (`CONCEPT.md`,
3.2 и 4.2), и агент получает контекст проекта тем же `get_task`. Отсюда предел в знаках
(кодовых точках, как `len` в Python и `char_length` в PostgreSQL), а не в байтах:
кириллица стоит столько же, сколько латиница. Длинный текст не обрезается — его место в
атрибутах и в деле проекта.
"""

import re

from app.domain.errors import InvalidProjectKeyError, ProjectDescriptionTooLongError

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


#: Предел описания проекта в знаках (`CONCEPT.md`, 3.2). Под него же заведено ограничение
#: `ck_projects_description_length` (`app/db/models/project.py`).
MAX_PROJECT_DESCRIPTION_LENGTH = 320


def validate_project_description(description: str) -> str:
    """Описание без пробелов по краям; длиннее предела — `project_description_too_long`.

    Длина считается после снятия пробелов: хранится и показывается именно этот текст.
    """
    normalized = description.strip()
    if len(normalized) > MAX_PROJECT_DESCRIPTION_LENGTH:
        raise ProjectDescriptionTooLongError(
            details={"length": len(normalized), "max_length": MAX_PROJECT_DESCRIPTION_LENGTH}
        )
    return normalized
