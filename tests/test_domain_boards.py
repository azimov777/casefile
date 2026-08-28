"""Домен досок без базы: названия, лимит колонок и виртуальная шкала порядка.

Виртуальная позиция — единственное место домена досок, где есть что ломать молча:
она сравнивается с явными рангами как число одного ряда, и потеря точности здесь
означала бы две карточки на одной позиции с произвольным порядком между ними.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.boards import (
    MAX_BOARD_COLUMNS,
    MAX_COLUMN_STATUSES,
    RANK_SCALE,
    ensure_column_capacity,
    ensure_column_count,
    ensure_column_statuses,
    validate_board_name,
    validate_column_name,
    validate_wip_limit,
    virtual_position,
)
from app.domain.errors import InvalidBoardError
from app.domain.ranking import POSITION_STEP, next_position, position_between


def test_a_board_name_is_a_single_trimmed_line() -> None:
    assert validate_board_name("  Доска команды  ") == "Доска команды"

    with pytest.raises(InvalidBoardError) as error:
        validate_board_name("\n".join(["Доска", "команды"]))

    assert error.value.details["reason"] == "multiline_not_allowed"


def test_an_empty_column_name_is_refused() -> None:
    with pytest.raises(InvalidBoardError) as error:
        validate_column_name("   ")

    assert error.value.details["reason"] == "required"


def test_a_zero_work_in_progress_limit_is_refused() -> None:
    """Ноль — не «запретить колонку», а второй способ сказать «колонки нет»."""
    assert validate_wip_limit(None) is None
    assert validate_wip_limit(3) == 3

    with pytest.raises(InvalidBoardError) as error:
        validate_wip_limit(0)

    assert error.value.details["reason"] == "must_be_positive"


def test_a_column_without_statuses_is_refused() -> None:
    """Пустой набор в фильтре означает «не фильтровать», то есть все задачи доски."""
    with pytest.raises(InvalidBoardError) as error:
        ensure_column_statuses(0)

    assert error.value.details["reason"] == "required"

    with pytest.raises(InvalidBoardError):
        ensure_column_statuses(MAX_COLUMN_STATUSES + 1)


def test_the_column_ceiling_counts_the_result_not_the_attempt() -> None:
    """`ensure_column_capacity` спрашивают до добавления, `ensure_column_count` — после."""
    ensure_column_capacity(MAX_BOARD_COLUMNS - 1)
    ensure_column_count(MAX_BOARD_COLUMNS)

    with pytest.raises(InvalidBoardError):
        ensure_column_capacity(MAX_BOARD_COLUMNS)
    with pytest.raises(InvalidBoardError):
        ensure_column_count(MAX_BOARD_COLUMNS + 1)


# --- Виртуальная шкала порядка -----------------------------------------------------


def test_a_later_issue_gets_a_bigger_virtual_position() -> None:
    """Порядок по времени создания обязан совпадать с порядком по позиции."""
    earlier = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)
    later = earlier + timedelta(microseconds=1)

    assert virtual_position(later) > virtual_position(earlier)


def test_a_microsecond_apart_leaves_room_for_insertions() -> None:
    """Между соседями по времени помещается столько же вставок, сколько между рангами.

    Это и есть смысл множителя шкалы: без него две задачи, созданные подряд, стояли бы
    вплотную, и первое же перетаскивание между ними требовало бы перенумерации доски.
    """
    earlier = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)
    later = earlier + timedelta(microseconds=1)

    assert virtual_position(later) - virtual_position(earlier) == RANK_SCALE
    assert position_between(virtual_position(earlier), virtual_position(later)) is not None


def test_the_same_creation_moment_gives_the_same_position() -> None:
    """Задачи одной транзакции получают одинаковую позицию, и это разбирает перенумерация.

    `now()` — время начала транзакции, одно на все её строки (`docs/notes/db.md`),
    поэтому случай не гипотетический: массовая вставка даёт его всегда. Зазора между
    такими соседями нет, и `position_between` обязана честно сказать об этом `None`, а
    не подставить «что-нибудь рядом».
    """
    moment = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)

    assert virtual_position(moment) == virtual_position(moment)
    assert position_between(virtual_position(moment), virtual_position(moment)) is None


def test_the_virtual_scale_fits_into_bigint() -> None:
    """Запас проверен: `bigint` вмещает шкалу далеко за пределами срока жизни системы."""
    assert virtual_position(datetime(2200, 1, 1, tzinfo=UTC)) < 2**63 - 1


def test_a_position_is_computed_the_same_way_from_any_timezone() -> None:
    """Один и тот же момент в разных зонах — одна позиция: шкала считается от эпохи."""
    utc = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)
    shifted = utc.astimezone(timezone(timedelta(hours=3)))

    assert virtual_position(shifted) == virtual_position(utc)


def test_the_end_of_the_list_is_always_reachable() -> None:
    """«В конец» — это позиция за последней, и она есть всегда.

    Ради этого свойства шкала и совмещена: при сортировке «ранжированные, потом
    остальные» поставить карточку в самый конец было бы нельзя.
    """
    last = virtual_position(datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC))

    assert next_position(last) == last + POSITION_STEP
    assert position_between(last, None) == last + POSITION_STEP
