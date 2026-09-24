"""Инструменты по реестрам: очереди и участники.

Чтение открыто набору `task` — оно часть рабочего цикла: без списка очередей агент с
чистым контекстом не найдёт, где вообще лежат задачи, без описания очереди не знает
общего контекста её задач, без реестра участников ему некому адресовать вопрос.
Запись требует набора `main`: заводить очереди и регистрировать участников — управление
установкой, а не работа над задачей.

Выпуска токенов здесь нет и не будет: выдача доступов остаётся за человеком и идёт
только через REST (`CONCEPT.md`, 5.2).

Модуль на инструмент; общее для нескольких — `arguments.py` и `views.py`.
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.registries import (
    create_queue,
    get_queue,
    list_participants,
    list_queues,
    register_participant,
    update_participant,
    update_queue,
)
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (
    get_queue,
    list_queues,
    list_participants,
    create_queue,
    update_queue,
    register_participant,
    update_participant,
)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
