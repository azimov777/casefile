"""Замечания к полям: собрать все сразу и отдать одним списком.

Правило проекта — не останавливаться на первом неверном поле: фронт подсвечивает всю
форму за один ответ, а агент исправляет запрос за одну попытку, а не за пять кругов
«исправил одно — вылезло другое». Механика для этого одна на весь домен: у задачи
(`app/domain/tasks.py`) и у записи дела (`app/domain/case.py`) одинаковые
`details.fields`, и клиент разбирает их одним кодом.

Причины — стабильные строки `snake_case` (`required`, `too_long`, `not_allowed`, ...):
это часть контракта наравне с кодом ошибки, по ним агент понимает, что чинить.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.errors import AppError


class FieldProblem(Exception):
    """Замечание к одному полю. Внутреннее: наружу уезжает списком в `details.fields`.

    Бросается нормализатором значения, который про имя поля не знает — имя добавляет
    накопитель. Так один и тот же нормализатор годится и полю `title` задачи, и полю
    `title` записи дела.
    """

    def __init__(self, reason: str, /, **details: Any) -> None:
        super().__init__(reason)
        # Позиционные `reason` и `field`, а подробности только по имени: иначе
        # `add("addressees", "unknown_participant", name=...)` с подробностью,
        # совпавшей по имени с параметром, падал бы `TypeError` в рантайме.
        self.details: dict[str, Any] = {**details, "reason": reason}


class FieldProblems:
    """Накопитель замечаний: собирает их по всем полям и бросает одну ошибку в конце.

    Пустой накопитель ничего не бросает — вызывающий не обязан проверять это сам.
    """

    __slots__ = ("_problems",)

    def __init__(self) -> None:
        self._problems: list[dict[str, Any]] = []

    @contextmanager
    def field(self, name: str) -> Iterator[None]:
        """Ловит `FieldProblem` из проверки одного поля и приписывает ему имя поля."""
        try:
            yield
        except FieldProblem as problem:
            self._problems.append({**problem.details, "field": name})

    def add(self, field: str, reason: str, /, **details: Any) -> None:
        """Замечание, найденное не нормализатором, а самим сценарием проверки.

        Имя поля и причина — только позиционно: подробность, совпавшая с ними по
        имени (`name`, `field`), иначе роняла бы вызов `TypeError` в рантайме.
        """
        self._problems.append({**details, "field": field, "reason": reason})

    def __bool__(self) -> bool:
        return bool(self._problems)

    def raise_as(self, error: type[AppError], **details: Any) -> None:
        """Бросает ошибку со всеми замечаниями, если они есть.

        Класс ошибки выбирает предметная область: у задачи это `task_fields_invalid`,
        у записи дела — `entry_fields_invalid`. Форма подробностей при этом общая.
        """
        if self._problems:
            raise error(details={**details, "fields": self._problems})
