"""Инструменты обсуждения: итог и закрытие (решение проекта `TRK#51`, пункты 2 и 7).

Своих инструментов чтения и записи у обсуждения нет, как у области (TRK-555): вопрос и
ответ — `ask` и `answer` по адресу `TRK~7`, заметка и чтение дела — `add_project_entry`
и `read_project_entries` по адресу, привязка задачи — `link` и `unlink` видом
`attached`. Здесь только то, чего у этих инструментов нет: итог из трёх частей и
закрытие с итогом одной транзакцией (решение TRK-671#11).
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.discussions import add_conclusion, close_discussion
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (add_conclusion, close_discussion)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
