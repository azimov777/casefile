"""Реестр полей задачи: типы значений, формат хранения в JSONB, валидатор.

Чистый Python: ни ORM, ни HTTP. Всё, что здесь описано, одинаково верно для REST,
MCP, автоматики и поиска.

## Адресация

Поле либо глобальное (доступно всем очередям), либо локальное для одной очереди.
Глобальное адресуется голым ключом (`severity`), локальное — с префиксом очереди
(`TRK.severity`). Разбор и сборка ссылки — общие с справочниками, из
`app/domain/refs.py`: формат один, и две реализации разошлись бы.

## Формат хранения значения в `values JSONB`

Формат зафиксирован здесь и обязателен для всех: задачи, история изменений, поиск и
автоматика читают одни и те же байты, и разночтения дадут молчаливые баги.

- **Ключ объекта `values` — ссылка на поле, а не ключ.** `{"severity": ...}` для
  глобального поля, `{"TRK.severity": ...}` для локального. Иначе глобальное
  `severity` и локальное `TRK.severity` попали бы в один ключ и затёрли друг друга.
- **Значения отсутствующего поля в объекте нет вовсе.** `null` в `values` не хранится
  никогда: «поля нет» и «поле есть, но пустое» — одно состояние, и два способа его
  записать неизбежно разъехались бы. Снятие значения удаляет ключ.
- **Множественное поле хранит массив** значений того же вида; пустых массивов в
  хранилище не бывает — пустой набор означает «значения нет», и ключ удаляется.
- **`string`, `text`, `enum`** — строка JSON. У `enum` это ключ варианта, а не его
  отображаемое название: название можно переименовать, ключ — нет.
- **`number`** — число JSON (целое или дробное). Строка числом не считается.
- **`boolean`** — `true` / `false` JSON.
- **`date`** — строка `YYYY-MM-DD` без времени и без зоны.
- **`datetime`** — строка ISO 8601, приведённая к UTC: `2026-08-27T10:00:00+00:00`.
  Значение без зоны отвергается: соглашения требуют времени с зоной, а домысливание
  зоны за клиента дало бы сдвиг, который заметят через месяц.
- **`actor`** — ключ актора (`alice`), а не его UUID: ключ уникален на установку,
  неизменяем и читаем в истории изменений и в дампе JSONB глазами.
- **`issue`** — ключ задачи (`TRK-123`). Ключи задач не меняются и не переиспользуются,
  поэтому ссылка остаётся верной даже после переноса задачи.

Существование актора и задачи домен проверить не может — это дело сценария
(`app/services/fields.py`). Здесь проверяется только форма ссылки.

## Валидатор

`validate_values` возвращает **все** замечания сразу, а не первое: фронту нужно
подсветить всю форму за один ответ, а агенту — исправить запрос за одну попытку.
Причина каждого замечания — стабильная строка в `snake_case`; список причин целиком:

| Причина | Когда |
|---|---|
| `invalid_ref` | ключ в `values` не разбирается как ссылка на поле |
| `duplicate_field` | два ключа в `values` указывают на одно поле |
| `unknown_field` | поля с такой ссылкой в наборе нет |
| `required` | обязательное поле не заполнено |
| `type_mismatch` | значение не того типа JSON (`expected` — какой ожидался) |
| `not_allowed` | значение вне списка вариантов перечисления (`allowed`) |
| `expected_array` | множественное поле получило одиночное значение |
| `unexpected_array` | одиночное поле получило массив |
| `too_many_values` | в массиве больше значений, чем разрешено (`max`) |
| `duplicate_values` | одно значение повторяется в массиве |
| `too_long` | строка длиннее допустимого (`max`) |
| `multiline_not_allowed` | перевод строки в однострочном поле |
| `invalid_date` / `invalid_datetime` | строка не разбирается (`expected` — формат) |
| `timezone_required` | дата со временем пришла без зоны |
| `invalid_actor_key` / `invalid_issue_key` | ссылка не той формы |

Сценарий добавляет к этому списку свои причины, которым нужна база: `not_applicable`,
`hidden`, `actor_not_found`, `issue_not_found`.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from app.core.errors import AppError
from app.domain.actors import validate_actor_key
from app.domain.errors import (
    InvalidActorKeyError,
    InvalidFieldKeyError,
    InvalidFieldRefError,
    InvalidIssueKeyError,
    InvalidQueueKeyError,
)
from app.domain.queues import format_issue_key, parse_issue_key
from app.domain.refs import (
    MAX_SCOPED_KEY_LENGTH,
    SCOPED_KEY_PATTERN,
    ScopedRef,
    build_scoped_ref,
    format_scoped_ref,
    normalize_scoped_key,
    parse_scoped_ref,
    validate_scoped_key,
)


class FieldValueType(StrEnum):
    """Тип значения поля. Определяет и проверку, и форму записи в JSONB.

    Тип выбирается один раз при создании: у поля с данными менять его нельзя — уже
    записанные значения задним числом стали бы значить другое.
    """

    STRING = "string"
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    ENUM = "enum"
    ACTOR = "actor"
    ISSUE = "issue"


#: Что различает `string` и `text`, кроме подсказки фронту: длина и переводы строк.
#: Без этой разницы два типа отличались бы только названием, и выбор между ними был
#: бы делом вкуса, а не смысла.
MAX_STRING_LENGTH = 255
MAX_TEXT_LENGTH = 32_768

#: Потолок на число значений множественного поля. Ограничение неочевидное, поэтому
#: названо прямо: `values` целиком уезжает в каждый ответ с задачей и в каждое
#: событие, и поле на десять тысяч значений сделало бы задачу неподъёмной.
MAX_MULTIPLE_VALUES = 100

#: Максимум вариантов у перечисления — по той же причине.
MAX_ENUM_OPTIONS = 200

#: Шаблон и предел длины ключа поля — общие с ключами справочников.
FIELD_KEY_PATTERN = SCOPED_KEY_PATTERN
MAX_FIELD_KEY_LENGTH = MAX_SCOPED_KEY_LENGTH

#: Вид объекта в `details` ошибок: по нему клиент отличает ссылку на поле от ссылки
#: на запись справочника.
FIELD_KIND = "field"

# Системные поля задачи живут отдельными колонками (см. `docs/CONCEPT.md`), и язык
# запросов из задачи 12 будет разрешать эти имена в колонки, а не в `values`.
# Кастомное поле с таким ключом стало бы недостижимым для поиска, поэтому ключ
# отвергается при создании, а не молча уводится в тень.
SYSTEM_FIELD_KEYS = frozenset(
    {
        "key",
        "queue",
        "type",
        "issue_type",
        "status",
        "resolution",
        "priority",
        "summary",
        "description",
        "author",
        "assignee",
        "followers",
        "deadline",
        "tags",
        "links",
        "comments",
        "checklist",
        "values",
        "version",
        "created_at",
        "updated_at",
        "project",
        "sprint",
    }
)

#: Разобранная ссылка на поле. Тот же тип, что у ссылки на запись справочника:
#: формат один на весь проект.
FieldRef = ScopedRef


def normalize_field_key(key: str) -> str:
    """Канонический вид ключа поля: без пробелов по краям, в нижнем регистре."""
    return normalize_scoped_key(key)


def validate_field_key(key: str) -> str:
    """Проверяет ключ поля и возвращает канонический вид.

    Помимо шаблона отвергает имена системных полей: они уже заняты колонками задачи.
    """
    normalized = validate_scoped_key(key, kind=FIELD_KIND, error=InvalidFieldKeyError)
    if normalized in SYSTEM_FIELD_KEYS:
        raise InvalidFieldKeyError(
            details={
                "kind": FIELD_KIND,
                "key": key,
                "reason": "reserved",
                "reserved": sorted(SYSTEM_FIELD_KEYS),
            },
        )
    return normalized


def format_field_ref(key: str, *, queue_key: str | None) -> str:
    """Собирает ссылку: глобальное поле — голый ключ, локальное — с префиксом очереди."""
    return format_scoped_ref(key, queue_key=queue_key)


def parse_field_ref(ref: str) -> FieldRef:
    """Разбирает ссылку `severity` или `TRK.severity`.

    Та же функция, что разбирает `TRK.open` у справочников: формат один, и второй
    разбор рано или поздно истолковал бы одну и ту же строку иначе.
    """
    return parse_scoped_ref(
        ref,
        kind=FIELD_KIND,
        key_error=InvalidFieldKeyError,
        ref_error=InvalidFieldRefError,
    )


def build_field_ref(key: str, *, queue_key: str | None) -> FieldRef:
    """Проверенная ссылка из двух половин: так её собирают тела запросов на создание."""
    reference = build_scoped_ref(
        key,
        queue_key=queue_key,
        kind=FIELD_KIND,
        key_error=InvalidFieldKeyError,
    )
    validate_field_key(reference.key)
    return reference


@dataclass(frozen=True, slots=True)
class FieldOption:
    """Один вариант перечисления: машинный ключ и отображаемое название.

    Хранится ключ, показывается название — как у справочников. Переименование
    варианта не трогает записанные значения.
    """

    key: str
    name: str


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Описание поля глазами валидатора.

    Отдельный тип, а не ORM-модель: домен не знает про SQLAlchemy, а валидатор должен
    проверяться без базы. Сценарий собирает `FieldSpec` из модели одной функцией.
    """

    ref: str
    value_type: FieldValueType
    is_multiple: bool = False
    is_required: bool = False
    options: tuple[FieldOption, ...] = ()
    default: Any = None

    @property
    def option_keys(self) -> tuple[str, ...]:
        return tuple(option.key for option in self.options)


@dataclass(frozen=True, slots=True)
class FieldIssue:
    """Одно замечание валидатора: какое поле, что не так, что допустимо.

    Ложится прямо в `details.fields` ответа — форму задают соглашения проекта.
    """

    field: str
    reason: str
    context: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_details(self) -> dict[str, Any]:
        return {"field": self.field, "reason": self.reason, **self.context}


@dataclass(frozen=True, slots=True)
class ValuesOutcome:
    """Результат проверки: приведённые значения и полный список замечаний.

    Значения возвращаются даже при непустом списке замечаний — по разобравшимся полям.
    Пользоваться ими можно только когда `issues` пуст; сценарий на этом и настаивает,
    превращая непустой список в `field_values_invalid`.
    """

    values: dict[str, Any]
    issues: tuple[FieldIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


class _Rejected(Exception):
    """Внутренний сигнал «значение не подошло». Наружу не выходит.

    Исключение, а не возвращаемый код: приведение типов вложенное (массив → элемент →
    строка → дата), и протаскивать через него пару «значение или ошибка» руками
    значило бы писать проверку после каждого шага.
    """

    def __init__(self, reason: str, **context: Any) -> None:
        self.reason = reason
        self.context = context
        super().__init__(reason)


#: Отличает «ключа в `values` не было» от «ключ был со значением `null`». Первое
#: включает значение по умолчанию, второе снимает значение — разница существенная.
_MISSING = object()


def normalize_value_keys(
    raw: Mapping[str, Any],
) -> tuple[dict[str, Any], list[FieldIssue]]:
    """Приводит ключи `values` к каноническим ссылкам.

    `trk.SEVERITY` и `TRK.severity` — одно и то же поле: адресация в проекте мягкая.
    Неразбираемый ключ не отбрасывается молча, а становится замечанием; два ключа,
    сошедшиеся в одну ссылку, — тоже, иначе один тихо затёр бы другой.
    """
    normalized: dict[str, Any] = {}
    issues: list[FieldIssue] = []
    for key, value in raw.items():
        try:
            ref = str(parse_field_ref(key))
        except (InvalidFieldKeyError, InvalidFieldRefError) as exc:
            issues.append(FieldIssue(field=key, reason="invalid_ref", context=_context(exc)))
            continue
        if ref in normalized:
            issues.append(FieldIssue(field=ref, reason="duplicate_field", context={"key": key}))
            continue
        normalized[ref] = value
    return normalized, issues


def apply_value_changes(
    current: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Накладывает частичное изменение на текущие значения.

    Правило одно и оно же записано в формате хранения: `null` снимает значение,
    отсутствующий ключ не трогает поле. Функция живёт здесь, а не в сценарии задачи,
    чтобы у REST, MCP и автоматики не появилось трёх толкований одного PATCH.

    Ключ, который не разбирается как ссылка, остаётся как есть: доложить о нём —
    дело валидатора, и делать это дважды в разных местах не нужно.
    """
    merged = dict(current)
    for key, value in changes.items():
        try:
            ref = str(parse_field_ref(key))
        except InvalidFieldKeyError, InvalidFieldRefError:
            ref = key
        if value is None:
            merged.pop(ref, None)
        else:
            merged[ref] = value
    return merged


def validate_values(
    raw: Mapping[str, Any],
    specs: Sequence[FieldSpec],
) -> ValuesOutcome:
    """Проверяет набор значений против набора полей и приводит типы.

    Набор значений считается полным: обязательные поля проверяются по нему целиком.
    Для частичного обновления вызывающий сначала склеивает текущее состояние с
    изменениями через `apply_value_changes`, а потом проверяет результат — иначе PATCH
    смог бы оставить задачу без обязательного поля.

    Возвращает **все** замечания, а не первое.
    """
    values, issues = normalize_value_keys(raw)
    by_ref = {spec.ref: spec for spec in specs}

    for ref in values:
        if ref not in by_ref:
            issues.append(FieldIssue(field=ref, reason="unknown_field"))

    result: dict[str, Any] = {}
    for spec in specs:
        given = values.get(spec.ref, _MISSING)
        if given is _MISSING and spec.default is not None:
            # Значение по умолчанию подставляется только за отсутствующий ключ.
            # Явный `null` — это осознанное «значения нет», и перебивать его
            # умолчанием значило бы не дать очистить поле вовсе.
            result[spec.ref] = spec.default
            continue
        if given is _MISSING or given is None:
            if spec.is_required:
                issues.append(_required_issue(spec))
            continue

        stored, field_issues = _coerce_field(spec, given)
        if field_issues:
            issues.extend(field_issues)
            continue
        if stored is None:
            # Пустая строка и пустой массив означают «значения нет»: хранить их
            # отдельным способом сказать то же самое проект не даёт.
            if spec.is_required:
                issues.append(_required_issue(spec))
            continue
        result[spec.ref] = stored

    return ValuesOutcome(values=result, issues=tuple(issues))


def _required_issue(spec: FieldSpec) -> FieldIssue:
    context: dict[str, Any] = {"type": spec.value_type.value}
    if spec.value_type is FieldValueType.ENUM:
        context["allowed"] = list(spec.option_keys)
    return FieldIssue(field=spec.ref, reason="required", context=context)


def _coerce_field(spec: FieldSpec, given: Any) -> tuple[Any, list[FieldIssue]]:
    """Приводит значение поля к форме хранения. `None` в ответе — «значения нет»."""
    if spec.is_multiple:
        return _coerce_multiple(spec, given)

    if isinstance(given, list):
        return None, [FieldIssue(field=spec.ref, reason="unexpected_array")]
    try:
        stored = _coerce_single(spec, given)
    except _Rejected as rejected:
        return None, [FieldIssue(field=spec.ref, reason=rejected.reason, context=rejected.context)]
    return stored, []


def _coerce_multiple(spec: FieldSpec, given: Any) -> tuple[Any, list[FieldIssue]]:
    if not isinstance(given, list):
        return None, [
            FieldIssue(field=spec.ref, reason="expected_array", context={"expected": "array"})
        ]
    if len(given) > MAX_MULTIPLE_VALUES:
        return None, [
            FieldIssue(
                field=spec.ref,
                reason="too_many_values",
                context={"max": MAX_MULTIPLE_VALUES, "got": len(given)},
            )
        ]

    stored: list[Any] = []
    issues: list[FieldIssue] = []
    for index, item in enumerate(given):
        if item is None:
            issues.append(
                FieldIssue(field=spec.ref, reason="type_mismatch", context={"index": index})
            )
            continue
        try:
            value = _coerce_single(spec, item)
        except _Rejected as rejected:
            issues.append(
                FieldIssue(
                    field=spec.ref,
                    reason=rejected.reason,
                    context={"index": index, **rejected.context},
                )
            )
            continue
        if value is None:
            issues.append(
                FieldIssue(field=spec.ref, reason="empty_value", context={"index": index})
            )
            continue
        stored.append(value)

    if issues:
        return None, issues
    if len(set(stored)) != len(stored):
        return None, [FieldIssue(field=spec.ref, reason="duplicate_values")]
    # Пустой массив приравнивается к отсутствию значения: см. формат хранения.
    return (stored or None), []


def _coerce_single(spec: FieldSpec, given: Any) -> Any:
    """Одно значение в форму хранения. Бросает `_Rejected` с причиной."""
    match spec.value_type:
        case FieldValueType.STRING:
            return _coerce_line(given)
        case FieldValueType.TEXT:
            return _coerce_text(given)
        case FieldValueType.NUMBER:
            return _coerce_number(given)
        case FieldValueType.BOOLEAN:
            return _coerce_boolean(given)
        case FieldValueType.DATE:
            return _coerce_date(given)
        case FieldValueType.DATETIME:
            return _coerce_datetime(given)
        case FieldValueType.ENUM:
            return _coerce_enum(given, spec.option_keys)
        case FieldValueType.ACTOR:
            return _coerce_actor(given)
        case FieldValueType.ISSUE:
            return _coerce_issue(given)


def _require_string(given: Any) -> str:
    if not isinstance(given, str):
        raise _Rejected("type_mismatch", expected="string", got=_json_type(given))
    return given.strip()


def _coerce_line(given: Any) -> str | None:
    value = _require_string(given)
    if "\n" in value or "\r" in value:
        raise _Rejected("multiline_not_allowed", hint="use the text value type")
    if len(value) > MAX_STRING_LENGTH:
        raise _Rejected("too_long", max=MAX_STRING_LENGTH, got=len(value))
    return value or None


def _coerce_text(given: Any) -> str | None:
    value = _require_string(given)
    if len(value) > MAX_TEXT_LENGTH:
        raise _Rejected("too_long", max=MAX_TEXT_LENGTH, got=len(value))
    return value or None


def _coerce_number(given: Any) -> float | int:
    # `bool` — подкласс `int`, поэтому проверяется до числа: иначе `true` тихо стало
    # бы единицей, и поле «оценка» приняло бы флаг.
    if isinstance(given, bool) or not isinstance(given, int | float):
        raise _Rejected("type_mismatch", expected="number", got=_json_type(given))
    return given


def _coerce_boolean(given: Any) -> bool:
    if not isinstance(given, bool):
        raise _Rejected("type_mismatch", expected="boolean", got=_json_type(given))
    return given


def _coerce_date(given: Any) -> str | None:
    value = _require_string(given)
    if not value:
        return None
    # Строгий разбор вместо `date.fromisoformat` в одиночку: тот принимает и
    # `20260827`, и форму с неделями, и в базе оказались бы три написания одной даты.
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise _Rejected("invalid_date", expected="YYYY-MM-DD", got=value) from exc
    return parsed.isoformat()


def _coerce_datetime(given: Any) -> str | None:
    value = _require_string(given)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _Rejected(
            "invalid_datetime", expected="ISO 8601 with a UTC offset", got=value
        ) from exc
    if parsed.tzinfo is None:
        raise _Rejected("timezone_required", expected="ISO 8601 with a UTC offset", got=value)
    return parsed.astimezone(UTC).isoformat()


def _coerce_enum(given: Any, allowed: tuple[str, ...]) -> str | None:
    value = _require_string(given)
    if not value:
        return None
    if value not in allowed:
        raise _Rejected("not_allowed", allowed=list(allowed), got=value)
    return value


def _coerce_actor(given: Any) -> str | None:
    value = _require_string(given)
    if not value:
        return None
    try:
        return validate_actor_key(value)
    except InvalidActorKeyError as exc:
        raise _Rejected("invalid_actor_key", **_context(exc)) from exc


def _coerce_issue(given: Any) -> str | None:
    value = _require_string(given)
    if not value:
        return None
    try:
        queue_key, number = parse_issue_key(value)
    except (InvalidIssueKeyError, InvalidQueueKeyError) as exc:
        raise _Rejected("invalid_issue_key", expected="QUEUE-NUMBER", got=value) from exc
    return format_issue_key(queue_key, number)


def _context(error: AppError) -> dict[str, Any]:
    """Подробности чужой ошибки как контекст замечания.

    Ключ `reason` из них выбрасывается намеренно: у замечания причина своя, и чужая
    затёрла бы её при сборке `details` — молча и только в некоторых ветках.
    """
    return {key: value for key, value in error.details.items() if key != "reason"}


def _json_type(value: Any) -> str:
    """Имя типа JSON для сообщения об ошибке: клиент мыслит в JSON, а не в Python."""
    match value:
        case bool():
            return "boolean"
        case int() | float():
            return "number"
        case str():
            return "string"
        case list():
            return "array"
        case dict():
            return "object"
        case None:
            return "null"
        case _:
            return type(value).__name__


def parsed_date(stored: str) -> date:
    """Обратное чтение даты из хранилища. Формат один, разбор — тоже один."""
    return date.fromisoformat(stored)


def parsed_datetime(stored: str) -> datetime:
    """Обратное чтение даты со временем из хранилища."""
    return datetime.fromisoformat(stored)


def referenced_actor_keys(values: Mapping[str, Any], specs: Iterable[FieldSpec]) -> set[str]:
    """Ключи акторов, на которых ссылаются значения: их существование проверяет сценарий."""
    return _referenced(values, specs, FieldValueType.ACTOR)


def referenced_issue_keys(values: Mapping[str, Any], specs: Iterable[FieldSpec]) -> set[str]:
    """Ключи задач, на которые ссылаются значения."""
    return _referenced(values, specs, FieldValueType.ISSUE)


def _referenced(
    values: Mapping[str, Any],
    specs: Iterable[FieldSpec],
    value_type: FieldValueType,
) -> set[str]:
    collected: set[str] = set()
    for spec in specs:
        if spec.value_type is not value_type or spec.ref not in values:
            continue
        stored = values[spec.ref]
        collected.update(stored if isinstance(stored, list) else [stored])
    return collected
