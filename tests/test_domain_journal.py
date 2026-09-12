"""Домен ленты без базы: потолок ожидания, курсор потока, слияние двух позиций.

Проверки здесь дублируют то, что в REST делает схема параметра (`le=`, `ge=`), и это не
лишняя работа: тот же вход приезжает в MCP мимо FastAPI, и правило обязано срабатывать
одинаково с обеих сторон. Расхождение интерфейсов на одном входе проект запрещает
отдельным правилом.
"""

import pytest

from app.domain.errors import (
    InvalidJournalCursorError,
    JournalTooManyTasksError,
    JournalWaitTooLongError,
)
from app.domain.journal import (
    DEFAULT_WAIT_SECONDS,
    JOURNAL_START,
    MAX_TASK_KEYS,
    MAX_WAIT_SECONDS,
    parse_last_event_id,
    resolve_after,
    resolve_task_keys,
    resolve_wait,
)

# --- Ключи задач фильтра --------------------------------------------------------------


def test_no_tasks_named_means_the_whole_journal() -> None:
    assert resolve_task_keys(None) == ()
    assert resolve_task_keys([]) == ()


def test_one_key_as_a_string_still_narrows_the_tail() -> None:
    """Прежняя форма вызова обязана работать без изменений: `task="TRK-42"`."""
    assert resolve_task_keys("TRK-42") == ("TRK-42",)


def test_several_keys_come_as_a_list_or_through_commas() -> None:
    """Две формы списка — та же пара, что у остальных списочных параметров API.

    Повтор параметра пишет сгенерированный клиент, перечисление через запятую — человек
    и агент, набирающие адрес руками.
    """
    assert resolve_task_keys(["TRK-1", "TRK-2"]) == ("TRK-1", "TRK-2")
    assert resolve_task_keys(["TRK-1,TRK-2"]) == ("TRK-1", "TRK-2")
    assert resolve_task_keys("TRK-1, TRK-2") == ("TRK-1", "TRK-2")


def test_a_key_named_twice_is_resolved_once() -> None:
    """Повтор ключа стоил бы второго разрешения в задачу и ничего бы не добавил."""
    assert resolve_task_keys(["TRK-1", "trk-1", "TRK-2"]) == ("TRK-1", "TRK-2")


def test_more_keys_than_the_ceiling_are_refused_with_both_numbers() -> None:
    """Отказ, а не усечение: выдача без части спрошенных дел читалась бы как ответ.

    Ждущий, назвавший больше потолка и получивший записи по части дел, счёл бы тишину
    по остальным за «там ничего не происходит». С обоими числами в подробностях он
    строит свой цикл из нескольких ожиданий.
    """
    keys = [f"TRK-{number}" for number in range(MAX_TASK_KEYS + 1)]

    with pytest.raises(JournalTooManyTasksError) as failure:
        resolve_task_keys(keys)

    assert failure.value.details["max"] == MAX_TASK_KEYS
    assert failure.value.details["tasks"] == MAX_TASK_KEYS + 1


def test_exactly_the_ceiling_passes() -> None:
    keys = [f"TRK-{number}" for number in range(MAX_TASK_KEYS)]

    assert len(resolve_task_keys(keys)) == MAX_TASK_KEYS


# --- Потолок ожидания ---------------------------------------------------------------


def test_wait_defaults_to_not_waiting() -> None:
    """Не передали ожидание — читаем хвост и отвечаем сразу."""
    assert resolve_wait(None) == DEFAULT_WAIT_SECONDS == 0


@pytest.mark.parametrize("seconds", [0, 0.5, 30, MAX_WAIT_SECONDS])
def test_wait_within_the_ceiling_passes_through(seconds: float) -> None:
    assert resolve_wait(seconds) == float(seconds)


def test_wait_above_the_ceiling_is_refused_with_the_ceiling_in_details() -> None:
    """Отказ, а не срезание до потолка.

    Срезание выглядит безобиднее и врёт: попросивший десять минут и получивший минуту
    истолковал бы пустой ответ как «за десять минут ничего не произошло». Потолок в
    подробностях позволяет клиенту сразу собрать свой цикл из нескольких ожиданий.
    """
    with pytest.raises(JournalWaitTooLongError) as failure:
        resolve_wait(600)

    assert failure.value.details["max"] == MAX_WAIT_SECONDS
    assert failure.value.details["wait"] == 600


def test_negative_wait_is_refused_rather_than_treated_as_zero() -> None:
    """Молча исправленный запрос скрывает ошибку в клиенте."""
    with pytest.raises(JournalWaitTooLongError):
        resolve_wait(-1)


# --- Курсор потока ------------------------------------------------------------------


def test_no_last_event_id_means_no_position() -> None:
    """Пустой заголовок — это «начни с конца», а не нулевая позиция."""
    assert parse_last_event_id(None) is None
    assert parse_last_event_id("") is None
    assert parse_last_event_id("   ") is None


def test_last_event_id_is_a_sequence_number() -> None:
    assert parse_last_event_id("17") == 17
    assert parse_last_event_id(" 17 ") == 17


def test_an_unknown_sequence_number_is_a_valid_position() -> None:
    """Записи постоянны, поэтому «слишком старого» курсора у ленты не бывает.

    Проверка на существование номера здесь была бы вредна: она заставила бы клиента,
    отставшего на неделю, начинать с конца, хотя догнать он может с любого номера.
    """
    assert parse_last_event_id("999999") == 999999


@pytest.mark.parametrize("raw", ["abc", "17.5", "1e3", "-1"])
def test_a_malformed_last_event_id_is_refused(raw: str) -> None:
    """Молчаливый старт с конца заставил бы клиента считать, что за обрыв ничего не было."""
    with pytest.raises(InvalidJournalCursorError):
        parse_last_event_id(raw)


# --- Две позиции --------------------------------------------------------------------


def test_the_position_defaults_to_the_beginning_of_the_journal() -> None:
    assert resolve_after(None, None) == JOURNAL_START == 0


def test_the_larger_of_the_two_positions_wins() -> None:
    """`after` задаёт клиент, `cursor` продолжает страницу; действуют оба сразу.

    Больший означает «уже прочитано дальше», и откатывать чтение назад молча нельзя:
    страница пришла бы не та, о которой клиент думает.
    """
    assert resolve_after(10, 20) == 20
    assert resolve_after(20, 10) == 20
    assert resolve_after(None, 20) == 20
    assert resolve_after(20, None) == 20
