"""Акторы: типы, ключи, инварианты системного актора.

Чистый Python: ни ORM, ни HTTP. Всё, что здесь описано, одинаково верно для REST,
MCP и фоновых процессов, поэтому проверки живут тут, а не в схемах запросов.
"""

import re
import uuid
from enum import StrEnum

from app.domain.errors import InvalidActorKeyError

# Ключ актора: латиница в нижнем регистре, как ключи полей и статусов в соглашениях.
# Верхний регистр отдан ключам очередей (`TRK`), чтобы одно от другого отличалось на глаз.
ACTOR_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
_ACTOR_KEY_RE = re.compile(ACTOR_KEY_PATTERN)

# `/api/v1/actors/me` адресует текущего актора: актор с таким ключом стал бы недостижим.
RESERVED_ACTOR_KEYS = frozenset({"me"})

# Системный актор создаётся миграцией с фиксированным идентификатором: автоматика,
# журнал изменений и outbox ссылаются на него из кода, а не ищут по ключу каждый раз.
# Тот же UUID записан литералом в миграции — совпадение стережёт тест.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_ACTOR_KEY = "system"
# Отображаемое имя — пользовательские данные, их можно переименовать через API.
# Заготовка английская: служебный слой проекта на русском не пишется.
SYSTEM_ACTOR_DISPLAY_NAME = "System"


class ActorType(StrEnum):
    """Кто инициировал действие.

    `system` — от его имени работают автоматика и фоновые процессы; такой актор один
    на установку и создаётся миграцией, а не через API.
    """

    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


#: Типы, которые разрешено заводить снаружи. `system` в список не входит намеренно.
CREATABLE_ACTOR_TYPES = frozenset({ActorType.HUMAN, ActorType.AGENT})


def normalize_actor_key(key: str) -> str:
    """Приводит ключ к каноническому виду: без пробелов по краям, в нижнем регистре."""
    return key.strip().lower()


def validate_actor_key(key: str) -> str:
    """Проверяет ключ и возвращает канонический вид.

    Бросает `InvalidActorKeyError` — в `details` уходит шаблон и список занятых ключей,
    чтобы агент понял, как исправить запрос, не читая исходники.
    """
    normalized = normalize_actor_key(key)
    if normalized in RESERVED_ACTOR_KEYS:
        raise InvalidActorKeyError(
            details={"key": key, "reason": "reserved", "reserved": sorted(RESERVED_ACTOR_KEYS)},
        )
    if not _ACTOR_KEY_RE.match(normalized):
        raise InvalidActorKeyError(
            details={"key": key, "reason": "pattern_mismatch", "pattern": ACTOR_KEY_PATTERN},
        )
    return normalized
