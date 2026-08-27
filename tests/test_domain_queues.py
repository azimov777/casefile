"""Домен очередей и справочников без базы: ключи, ссылки, категории.

Правила из `app/domain` одинаково верны для REST, MCP и фоновых процессов, поэтому
проверяются отдельно от всего остального — без сессии, приложения и сети.
"""

import pytest

from app.domain.catalogs import (
    INITIAL_ISSUE_TYPES,
    INITIAL_RESOLUTIONS,
    INITIAL_STATUSES,
    CatalogKind,
    CatalogRef,
    StatusCategory,
    build_catalog_ref,
    format_catalog_ref,
    parse_catalog_ref,
    validate_catalog_key,
)
from app.domain.errors import (
    InvalidCatalogKeyError,
    InvalidCatalogRefError,
    InvalidQueueKeyError,
)
from app.domain.queues import (
    FIRST_ISSUE_NUMBER,
    format_issue_key,
    normalize_queue_key,
    validate_queue_key,
)


@pytest.mark.parametrize("raw", ["TRK", "trk", " TRK ", "Trk"])
def test_queue_key_is_normalised_to_upper_case(raw: str) -> None:
    """Ключ очереди приводится к верхнему регистру: `trk` и `TRK` — одна очередь."""
    assert validate_queue_key(raw) == "TRK"


@pytest.mark.parametrize(
    "raw",
    ["T", "1TRK", "TRK-2", "TRK.OPS", "TRK_OPS", "ОЧЕРЕДЬ", "A" * 17, ""],
)
def test_invalid_queue_keys_are_rejected(raw: str) -> None:
    """Разделители запрещены: ключ очереди входит в ключ задачи `TRK-123`."""
    with pytest.raises(InvalidQueueKeyError):
        validate_queue_key(raw)


def test_queue_key_error_explains_the_pattern() -> None:
    """Агент должен понять, как исправить запрос, не читая исходники."""
    with pytest.raises(InvalidQueueKeyError) as error:
        validate_queue_key("нет")

    assert error.value.details["reason"] == "pattern_mismatch"
    assert "pattern" in error.value.details


def test_issue_key_is_built_from_queue_key_and_number() -> None:
    assert format_issue_key(normalize_queue_key("trk"), FIRST_ISSUE_NUMBER) == "TRK-1"


@pytest.mark.parametrize("raw", ["open", "OPEN", " open "])
def test_catalog_key_is_normalised_to_lower_case(raw: str) -> None:
    assert validate_catalog_key(raw, kind=CatalogKind.STATUS) == "open"


@pytest.mark.parametrize("raw", ["1open", "in progress", "TRK.open", "o", "x" * 65])
def test_invalid_catalog_keys_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidCatalogKeyError):
        validate_catalog_key(raw, kind=CatalogKind.STATUS)


def test_global_reference_is_a_bare_key() -> None:
    parsed = parse_catalog_ref("open", kind=CatalogKind.STATUS)

    assert parsed == CatalogRef(key="open")
    assert parsed.is_global
    assert str(parsed) == "open"


def test_local_reference_carries_the_queue_key() -> None:
    parsed = parse_catalog_ref("TRK.in_review", kind=CatalogKind.STATUS)

    assert parsed == CatalogRef(key="in_review", queue_key="TRK")
    assert not parsed.is_global
    assert str(parsed) == "TRK.in_review"


@pytest.mark.parametrize("raw", ["", "TRK.", ".open", "TRK.a.b", "TRK.in progress"])
def test_malformed_references_are_rejected(raw: str) -> None:
    """Обе половины ссылки проверяются своими шаблонами, а не «на глаз»."""
    with pytest.raises((InvalidCatalogRefError, InvalidCatalogKeyError, InvalidQueueKeyError)):
        parse_catalog_ref(raw, kind=CatalogKind.STATUS)


@pytest.mark.parametrize("raw", ["TRK.open", "trk.open", "TRK.OPEN", " trk.Open "])
def test_reference_addressing_is_case_insensitive(raw: str) -> None:
    """Адресация существующего объекта мягкая: регистр приводится к каноническому.

    Правило сквозное для проекта. Строгий шаблон стоит в схемах создания — придумать
    кривой ключ нельзя, — а вот найти запись по `trk.open` можно и через REST, и через
    MCP одинаково. Иначе один и тот же ввод один интерфейс отвергал бы, а другой
    выполнял: расхождение, которое проект запрещает отдельным правилом.
    """
    assert parse_catalog_ref(raw, kind=CatalogKind.STATUS) == CatalogRef(
        key="open", queue_key="TRK"
    )


def test_reference_survives_a_round_trip() -> None:
    """Сборка и разбор ссылки — обратные операции, иначе адресация разъедется."""
    for queue_key in (None, "TRK"):
        built = build_catalog_ref("open", queue_key=queue_key, kind=CatalogKind.STATUS)
        rendered = format_catalog_ref(built.key, queue_key=built.queue_key)

        assert parse_catalog_ref(rendered, kind=CatalogKind.STATUS) == built


def test_status_categories_are_exactly_three() -> None:
    """Категорий ровно три: на них опираются доски, прогресс проектов и автоматика."""
    assert [category.value for category in StatusCategory] == ["new", "in_progress", "done"]


def test_initial_catalog_keys_are_valid() -> None:
    """Начальный набор обязан проходить те же проверки, что и записи пользователя."""
    for entry in INITIAL_STATUSES:
        assert validate_catalog_key(entry.key, kind=CatalogKind.STATUS) == entry.key
        assert entry.category is not None
    for entry in INITIAL_ISSUE_TYPES:
        assert validate_catalog_key(entry.key, kind=CatalogKind.ISSUE_TYPE) == entry.key
    for entry in INITIAL_RESOLUTIONS:
        assert validate_catalog_key(entry.key, kind=CatalogKind.RESOLUTION) == entry.key


def test_initial_statuses_cover_every_category() -> None:
    """Свежая установка должна давать работающий процесс: начало, работа и конец."""
    categories = {entry.category for entry in INITIAL_STATUSES}

    assert categories == set(StatusCategory)
