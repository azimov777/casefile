"""Домен проектов и портфелей: ключи, период, прогресс. Без базы.

Здесь проверяются правила, которые обязаны быть одинаковыми у REST, MCP и автоматики.
Главное из них — формула прогресса портфеля: она принята решением, а не выведена, и без
теста на конкретных числах её однажды «поправят» на среднее от детей.
"""

from datetime import date

import pytest

from app.domain.errors import (
    InvalidPortfolioError,
    InvalidPortfolioKeyError,
    InvalidProjectError,
    InvalidProjectKeyError,
)
from app.domain.projects import (
    MAX_PLANNING_NAME_LENGTH,
    PlanningKind,
    Progress,
    aggregate,
    normalize_planning_key,
    validate_period,
    validate_planning_description,
    validate_planning_key,
    validate_planning_name,
)

# --- Ключи --------------------------------------------------------------------------


def test_a_key_is_normalised_to_lower_case() -> None:
    """Адресация мягкая: `/projects/Alpha` обязан находить `alpha`."""
    assert normalize_planning_key("  Alpha  ") == "alpha"
    assert (
        validate_planning_key("ALPHA", kind=PlanningKind.PROJECT, error=InvalidProjectKeyError)
        == "alpha"
    )


@pytest.mark.parametrize("key", ["", "a", "1alpha", "alpha-two", "alpha.two", "альфа", "a" * 65])
def test_a_key_outside_the_pattern_is_refused_with_the_pattern(key: str) -> None:
    """В `details` уходит шаблон: агент исправляет запрос, не читая исходники."""
    with pytest.raises(InvalidProjectKeyError) as error:
        validate_planning_key(key, kind=PlanningKind.PROJECT, error=InvalidProjectKeyError)

    assert error.value.details["reason"] == "pattern_mismatch"
    assert "pattern" in error.value.details


def test_the_key_error_class_comes_from_the_caller() -> None:
    """Коды `invalid_project_key` и `invalid_portfolio_key` не склеиваются в один.

    Правило проверки общее, а код — часть контракта: клиент по нему решает, что
    показать, и одна ошибка на две сущности заставила бы его разбирать `details`.
    """
    with pytest.raises(InvalidPortfolioKeyError):
        validate_planning_key("", kind=PlanningKind.PORTFOLIO, error=InvalidPortfolioKeyError)


# --- Название и описание -------------------------------------------------------------


def test_an_empty_name_is_refused_rather_than_replaced() -> None:
    """Придумать название за пользователя нечем, а безымянный проект нечитаем в списке."""
    with pytest.raises(InvalidProjectError) as error:
        validate_planning_name("   ", kind=PlanningKind.PROJECT)

    assert error.value.details["reason"] == "required"


def test_a_multiline_name_is_refused() -> None:
    """Название живёт в списках и на карточках портфеля: перевод строки ломает вёрстку."""
    with pytest.raises(InvalidPortfolioError):
        validate_planning_name("Платформа\nдоставки", kind=PlanningKind.PORTFOLIO)  # noqa: RUF001


def test_a_too_long_name_names_the_limit() -> None:
    with pytest.raises(InvalidProjectError) as error:
        validate_planning_name("x" * (MAX_PLANNING_NAME_LENGTH + 1), kind=PlanningKind.PROJECT)

    assert error.value.details["max"] == MAX_PLANNING_NAME_LENGTH


def test_an_empty_description_is_a_legal_value() -> None:
    """Пустая строка означает «описания нет» — второго способа сказать это нет."""
    assert validate_planning_description("  ", kind=PlanningKind.PROJECT) == ""


# --- Период --------------------------------------------------------------------------


def test_a_period_may_be_open_on_either_side() -> None:
    """Проект без сроков — обычное состояние планирования, а не недооформленность."""
    validate_period(None, None, kind=PlanningKind.PROJECT)
    validate_period(date(2026, 1, 1), None, kind=PlanningKind.PROJECT)
    validate_period(None, date(2026, 1, 1), kind=PlanningKind.PROJECT)


def test_a_one_day_period_is_allowed() -> None:
    """Совпадение дат — законный план, а не ошибка ввода."""
    validate_period(date(2026, 1, 1), date(2026, 1, 1), kind=PlanningKind.PROJECT)


def test_an_inverted_period_is_refused_with_both_dates() -> None:
    """Обе даты уходят в `details`: клиент видит, какую из них исправлять."""
    with pytest.raises(InvalidProjectError) as error:
        validate_period(date(2026, 3, 1), date(2026, 1, 1), kind=PlanningKind.PROJECT)

    assert error.value.details["reason"] == "before_start"
    assert error.value.details["start_date"] == "2026-03-01"
    assert error.value.details["end_date"] == "2026-01-01"


# --- Прогресс ------------------------------------------------------------------------


def test_a_project_without_issues_has_no_ratio_rather_than_zero() -> None:
    """«Нечего считать» и «сделано 0%» — разные вещи, и выглядеть одинаково не должны."""
    empty = Progress()

    assert empty.total == 0
    assert empty.ratio is None


def test_the_ratio_is_the_share_of_done_issues() -> None:
    assert Progress(total=4, done=1).ratio == 0.25
    assert Progress(total=4, done=4).ratio == 1.0


@pytest.mark.parametrize("counters", [(-1, 0), (1, -1), (1, 2)])
def test_impossible_counters_fail_loudly(counters: tuple[int, int]) -> None:
    """Закрытых больше, чем всего, — это сломанный запрос, а не редкое состояние.

    Тихо принять такое значило бы отдать клиенту прогресс больше единицы и заставить
    искать причину в интерфейсе.
    """
    total, done = counters
    with pytest.raises(ValueError):
        Progress(total=total, done=done)


def test_a_portfolio_sums_issues_rather_than_averaging_children() -> None:
    """Проект на 900 задач и проект на 100: 55%, а не 75%.

    Ровно тот пример, на котором принималось решение. Среднее от детей отвечало бы на
    другой вопрос — «какая доля инициатив готова», — и закрытый мелкий проект двигал бы
    число портфеля как крупный. Тест стережёт формулу от «упрощения».
    """
    core = Progress(total=900, done=450)
    storefront = Progress(total=100, done=100)

    total = aggregate([core, storefront])

    assert (total.total, total.done) == (1000, 550)
    assert total.ratio == 0.55


def test_an_empty_project_does_not_drag_the_portfolio_down() -> None:
    """У суммы пустой проект добавляет ноль к обоим счётчикам; у среднего — тянул бы вниз."""
    assert aggregate([Progress(total=4, done=2), Progress()]).ratio == 0.5


def test_a_portfolio_without_any_issues_has_no_ratio() -> None:
    assert aggregate([]).ratio is None
    assert aggregate([Progress(), Progress()]).ratio is None
