"""Домен задач без базы: название, описание, дедлайн, теги, имена полей в журнале.

Проверки живут в домене, а не в схемах запросов, потому что тот же сценарий зовут MCP и
автоматика. Поэтому и тесты здесь — без базы и без HTTP.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.errors import (
    InvalidIssueDeadlineError,
    InvalidIssueDescriptionError,
    InvalidIssueSummaryError,
    InvalidIssueTagsError,
)
from app.domain.fields import SYSTEM_FIELD_KEYS
from app.domain.issues import (
    MAX_DESCRIPTION_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    IssueField,
    normalize_tags,
    tags_differ,
    validate_deadline,
    validate_description,
    validate_summary,
)

# --- Имена полей -----------------------------------------------------------------


def test_every_system_field_is_reserved_for_columns() -> None:
    """Имя системного поля в журнале не должно пересекаться с кастомным полем.

    Кастомное поле с ключом `status` завести нельзя (`SYSTEM_FIELD_KEYS`), и благодаря
    этому имя в записи журнала однозначно: либо системное поле, либо ссылка на
    кастомное. Разъехаться двум спискам не даёт этот тест — другого сторожа нет.
    """
    assert {field.value for field in IssueField} <= SYSTEM_FIELD_KEYS


# --- Название и описание ---------------------------------------------------------


def test_summary_is_trimmed() -> None:
    assert validate_summary("  Починить выдачу  ") == "Починить выдачу"


@pytest.mark.parametrize("summary", ["", "   ", "\n"])
def test_empty_summary_is_rejected(summary: str) -> None:
    """Задача без названия нечитаема в любом списке, а придумать его нечем."""
    with pytest.raises(InvalidIssueSummaryError):
        validate_summary(summary)


def test_multiline_summary_is_rejected() -> None:
    # Строка собирается из частей, а не пишется одним литералом: в исходнике `\n`
    # приклеивается к следующему слову, и RUF001 видит смесь латиницы с кириллицей.
    summary = "\n".join(["Первая строка", "вторая строка"])

    with pytest.raises(InvalidIssueSummaryError) as error:
        validate_summary(summary)

    assert error.value.details["reason"] == "multiline_not_allowed"


def test_too_long_summary_is_rejected() -> None:
    with pytest.raises(InvalidIssueSummaryError) as error:
        validate_summary("я" * (MAX_SUMMARY_LENGTH + 1))

    assert error.value.details["max"] == MAX_SUMMARY_LENGTH


def test_empty_description_is_allowed() -> None:
    """Пустая строка — законное «описания нет»; второго способа сказать это нет."""
    assert validate_description("") == ""


def test_too_long_description_is_rejected() -> None:
    with pytest.raises(InvalidIssueDescriptionError):
        validate_description("я" * (MAX_DESCRIPTION_LENGTH + 1))


# --- Дедлайн ---------------------------------------------------------------------


def test_deadline_keeps_an_aware_moment() -> None:
    moment = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    assert validate_deadline(moment) == moment


def test_deadline_is_brought_to_utc() -> None:
    """Иначе ответ на создание отдаёт зону клиента, а чтение из базы — уже UTC.

    Момент при этом один и тот же, но записи разные, и клиент, сравнивающий ответы
    строкой, видит изменение там, где ничего не менялось. Поймала это живая проверка.
    """
    moscow = validate_deadline(datetime(2026, 9, 1, 12, 0, tzinfo=timezone(timedelta(hours=3))))

    assert moscow is not None
    assert moscow.tzinfo is UTC
    assert moscow.isoformat() == "2026-09-01T09:00:00+00:00"


def test_deadline_without_timezone_is_rejected() -> None:
    """Домысливание зоны дало бы сдвиг, который заметят в день напоминания."""
    with pytest.raises(InvalidIssueDeadlineError) as error:
        validate_deadline(datetime(2026, 9, 1, 12, 0))

    assert error.value.details["reason"] == "timezone_required"


def test_missing_deadline_is_allowed() -> None:
    assert validate_deadline(None) is None


# --- Теги ------------------------------------------------------------------------


def test_tags_keep_order_and_case() -> None:
    assert normalize_tags(["Релиз", " backend ", ""]) == ["Релиз", "backend"]


def test_duplicate_tags_are_dropped_case_insensitively() -> None:
    """Первое написание побеждает: иначе результат зависел бы от порядка повторов."""
    assert normalize_tags(["Релиз", "релиз", "РЕЛИЗ"]) == ["Релиз"]


def test_too_long_tag_is_rejected() -> None:
    with pytest.raises(InvalidIssueTagsError) as error:
        normalize_tags(["t" * (MAX_TAG_LENGTH + 1)])

    assert error.value.details["reason"] == "too_long"


def test_too_many_tags_are_rejected() -> None:
    with pytest.raises(InvalidIssueTagsError) as error:
        normalize_tags([f"tag{index}" for index in range(MAX_TAGS + 1)])

    assert error.value.details["reason"] == "too_many"


def test_reordering_tags_counts_as_a_change() -> None:
    """Порядок тегов виден в карточке, поэтому перестановка — тоже изменение."""
    assert tags_differ(["a", "b"], ["b", "a"])
    assert not tags_differ(["a", "b"], ["a", "b"])
