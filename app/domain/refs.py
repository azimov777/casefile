"""Адресация объекта, у которого есть область действия: глобальная или внутри очереди.

Одна механика на весь проект. Ей пользуются справочники (`open`, `TRK.open`) и реестр
полей (`severity`, `TRK.severity`): формат ссылки у них общий, и разные разборы одной
и той же строки дали бы молчаливое расхождение — поиск нашёл бы одно поле, а
валидатор проверил другое.

Правила формата:

- глобальный объект адресуется голым ключом: `severity`;
- локальный — с префиксом очереди через точку: `TRK.severity`;
- точка в ключ не входит: иначе разбор ссылки стал бы неоднозначным;
- регистр приводится к каноническому (`trk.SEVERITY` → `TRK.severity`): адресация в
  проекте мягкая, строгий шаблон стоит только там, где ключ придумывают.

Конкретный вид объекта модуль не знает: `kind` и классы ошибок передаёт вызывающий,
чтобы коды оставались точными (`invalid_catalog_ref` против `invalid_field_ref`).
"""

import re
from dataclasses import dataclass

from app.core.errors import AppError
from app.domain.queues import validate_queue_key

# Ключ — snake_case латиницей, как требуют соглашения от ключей полей, статусов и типов.
SCOPED_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
MAX_SCOPED_KEY_LENGTH = 64

_SCOPED_KEY_RE = re.compile(SCOPED_KEY_PATTERN)

#: Разделитель ссылки на локальный объект: `<КЛЮЧ ОЧЕРЕДИ>.<ключ>`.
REF_SEPARATOR = "."


@dataclass(frozen=True, slots=True)
class ScopedRef:
    """Разобранная ссылка: ключ и область действия.

    `queue_key is None` — объект глобальный. Разбор и сборка живут рядом, чтобы формат
    нельзя было случайно продублировать по-своему в другом месте.
    """

    key: str
    queue_key: str | None = None

    @property
    def is_global(self) -> bool:
        return self.queue_key is None

    def __str__(self) -> str:
        return format_scoped_ref(self.key, queue_key=self.queue_key)


def normalize_scoped_key(key: str) -> str:
    """Канонический вид ключа: без пробелов по краям, в нижнем регистре."""
    return key.strip().lower()


def validate_scoped_key(key: str, *, kind: str, error: type[AppError]) -> str:
    """Проверяет ключ по общему шаблону и возвращает канонический вид."""
    normalized = normalize_scoped_key(key)
    if not _SCOPED_KEY_RE.match(normalized):
        raise error(
            details={
                "kind": kind,
                "key": key,
                "reason": "pattern_mismatch",
                "pattern": SCOPED_KEY_PATTERN,
            },
        )
    return normalized


def format_scoped_ref(key: str, *, queue_key: str | None) -> str:
    """Собирает ссылку: глобальный объект — голый ключ, локальный — с префиксом очереди."""
    if queue_key is None:
        return key
    return f"{queue_key}{REF_SEPARATOR}{key}"


def parse_scoped_ref(
    ref: str,
    *,
    kind: str,
    key_error: type[AppError],
    ref_error: type[AppError],
) -> ScopedRef:
    """Разбирает `severity` или `TRK.severity` и проверяет обе половины.

    Ссылка приезжает из пути URL, из тела запроса и из строки поиска, поэтому
    проверяется здесь целиком: ключ очереди — по шаблону очередей, ключ объекта — по
    общему шаблону. Всё, что не разобралось, — ошибка с ожидаемым форматом в `details`.
    """
    candidate = ref.strip()
    if not candidate:
        raise ref_error(details={"kind": kind, "ref": ref, "reason": "empty"})

    queue_part, separator, key_part = candidate.partition(REF_SEPARATOR)
    if not separator:
        return ScopedRef(key=validate_scoped_key(candidate, kind=kind, error=key_error))
    if REF_SEPARATOR in key_part:
        raise ref_error(
            details={
                "kind": kind,
                "ref": ref,
                "reason": "too_many_separators",
                "expected": f"<QUEUE>{REF_SEPARATOR}<key> or <key>",
            },
        )
    return ScopedRef(
        key=validate_scoped_key(key_part, kind=kind, error=key_error),
        queue_key=validate_queue_key(queue_part),
    )


def build_scoped_ref(
    key: str,
    *,
    queue_key: str | None,
    kind: str,
    key_error: type[AppError],
) -> ScopedRef:
    """Проверенная ссылка из двух половин: так её собирают тела запросов на создание."""
    return ScopedRef(
        key=validate_scoped_key(key, kind=kind, error=key_error),
        queue_key=None if queue_key is None else validate_queue_key(queue_key),
    )
