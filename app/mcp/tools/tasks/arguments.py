"""Аргументы, общие для нескольких инструментов задач: решения, направление и момент.

Поля `decisions`, `direction` и `not_before` ставит `create_task` и меняет `update_task`
(`CONCEPT.md`, 3.3; решение проекта `TRK#47`), и правило у каждого одно на оба инструмента:
какое значение принимается и какой ответит отказ.
"""

from typing import Annotated

from pydantic import Field

from app.domain.tasks import MAX_DECISIONS

#: Что такое ссылка на решение и чем трекер её отклонит. Отказ `task_entry` назван прямо:
#: это та ссылка, которой практику одной задачи выдают за решение проекта (`CONCEPT.md`,
#: 3.2, «Слухи»).
DECISIONS_RULE = (
    "References `PROJECT#N` to `decision` entries of a project's case, up to "
    f"{MAX_DECISIONS}: the project decisions the task relies on. A task entry such as "
    "`TRK-42#7` is refused with `task_fields_invalid` (`task_entry`), a project entry of "
    "another type with `not_a_decision`. A reference not yet in the field leads to a "
    "decision in force; a superseded one is refused with `decision_not_in_force`, its "
    "successor in `details`"
)

#: Направление задачи (`CONCEPT.md`, 3.3, 3.7): адрес направления её проекта. Ставит
#: `create_task`, меняет `update_task`; формулировка короткая намеренно — метадата
#: инструментов держится в бюджете токенов (`docs/notes/mcp.md`).
DIRECTION_RULE = "Direction address `PROJECT/key`"

DirectionArg = Annotated[str | None, Field(description=DIRECTION_RULE)]

#: Момент «не раньше» (решение проекта `TRK#47`): поле, признак и отказ входа названы в
#: одном месте, потому что агент ставит момент там же, где узнаёт, что он держит. Примера
#: значения в схеме нет: примеры метадаты — только форматы ключей (`tests/test_mcp_metadata.py`).
NOT_BEFORE_RULE = (
    "Moment before which the task cannot enter `in_progress`: ISO 8601 date and time with "
    "a UTC offset, by the clock of the device of whoever sets it. A time without an offset "
    "or a date without a time is refused with `task_fields_invalid`. Until the database "
    "clock reaches the moment the `deferred` feature is true and entry into `in_progress` "
    "is refused with `task_deferred`; the moment arrives with no entry, no status change "
    "and no wake-up"
)

NotBeforeArg = Annotated[str | None, Field(description=NOT_BEFORE_RULE)]

DecisionsArg = Annotated[
    list[str] | None,
    Field(description=DECISIONS_RULE, examples=[["TRK#15"]]),
]
