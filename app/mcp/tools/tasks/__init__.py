"""Инструменты по задачам: прочитать, найти, завести, поправить, перевести, закрыть, перенести.

Тонкий слой: каждый инструмент разбирает аргументы, зовёт сценарий и превращает
результат в данные. Своей логики здесь нет и быть не может — иначе агент и человек
получили бы две разные системы поверх одной базы.

Модуль на инструмент; формы ответа, общие для нескольких из них, — `views.py`.
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.tasks import (
    close_task,
    create_task,
    get_task,
    move_task,
    search_tasks,
    transition,
    update_task,
)
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (
    get_task,
    search_tasks,
    create_task,
    update_task,
    transition,
    close_task,
    move_task,
)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
