"""Настройки установки: реестр семи параметров и правила их значений.

Слово владельца TRK~31#4: параметры установки, годные человеку, хранятся в базе, правит
администратор, а переменная окружения остаётся умолчанием. Здесь — только правила:
имя, тип, пределы, умолчание кода и имя переменной окружения для каждого из семи.
Таблица и чтение «база → окружение → умолчание» — `app/db` и
`app/services/installation_settings.py`.

В реестре ровно те параметры, которые читаются уже после подъёма базы и не открывают
двери: срок сеанса, срок подключения агента, страница и обрезка MCP, проверка выпуска,
предел файла и срок «не открывали N дней». Всё, что нужно до чтения базы, секреты,
защита, железо и привязка контура остаются переменными окружения и сюда не входят.

Чистый Python: ни ORM, ни HTTP, ни чтения окружения.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from app.domain.errors import InstallationSettingInvalidError, InstallationSettingNotFoundError

#: Значение настройки после разбора.
SettingValue = int | bool | timedelta


class SettingKind(StrEnum):
    """Тип значения: от него зависит разбор строки и запись канонического вида."""

    INTEGER = "integer"
    BOOLEAN = "boolean"
    DURATION = "duration"  # ISO 8601: `P30D`, `PT1H`


_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})
_INTEGER_RE = re.compile(r"^[+-]?[0-9]{1,18}$")
_DURATION_RE = re.compile(
    r"^P(?:([0-9]{1,6})D)?(?:T(?:([0-9]{1,8})H)?(?:([0-9]{1,10})M)?(?:([0-9]{1,12})S)?)?$"
)


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """Правила одной настройки.

    `minimum`/`maximum` — включительно, в единицах настройки (для срока — в секундах;
    у логической их нет). `default` — умолчание кода: его берут, когда нет ни значения в
    базе, ни переменной окружения.
    """

    name: str
    env_var: str
    kind: SettingKind
    default: SettingValue
    minimum: int | None = None
    maximum: int | None = None


_DAY = 24 * 3600

#: Реестр. Порядок — порядок показа. Умолчания совпадают с `Settings` в
#: `app/core/config.py` (тест сверяет).
SETTINGS: tuple[SettingSpec, ...] = (
    SettingSpec(
        "session_hours", "TRACKER_SESSION_HOURS", SettingKind.INTEGER, 168, 1, 24 * 365 * 5
    ),
    SettingSpec(
        "oauth_access_ttl",
        "TRACKER_OAUTH_ACCESS_TTL",
        SettingKind.DURATION,
        timedelta(days=30),
        60,
        365 * _DAY,
    ),
    SettingSpec("mcp_page_size", "TRACKER_MCP_PAGE_SIZE", SettingKind.INTEGER, 25, 1, 200),
    SettingSpec(
        "mcp_text_limit", "TRACKER_MCP_TEXT_LIMIT", SettingKind.INTEGER, 2000, 200, 100_000
    ),
    SettingSpec("release_check", "TRACKER_RELEASE_CHECK", SettingKind.BOOLEAN, True),
    SettingSpec(
        "file_max_bytes",
        "TRACKER_FILE_MAX_BYTES",
        SettingKind.INTEGER,
        25 * 1024 * 1024,
        1,
        1024 * 1024 * 1024,
    ),
    SettingSpec(
        "file_unopened_days", "TRACKER_FILE_UNOPENED_DAYS", SettingKind.INTEGER, 90, 1, 3650
    ),
)

_BY_NAME: Mapping[str, SettingSpec] = {spec.name: spec for spec in SETTINGS}


def get_spec(name: str) -> SettingSpec:
    """Правила настройки по имени; неизвестное имя — `installation_setting_not_found`."""
    spec = _BY_NAME.get(name)
    if spec is None:
        raise InstallationSettingNotFoundError(details={"name": name})
    return spec


def _invalid(spec: SettingSpec, reason: str) -> InstallationSettingInvalidError:
    details: dict[str, object] = {"name": spec.name, "reason": reason}
    if spec.minimum is not None:
        details["minimum"] = spec.minimum
    if spec.maximum is not None:
        details["maximum"] = spec.maximum
    return InstallationSettingInvalidError(details=details)


def parse_value(spec: SettingSpec, raw: str) -> SettingValue:
    """Строка в значение по типу и пределам настройки; иначе `installation_setting_invalid`."""
    text = raw.strip()
    number: int
    match spec.kind:
        case SettingKind.BOOLEAN:
            lowered = text.lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
            raise _invalid(spec, "not_a_boolean")
        case SettingKind.INTEGER:
            if not _INTEGER_RE.match(text):
                raise _invalid(spec, "not_an_integer")
            number = int(text)
        case SettingKind.DURATION:
            found = _DURATION_RE.match(text.upper())
            if text in {"", "P", "PT"} or found is None or text.upper().endswith("T"):
                raise _invalid(spec, "not_a_duration")
            days, hours, minutes, seconds = (int(part or 0) for part in found.groups())
            number = days * _DAY + hours * 3600 + minutes * 60 + seconds
    if spec.minimum is not None and number < spec.minimum:
        raise _invalid(spec, "too_small")
    if spec.maximum is not None and number > spec.maximum:
        raise _invalid(spec, "too_large")
    return timedelta(seconds=number) if spec.kind is SettingKind.DURATION else number


def format_value(spec: SettingSpec, value: SettingValue) -> str:
    """Канонический вид значения для хранения: `true`/`false`, число, `PT…S` секундами."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, timedelta):
        return f"PT{int(value.total_seconds())}S"
    return str(value)
