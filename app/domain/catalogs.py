"""Справочники очереди: статусы, типы задач, резолюции.

Три справочника устроены одинаково — ключ, отображаемое название, область действия,
признак активности, — поэтому их общие правила описаны здесь один раз. Отличается
только собственное поле: у статуса это обязательная категория, у типа задачи — иконка.

Область действия: запись либо глобальная (доступна всем очередям), либо локальная для
одной очереди. Глобальная запись адресуется голым ключом (`open`), локальная — с
префиксом очереди (`TRK.open`).

Сам разбор ссылки живёт не здесь, а в `app/domain/refs.py`: тот же формат у ключей
реестра полей (`TRK.severity`), и две реализации одного формата рано или поздно
разошлись бы. Функции ниже — тонкие обёртки, добавляющие к общей механике вид
справочника и его коды ошибок.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import InvalidCatalogKeyError, InvalidCatalogRefError
from app.domain.queues import normalize_queue_key
from app.domain.refs import (
    MAX_SCOPED_KEY_LENGTH,
    REF_SEPARATOR,
    SCOPED_KEY_PATTERN,
    ScopedRef,
    build_scoped_ref,
    format_scoped_ref,
    normalize_scoped_key,
    parse_scoped_ref,
    validate_scoped_key,
)


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


#: Шаблон ключа справочника — общий шаблон ключа с областью действия. Точка в него не
#: входит намеренно: она разделяет очередь и ключ в ссылке `TRK.open`.
CATALOG_KEY_PATTERN = SCOPED_KEY_PATTERN
MAX_CATALOG_KEY_LENGTH = MAX_SCOPED_KEY_LENGTH

#: Разделитель ссылки на локальную запись: `<КЛЮЧ ОЧЕРЕДИ>.<ключ записи>`.
CATALOG_REF_SEPARATOR = REF_SEPARATOR

#: Разобранная ссылка на запись справочника. Тот же тип, что у ссылки на поле:
#: формат один, и различать их нечем — различается только вид объекта в ошибках.
CatalogRef = ScopedRef


def normalize_catalog_key(key: str) -> str:
    """Канонический вид ключа справочника: без пробелов по краям, в нижнем регистре."""
    return normalize_scoped_key(key)


def validate_catalog_key(key: str, *, kind: CatalogKind) -> str:
    """Проверяет ключ записи справочника и возвращает канонический вид."""
    return validate_scoped_key(key, kind=kind.value, error=InvalidCatalogKeyError)


def format_catalog_ref(key: str, *, queue_key: str | None) -> str:
    """Собирает ссылку: глобальная запись — голый ключ, локальная — с префиксом очереди."""
    return format_scoped_ref(key, queue_key=queue_key)


def parse_catalog_ref(ref: str, *, kind: CatalogKind) -> CatalogRef:
    """Разбирает ссылку `open` или `TRK.open` и проверяет обе половины.

    Регистр приводится к каноническому: `trk.OPEN` находит ту же запись, что и
    `TRK.open`. Это общее для проекта правило — адресация существующего объекта мягкая,
    создание строгое (шаблон стоит в схеме создания). Иначе один и тот же ключ REST
    отвергал бы, а MCP и фоновые вызовы, идущие мимо схем FastAPI, выполняли бы.
    """
    return parse_scoped_ref(
        ref,
        kind=kind.value,
        key_error=InvalidCatalogKeyError,
        ref_error=InvalidCatalogRefError,
    )


def build_catalog_ref(key: str, *, queue_key: str | None, kind: CatalogKind) -> CatalogRef:
    """Проверенная ссылка из двух половин: так её собирают тела запросов на создание."""
    return build_scoped_ref(
        key,
        queue_key=queue_key,
        kind=kind.value,
        key_error=InvalidCatalogKeyError,
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

#: Ключ типа задачи «эпик». Эпик — верхний уровень планирования, и связи опираются на
#: этот ключ: задаче такого типа нельзя назначить родителя (`app/domain/links.py`).
#: Сравнивается именно ключ, а не ссылка: локальный тип очереди `TRK.epic` — тоже эпик,
#: иначе очередь со своим набором типов молча потеряла бы правило.
EPIC_ISSUE_TYPE_KEY = "epic"
