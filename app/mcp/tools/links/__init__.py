"""Инструменты по связям: поставить и снять.

Обе задачи разрешаются здесь, а не в сценарии: модуль связей намеренно не импортирует
сценарии задач, иначе зависимость стала бы кольцевой (`app/services/links.py`). Ровно то
же самое делает роутер REST — и это не дублирование логики, а разрешение адреса, которое
у каждого интерфейса своё.

Чтения связей отдельным инструментом нет: они приезжают в пакете преемника `get_task`
вместе со статусом задачи на другой стороне. Отдельный инструмент означал бы второй вызов
ради того, что агент получает первым.

Модуль на инструмент; аргументы и ответ, общие для обоих, — `arguments.py` и `views.py`.
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.links import link, unlink
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (
    link,
    unlink,
)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
