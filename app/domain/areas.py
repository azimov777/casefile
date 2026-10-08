"""Области: правила ключа, адреса, описания и причины архива.

Область — бесконечная часть работы внутри одного проекта (TRK#57; решения
владельца `TRK#16`, `TRK#17`). Устроена как проект, только меньше: карточка, атрибуты,
дело и архив, а статуса, исполнителя и проверок нет.

## Ключ и адрес

Ключ области уникален внутри проекта и неизменяем, как ключ проекта. Канонический вид
— **нижний** регистр: ключ стоит после косой черты адреса (`TRK/promotion`) и читается
как слово, а не как ключ задачи. Регистр на входе не важен — ключ канонизируется, а не
отвергается, чтобы `Promotion` при существующем `promotion` дал «ключ занят», а не
«неверная форма» (то же правило, что у проекта, `app/domain/projects.py`).

Адрес — ключ проекта и ключ области через косую черту. Косой черты нет ни в ключе
проекта, ни в ключе задачи, поэтому по ней адрес области отличают от ключа проекта
(`TRK`) везде, где принимается и то и другое, и ссылку на запись области
(`TRK/promotion#3`) — от ссылки на запись проекта (`TRK#7`).

## Описание и причина

Описание — короткое «что это» не длиннее того же предела, что у проекта, по той же
причине: оно поедет в карточке каждой задачи области (`TRK#16`, часть 2; поле задачи
— TRK-556). Причина архивирования и восстановления обязательна в обе стороны, как у
проекта.
"""

import re
from dataclasses import dataclass

from app.domain.errors import (
    AreaDescriptionTooLongError,
    AreaReasonRequiredError,
    InvalidAreaKeyError,
)
from app.domain.projects import (
    MAX_PROJECT_DESCRIPTION_LENGTH,
    MAX_PROJECT_REASON_LENGTH,
    PROJECT_KEY_PATTERN,
    normalize_project_key,
)

#: Ключ области: строчная латиница, цифры и дефис; начало и конец — буква или цифра,
#: чтобы дефис по краю (`-promo`, `promo-`) не выглядел опечаткой адреса.
AREA_KEY_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
_AREA_KEY_RE = re.compile(AREA_KEY_PATTERN)

#: Верхняя граница длины ключа по шаблону: под неё задана колонка `areas.key`.
MAX_AREA_KEY_LENGTH = 32

#: Разделитель адреса области: `TRK/promotion`.
ADDRESS_SEPARATOR = "/"

#: Форма адреса в подробностях отказа: по ней агент чинит запрос.
AREA_ADDRESS_SHAPE = f"<PROJECT>{ADDRESS_SEPARATOR}<area key>"

_PROJECT_KEY_RE = re.compile(PROJECT_KEY_PATTERN)

#: Предел описания области в знаках — тот же, что у проекта (TRK#57). Под
#: него же заведено ограничение `ck_areas_description_length`.
MAX_AREA_DESCRIPTION_LENGTH = MAX_PROJECT_DESCRIPTION_LENGTH

#: Предел причины архивирования и восстановления — тот же, что у проекта.
MAX_AREA_REASON_LENGTH = MAX_PROJECT_REASON_LENGTH


@dataclass(frozen=True, slots=True)
class AreaAddress:
    """Адрес области: ключ проекта в верхнем регистре и ключ области в нижнем.

    Канонический вид обеих частей, но не проверенный шаблон ключа области: адресация
    мягкая (`TRK/api#22`, «Адресация мягкая, создание строгое»), и адрес с ключом не
    по шаблону ищется и не находится (`area_not_found`), а не отвергается формой.
    """

    project_key: str
    key: str

    def __str__(self) -> str:
        return format_area_address(self.project_key, self.key)


def format_area_address(project_key: str, key: str) -> str:
    """Адрес области из ключа проекта и ключа области: `TRK/promotion`."""
    return f"{project_key}{ADDRESS_SEPARATOR}{key}"


def is_area_address(value: str) -> bool:
    """Называет ли строка область, а не проект: в адресе области есть косая черта.

    По этому признаку инструменты, принимающие ключ проекта или адрес области, решают,
    кого ищут; форму каждой части проверяет уже поиск.
    """
    return ADDRESS_SEPARATOR in value


def normalize_area_key(key: str) -> str:
    """Канонический вид ключа: без пробелов по краям, в нижнем регистре."""
    return key.strip().lower()


def parse_area_address(value: str) -> AreaAddress:
    """Разбирает адрес для поиска: обе части канонизируются, шаблон ключа не проверяется.

    Строка без косой черты — не адрес области: это ключ проекта, и звать сюда её не
    должны (`is_area_address`). Разбор по первой косой черте: в ключе проекта её не
    бывает, а лишняя справа останется в ключе области и не найдётся.
    """
    project_key, _, key = value.partition(ADDRESS_SEPARATOR)
    return AreaAddress(project_key=normalize_project_key(project_key), key=normalize_area_key(key))


def validate_new_area_address(value: str) -> AreaAddress:
    """Адрес новой области: косая черта, ключ проекта по форме, ключ по шаблону.

    Отказ один — `invalid_area_key` — с причиной в `details.reason`: `not_an_address`
    (нет косой черты или пустая левая часть) или `pattern_mismatch` (ключ не по шаблону).
    Есть ли такой проект, проверяет сценарий: домен в базу не ходит.
    """
    if not is_area_address(value):
        raise InvalidAreaKeyError(
            details={"key": value, "reason": "not_an_address", "expected": AREA_ADDRESS_SHAPE}
        )
    address = parse_area_address(value)
    if not _PROJECT_KEY_RE.match(address.project_key):
        raise InvalidAreaKeyError(
            details={"key": value, "reason": "not_an_address", "expected": AREA_ADDRESS_SHAPE}
        )
    if not _AREA_KEY_RE.match(address.key):
        raise InvalidAreaKeyError(
            details={"key": value, "reason": "pattern_mismatch", "pattern": AREA_KEY_PATTERN}
        )
    return address


def is_area_key(key: str) -> bool:
    """Ключ уже в каноническом виде и по шаблону — для разбора ссылки `TRK/promotion#3`."""
    return _AREA_KEY_RE.match(key) is not None


def validate_area_description(description: str) -> str:
    """Описание без пробелов по краям; длиннее предела — `area_description_too_long`."""
    normalized = description.strip()
    if len(normalized) > MAX_AREA_DESCRIPTION_LENGTH:
        raise AreaDescriptionTooLongError(
            details={"length": len(normalized), "max_length": MAX_AREA_DESCRIPTION_LENGTH}
        )
    return normalized


def require_area_reason(reason: str | None, *, address: str, action: str) -> str:
    """Причина `archive`/`restore` без пробелов по краям; пустая — `area_reason_required`."""
    normalized = (reason or "").strip()
    if not normalized:
        raise AreaReasonRequiredError(details={"key": address, "action": action})
    return normalized
