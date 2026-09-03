"""Участники: род и правила имени.

Чистый Python: ни ORM, ни HTTP. Всё, что здесь описано, одинаково верно для REST, MCP и
командной строки, поэтому проверки живут тут, а не в схемах запросов.

## Имя канонизируется, а не отвергается по регистру

Соглашения требуют, чтобы имена были уникальны **без учёта регистра**. Сделать это
шаблоном «только нижний регистр» нельзя: тогда `Alice` при существующем `alice` получил
бы `422` от схемы запроса — ответ про форму строки вместо ответа про занятое имя. Поэтому
шаблон принимает обе раскладки, а канонический вид (нижний регистр) считает домен, и
уникальность держит обычное ограничение `UNIQUE` по уже канонизированной колонке.
"""

import re
from enum import StrEnum

from app.domain.errors import InvalidParticipantNameError

#: Имя участника: латиница, `snake_case`. Верхний регистр допускается на входе и
#: приводится к нижнему — см. раздел «Имя канонизируется» выше.
PARTICIPANT_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{1,63}$"
_PARTICIPANT_NAME_RE = re.compile(PARTICIPANT_NAME_PATTERN)


class ParticipantKind(StrEnum):
    """Род участника.

    Ролей и прав за родом не стоит: любую запись и любой переход может сделать участник
    любого рода (`CONCEPT.md`, 3.1). Род нужен, чтобы читающий дело понимал, кто
    говорит, и чтобы интерфейс человека отличал людей от агентов в списке адресатов.
    """

    HUMAN = "human"
    AGENT = "agent"


def normalize_participant_name(name: str) -> str:
    """Канонический вид имени: без пробелов по краям, в нижнем регистре."""
    return name.strip().lower()


def validate_participant_name(name: str) -> str:
    """Проверяет имя и возвращает канонический вид.

    В `details` уезжает шаблон: агент, получивший отказ, должен исправить запрос с
    первой попытки, не читая исходники.
    """
    normalized = normalize_participant_name(name)
    if not _PARTICIPANT_NAME_RE.match(normalized):
        raise InvalidParticipantNameError(
            details={
                "name": name,
                "reason": "pattern_mismatch",
                "pattern": PARTICIPANT_NAME_PATTERN,
            },
        )
    return normalized
