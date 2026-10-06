"""Направления: правила ключа, адреса, описания и причины архива.

Направление — бесконечная часть работы внутри одного проекта (`CONCEPT.md`, 3.7; решения
владельца `TRK#16`, `TRK#17`). Устроено как проект, только меньше: карточка, атрибуты,
дело и архив, а статуса, исполнителя и проверок нет.

## Ключ и адрес

Ключ направления уникален внутри проекта и неизменяем, как ключ проекта. Канонический вид
— **нижний** регистр: ключ стоит после косой черты адреса (`TRK/promotion`) и читается
как слово, а не как ключ задачи. Регистр на входе не важен — ключ канонизируется, а не
отвергается, чтобы `Promotion` при существующем `promotion` дал «ключ занят», а не
«неверная форма» (то же правило, что у проекта, `app/domain/projects.py`).

Адрес — ключ проекта и ключ направления через косую черту. Косой черты нет ни в ключе
проекта, ни в ключе задачи, поэтому по ней адрес направления отличают от ключа проекта
(`TRK`) везде, где принимается и то и другое, и ссылку на запись направления
(`TRK/promotion#3`) — от ссылки на запись проекта (`TRK#7`).

## Описание и причина

Описание — короткое «что это» не длиннее того же предела, что у проекта, по той же
причине: оно поедет в карточке каждой задачи направления (`TRK#16`, часть 2; поле задачи
— TRK-556). Причина архивирования и восстановления обязательна в обе стороны, как у
проекта.
"""

import re
from dataclasses import dataclass

from app.domain.errors import (
    DirectionDescriptionTooLongError,
    DirectionReasonRequiredError,
    InvalidDirectionKeyError,
)
from app.domain.projects import (
    MAX_PROJECT_DESCRIPTION_LENGTH,
    MAX_PROJECT_REASON_LENGTH,
    PROJECT_KEY_PATTERN,
    normalize_project_key,
)

#: Ключ направления: строчная латиница, цифры и дефис; начало и конец — буква или цифра,
#: чтобы дефис по краю (`-promo`, `promo-`) не выглядел опечаткой адреса.
DIRECTION_KEY_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
_DIRECTION_KEY_RE = re.compile(DIRECTION_KEY_PATTERN)

#: Верхняя граница длины ключа по шаблону: под неё задана колонка `directions.key`.
MAX_DIRECTION_KEY_LENGTH = 32

#: Разделитель адреса направления: `TRK/promotion`.
ADDRESS_SEPARATOR = "/"

#: Форма адреса в подробностях отказа: по ней агент чинит запрос.
DIRECTION_ADDRESS_SHAPE = f"<PROJECT>{ADDRESS_SEPARATOR}<direction key>"

_PROJECT_KEY_RE = re.compile(PROJECT_KEY_PATTERN)

#: Предел описания направления в знаках — тот же, что у проекта (`CONCEPT.md`, 3.7). Под
#: него же заведено ограничение `ck_directions_description_length`.
MAX_DIRECTION_DESCRIPTION_LENGTH = MAX_PROJECT_DESCRIPTION_LENGTH

#: Предел причины архивирования и восстановления — тот же, что у проекта.
MAX_DIRECTION_REASON_LENGTH = MAX_PROJECT_REASON_LENGTH


@dataclass(frozen=True, slots=True)
class DirectionAddress:
    """Адрес направления: ключ проекта в верхнем регистре и ключ направления в нижнем.

    Канонический вид обеих частей, но не проверенный шаблон ключа направления: адресация
    мягкая (`docs/notes/api.md`, «Адресация мягкая, создание строгое»), и адрес с ключом не
    по шаблону ищется и не находится (`direction_not_found`), а не отвергается формой.
    """

    project_key: str
    key: str

    def __str__(self) -> str:
        return format_direction_address(self.project_key, self.key)


def format_direction_address(project_key: str, key: str) -> str:
    """Адрес направления из ключа проекта и ключа направления: `TRK/promotion`."""
    return f"{project_key}{ADDRESS_SEPARATOR}{key}"


def is_direction_address(value: str) -> bool:
    """Называет ли строка направление, а не проект: в адресе направления есть косая черта.

    По этому признаку инструменты, принимающие ключ проекта или адрес направления, решают,
    кого ищут; форму каждой части проверяет уже поиск.
    """
    return ADDRESS_SEPARATOR in value


def normalize_direction_key(key: str) -> str:
    """Канонический вид ключа: без пробелов по краям, в нижнем регистре."""
    return key.strip().lower()


def parse_direction_address(value: str) -> DirectionAddress:
    """Разбирает адрес для поиска: обе части канонизируются, шаблон ключа не проверяется.

    Строка без косой черты — не адрес направления: это ключ проекта, и звать сюда её не
    должны (`is_direction_address`). Разбор по первой косой черте: в ключе проекта её не
    бывает, а лишняя справа останется в ключе направления и не найдётся.
    """
    project_key, _, key = value.partition(ADDRESS_SEPARATOR)
    return DirectionAddress(
        project_key=normalize_project_key(project_key), key=normalize_direction_key(key)
    )


def validate_new_direction_address(value: str) -> DirectionAddress:
    """Адрес нового направления: косая черта, ключ проекта по форме, ключ по шаблону.

    Отказ один — `invalid_direction_key` — с причиной в `details.reason`: `not_an_address`
    (нет косой черты или пустая левая часть) или `pattern_mismatch` (ключ не по шаблону).
    Есть ли такой проект, проверяет сценарий: домен в базу не ходит.
    """
    if not is_direction_address(value):
        raise InvalidDirectionKeyError(
            details={"key": value, "reason": "not_an_address", "expected": DIRECTION_ADDRESS_SHAPE}
        )
    address = parse_direction_address(value)
    if not _PROJECT_KEY_RE.match(address.project_key):
        raise InvalidDirectionKeyError(
            details={"key": value, "reason": "not_an_address", "expected": DIRECTION_ADDRESS_SHAPE}
        )
    if not _DIRECTION_KEY_RE.match(address.key):
        raise InvalidDirectionKeyError(
            details={"key": value, "reason": "pattern_mismatch", "pattern": DIRECTION_KEY_PATTERN}
        )
    return address


def is_direction_key(key: str) -> bool:
    """Ключ уже в каноническом виде и по шаблону — для разбора ссылки `TRK/promotion#3`."""
    return _DIRECTION_KEY_RE.match(key) is not None


def validate_direction_description(description: str) -> str:
    """Описание без пробелов по краям; длиннее предела — `direction_description_too_long`."""
    normalized = description.strip()
    if len(normalized) > MAX_DIRECTION_DESCRIPTION_LENGTH:
        raise DirectionDescriptionTooLongError(
            details={"length": len(normalized), "max_length": MAX_DIRECTION_DESCRIPTION_LENGTH}
        )
    return normalized


def require_direction_reason(reason: str | None, *, address: str, action: str) -> str:
    """Причина `archive`/`restore` без пробелов по краям; пустая — `direction_reason_required`."""
    normalized = (reason or "").strip()
    if not normalized:
        raise DirectionReasonRequiredError(details={"key": address, "action": action})
    return normalized
