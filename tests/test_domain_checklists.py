"""Домен чеклиста без базы: текст пункта и арифметика разреженных позиций.

Позиции — единственное место чеклиста, где есть что ломать. Проверяется не только
«между соседями получается число», но и исчерпание зазора: именно оно превращается в
перенумерацию списка, и молчаливая ошибка здесь дала бы два пункта на одной позиции.
"""

from datetime import UTC, datetime
from itertools import pairwise

import pytest

from app.domain.checklists import (
    MAX_CHECKLIST_ITEMS,
    MAX_CHECKLIST_TEXT_LENGTH,
    POSITION_STEP,
    ensure_capacity,
    next_position,
    position_between,
    rebalanced_positions,
    validate_item_deadline,
    validate_text,
)
from app.domain.errors import InvalidChecklistItemError
from app.domain.fields import SYSTEM_FIELD_KEYS


def test_the_text_is_trimmed_and_kept() -> None:
    assert validate_text("  Прогнать тесты  ") == "Прогнать тесты"


def test_an_empty_item_is_refused() -> None:
    with pytest.raises(InvalidChecklistItemError) as error:
        validate_text("  ")
    assert error.value.details["reason"] == "required"


def test_a_multiline_item_is_refused() -> None:
    """Пункт — одна строка: тому, что не помещается, нужна подзадача с описанием."""
    with pytest.raises(InvalidChecklistItemError) as error:
        validate_text("Прогнать тесты\nи собрать релиз")
    assert error.value.details["reason"] == "multiline_not_allowed"


def test_a_too_long_item_is_refused() -> None:
    with pytest.raises(InvalidChecklistItemError) as error:
        validate_text("a" * (MAX_CHECKLIST_TEXT_LENGTH + 1))
    assert error.value.details["reason"] == "too_long"


def test_a_deadline_without_a_timezone_is_refused_with_the_checklist_code() -> None:
    """Правило то же, что у дедлайна задачи, а код ошибки — свой.

    Клиент, получивший `invalid_issue_deadline` в ответ на правку пункта, искал бы
    проблему в дедлайне самой задачи.
    """
    with pytest.raises(InvalidChecklistItemError) as error:
        validate_item_deadline(datetime(2026, 9, 1, 12, 0))
    assert error.value.code == "invalid_checklist_item"
    assert error.value.details["reason"] == "timezone_required"


def test_a_deadline_with_a_timezone_becomes_utc() -> None:
    aware = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert validate_item_deadline(aware) == aware
    assert validate_item_deadline(None) is None


def test_the_first_item_and_the_next_one_are_a_full_step_apart() -> None:
    """Шаг между соседями — тот запас, за счёт которого перемещение меняет одну строку."""
    first = next_position(None)
    assert first == POSITION_STEP
    assert next_position(first) == 2 * POSITION_STEP


def test_a_position_between_neighbours_splits_the_gap() -> None:
    assert position_between(1024, 2048) == 1536
    assert position_between(None, None) == POSITION_STEP
    assert position_between(2048, None) == 2048 + POSITION_STEP
    assert position_between(None, 1024) == 512


def test_an_exhausted_gap_asks_for_a_rebalance_instead_of_failing() -> None:
    """`None` — сигнал перенумеровать список, а не ошибка.

    Вызывающая сторона обязана его обработать: иначе два пункта получат одну позицию,
    и порядок между ними станет произвольным.
    """
    assert position_between(1024, 1025) is None
    assert position_between(1024, 1024) is None
    # Вставка в самое начало упирается в ноль: отрицательных позиций не бывает.
    assert position_between(None, 1) is None


def test_a_rebalance_restores_the_full_gap_between_neighbours() -> None:
    positions = rebalanced_positions(3)
    assert positions == [POSITION_STEP, 2 * POSITION_STEP, 3 * POSITION_STEP]
    assert all(second - first == POSITION_STEP for first, second in pairwise(positions))


def test_the_capacity_limit_stops_before_the_ceiling_is_crossed() -> None:
    """Потолок нужен потому, что чеклист отдаётся целиком, без пагинации."""
    ensure_capacity(MAX_CHECKLIST_ITEMS - 1)
    with pytest.raises(InvalidChecklistItemError) as error:
        ensure_capacity(MAX_CHECKLIST_ITEMS)
    assert error.value.details["reason"] == "too_many_items"


def test_the_journal_field_name_cannot_be_taken_by_a_custom_field() -> None:
    """`checklist` — имя поля в журнале, поэтому кастомное поле с таким ключом запрещено."""
    assert "checklist" in SYSTEM_FIELD_KEYS
