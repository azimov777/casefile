"""Доступ участника-агента к проектам: три режима и одно правило «открыт ли проект».

Чистый Python: ни ORM, ни HTTP. Слово владельца — TRK~28#6 (выбор «A»): на каждом
участнике-агенте стоит режим и список проектов.

- `all` — открыты все проекты, в том числе заведённые позже (по умолчанию); список пуст и
  не читается;
- `except` — открыты все, кроме перечисленных: новые проекты открыты сами;
- `only` — открыты только перечисленные: новые проекты закрыты, пока их не добавили.

Проекты в списке названы идентификатором, не ключом: ключ неизменяем, но идентификатор
не зависит от его написания. Участник-человек и вызов без участника (общий агентский
ключ, временный агент) ограничений не имеют: для них берут `UNRESTRICTED`.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import ProjectAccessModeInvalidError


class ProjectAccessMode(StrEnum):
    """Режим доступа к проектам."""

    ALL = "all"
    EXCEPT = "except"
    ONLY = "only"


def parse_project_access_mode(value: str | ProjectAccessMode) -> ProjectAccessMode:
    """Режим из строки; чужое значение — `project_access_mode_invalid` с допустимыми."""
    try:
        return ProjectAccessMode(value)
    except ValueError:
        raise ProjectAccessModeInvalidError(
            details={"mode": value, "allowed": [mode.value for mode in ProjectAccessMode]}
        ) from None


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """Режим и список проектов участника. Неизменяемое значение.

    Режим проверяется при создании: значение вне трёх — `project_access_mode_invalid`.
    """

    mode: ProjectAccessMode = ProjectAccessMode.ALL
    project_ids: frozenset[uuid.UUID] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", parse_project_access_mode(self.mode))
        object.__setattr__(self, "project_ids", frozenset(self.project_ids))

    @classmethod
    def of(cls, mode: str, project_ids: Iterable[uuid.UUID] = ()) -> ProjectAccess:
        return cls(mode=parse_project_access_mode(mode), project_ids=frozenset(project_ids))


#: Доступ без ограничений: людям, общему агентскому ключу и временным агентам.
UNRESTRICTED = ProjectAccess()


def is_open(access: ProjectAccess, project_id: uuid.UUID) -> bool:
    """Открыт ли проект участнику с таким доступом."""
    if access.mode is ProjectAccessMode.EXCEPT:
        return project_id not in access.project_ids
    if access.mode is ProjectAccessMode.ONLY:
        return project_id in access.project_ids
    return True


#: Вместо ключа закрытого агенту проекта там, где факт связи показать нужно, а проект назвать
#: нельзя: связь есть, назвать её сторону вызову не положено (TRK-753).
CLOSED_PROJECT_LABEL = "[closed project]"


def mask_closed_keys(text: str, closed_keys: Iterable[str]) -> str:
    """Заменяет в строке всё, что называет закрытый проект, меткой `CLOSED_PROJECT_LABEL`.

    Называет проект ключ в любом написании: `TRK`, `TRK-7`, `TRK/core#3`, `TRK~2#1`. Без
    закрытых ключей строка не меняется.
    """
    keys = sorted({key.upper() for key in closed_keys}, key=len, reverse=True)
    if not keys:
        return text
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(key) for key in keys) + r")\b(?:[-/~#][\w-]*)*",
        re.IGNORECASE,
    )
    return pattern.sub(CLOSED_PROJECT_LABEL, text)
