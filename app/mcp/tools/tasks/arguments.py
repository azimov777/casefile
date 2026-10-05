"""Аргументы, общие для нескольких инструментов задач: решения проекта у задачи.

Поле `decisions` ставит `create_task` и меняет `update_task` (`CONCEPT.md`, 3.3), и правило
у него одно на оба инструмента: какая ссылка — решение проекта и какой ответит отказ.
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

DecisionsArg = Annotated[
    list[str] | None,
    Field(description=DECISIONS_RULE, examples=[["TRK#15"]]),
]
