"""Инструменты по реестрам: проекты и участники.

Чтение открыто набору `task` — оно часть рабочего цикла: без списка проектов агент с
чистым контекстом не найдёт, где вообще лежат задачи, без описания проекта не знает
общего контекста его задач, без реестра участников ему некому адресовать вопрос.
Запись требует набора `main`: заводить проекты и регистрировать участников — управление
установкой, а не работа над задачей. Исключение — атрибуты проекта (`set_attribute`,
`remove_attribute`): их ведёт рабочий цикл агента, набор `task` (`CONCEPT.md`, 3.2).

Выпуска токенов здесь нет и не будет: выдача доступов остаётся за человеком и идёт
только через REST (`CONCEPT.md`, 5.2).

Модуль на инструмент; общее для нескольких — `arguments.py` и `views.py`.
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.registries import (
    create_project,
    get_project,
    list_participants,
    list_projects,
    register_participant,
    remove_attribute,
    set_attribute,
    update_participant,
    update_project,
)
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (
    get_project,
    list_projects,
    list_participants,
    create_project,
    update_project,
    set_attribute,
    remove_attribute,
    register_participant,
    update_participant,
)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
