"""Справочники очереди: статусы, типы задач, резолюции.

Три справочника устроены одинаково — ключ, отображаемое название, область действия,
признак активности, — поэтому их общие правила описаны здесь один раз. Отличается
только собственное поле: у статуса это обязательная категория, у типа задачи — иконка.

Область действия: запись либо глобальная (доступна всем очередям), либо локальная для
одной очереди. Адресация повторяет договорённость о полях из задачи 04: глобальная
запись адресуется голым ключом (`open`), локальная — с префиксом очереди (`TRK.open`).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import InvalidCatalogKeyError, InvalidCatalogRefError
from app.domain.queues import normalize_queue_key, validate_queue_key


class StatusCategory(StrEnum):
    """Смысл статуса для машины: где задача находится в процессе.

    Категория важнее самого статуса. Доски, прогресс проектов и правила автоматики
    опираются на неё, а не на название и не на ключ: команда переименовывает «Закрыт»
    в «Готово», и ничего не ломается. Поэтому категория обязательна и пустой быть не может.
    """

    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class CatalogKind(StrEnum):
    """Какой именно справочник. Нужен там, где код общий для всех трёх.

    Значения совпадают с префиксами кодов ошибок (`status_not_found`,
    `issue_type_in_use`) — по ним же строятся `details` в ответах.
    """

    STATUS = "status"
    ISSUE_TYPE = "issue_type"
    RESOLUTION = "resolution"


# Ключи справочников — snake_case латиницей, как ключи полей в соглашениях.
# Точка в шаблон не входит намеренно: она разделяет очередь и ключ в ссылке `TRK.open`,
# и ключ с точкой сделал бы разбор ссылки неоднозначным.
CATALOG_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
MAX_CATALOG_KEY_LENGTH = 64

_CATALOG_KEY_RE = re.compile(CATALOG_KEY_PATTERN)

#: Разделитель ссылки на локальную запись: `<КЛЮЧ ОЧЕРЕДИ>.<ключ записи>`.
CATALOG_REF_SEPARATOR = "."


@dataclass(frozen=True, slots=True)
class CatalogRef:
    """Разобранная ссылка на запись справочника.

    `queue_key is None` — запись глобальная. Разбор и сборка ссылки живут рядом,
    чтобы формат нельзя было случайно продублировать по-своему в другом месте.
    """

    key: str
    queue_key: str | None = None

    @property
    def is_global(self) -> bool:
        return self.queue_key is None

    def __str__(self) -> str:
        return format_catalog_ref(self.key, queue_key=self.queue_key)


def normalize_catalog_key(key: str) -> str:
    """Канонический вид ключа справочника: без пробелов по краям, в нижнем регистре."""
    return key.strip().lower()


def validate_catalog_key(key: str, *, kind: CatalogKind) -> str:
    """Проверяет ключ записи справочника и возвращает канонический вид."""
    normalized = normalize_catalog_key(key)
    if not _CATALOG_KEY_RE.match(normalized):
        raise InvalidCatalogKeyError(
            details={
                "kind": kind.value,
                "key": key,
                "reason": "pattern_mismatch",
                "pattern": CATALOG_KEY_PATTERN,
            },
        )
    return normalized


def format_catalog_ref(key: str, *, queue_key: str | None) -> str:
    """Собирает ссылку: глобальная запись — голый ключ, локальная — с префиксом очереди."""
    if queue_key is None:
        return key
    return f"{queue_key}{CATALOG_REF_SEPARATOR}{key}"


def parse_catalog_ref(ref: str, *, kind: CatalogKind) -> CatalogRef:
    """Разбирает ссылку `open` или `TRK.open` и проверяет обе половины.

    Ссылка приезжает из пути URL и из тела запроса, поэтому проверяется здесь целиком:
    ключ очереди — по шаблону очередей, ключ записи — по шаблону справочников. Всё,
    что не разобралось, — `invalid_catalog_ref` с указанием ожидаемого формата.

    Регистр приводится к каноническому: `trk.OPEN` находит ту же запись, что и
    `TRK.open`. Это общее для проекта правило — адресация существующего объекта мягкая,
    создание строгое (шаблон стоит в схеме создания). Иначе один и тот же ключ REST
    отвергал бы, а MCP и фоновые вызовы, идущие мимо схем FastAPI, выполняли бы.
    """
    candidate = ref.strip()
    if not candidate:
        raise InvalidCatalogRefError(details={"kind": kind.value, "ref": ref, "reason": "empty"})

    queue_part, separator, key_part = candidate.partition(CATALOG_REF_SEPARATOR)
    if not separator:
        return CatalogRef(key=validate_catalog_key(candidate, kind=kind))
    if CATALOG_REF_SEPARATOR in key_part:
        raise InvalidCatalogRefError(
            details={
                "kind": kind.value,
                "ref": ref,
                "reason": "too_many_separators",
                "expected": f"<QUEUE>{CATALOG_REF_SEPARATOR}<key> or <key>",
            },
        )
    return CatalogRef(
        key=validate_catalog_key(key_part, kind=kind),
        queue_key=validate_queue_key(queue_part),
    )


def build_catalog_ref(key: str, *, queue_key: str | None, kind: CatalogKind) -> CatalogRef:
    """Проверенная ссылка из двух половин: так её собирают тела запросов на создание."""
    return CatalogRef(
        key=validate_catalog_key(key, kind=kind),
        queue_key=None if queue_key is None else validate_queue_key(queue_key),
    )


def normalize_optional_queue_key(queue_key: str | None) -> str | None:
    """Ключ очереди или `None` для глобальной области — без проверки по шаблону."""
    return None if queue_key is None else normalize_queue_key(queue_key)


@dataclass(frozen=True, slots=True)
class SeedEntry:
    """Одна запись начального набора справочников.

    Тот же набор записан литералами в миграции: она создаёт эти строки на свежей базе
    и не имеет права зависеть от кода приложения. Совпадение стережёт тест
    `tests/test_catalogs_service.py`.
    """

    key: str
    name: str
    category: StatusCategory | None = None
    icon: str = ""


# Начальный набор — обычные глобальные записи, а не зашитый справочник: их можно
# переименовать, отключить и дополнить своими. Названия на русском намеренно: это
# пользовательские данные, единственное место, где соглашения разрешают не английский.
INITIAL_STATUSES: tuple[SeedEntry, ...] = (
    SeedEntry(key="open", name="Открыт", category=StatusCategory.NEW),
    # `noqa` ровно на одной строке и по делу: RUF001 стережёт английский в служебных
    # строках, но однобуквенное слово «В» он не может отличить от латинской `B` —
    # у слова из одного символа нет контекста, по которому определяется алфавит.
    # Переименовывать пользовательское название ради линтера неправильно.
    SeedEntry(key="in_progress", name="В работе", category=StatusCategory.IN_PROGRESS),  # noqa: RUF001
    SeedEntry(key="closed", name="Закрыт", category=StatusCategory.DONE),
)

INITIAL_ISSUE_TYPES: tuple[SeedEntry, ...] = (
    SeedEntry(key="task", name="Задача", icon="task"),
    SeedEntry(key="bug", name="Баг", icon="bug"),
    SeedEntry(key="epic", name="Эпик", icon="epic"),
)

INITIAL_RESOLUTIONS: tuple[SeedEntry, ...] = (
    SeedEntry(key="done", name="Сделано"),
    SeedEntry(key="rejected", name="Отклонено"),
    SeedEntry(key="duplicate", name="Дубликат"),
)

#: Чем новая очередь укомплектована по умолчанию, если создающий не выбрал иного.
DEFAULT_STATUS_KEY = "open"
DEFAULT_ISSUE_TYPE_KEY = "task"
