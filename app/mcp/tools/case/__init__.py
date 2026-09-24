"""Инструменты по делу: прочитать записи и подшить свою.

Один инструмент — один вид записи. Составного «подшить и перевести» здесь нет: у
составного вызова отказ второй половины оставляет первую применённой, а агент видит одну
ошибку и не знает, что именно случилось.

Исключение ровно одно, и оно не отсюда: закрытие задачи (`app/mcp/tools/tasks/close_task.py`,
`close_task`) подшивает вердикты, записи и сводку и переводит задачу в `done` одной
транзакцией. Довод выше его не запрещает, а объясняет: там половин не бывает — отказ
любой части не оставляет ни одной записи, и ошибка приходит одна, потому что действие
одно.

Каждый инструмент зовёт **свою обёртку** сценария (`app/services/case.py`,
`add_summary`, `ask`, `answer`, `add_verdict`, `add_entry`), а не собирает нагрузку сам:
форма нагрузки — знание домена, и второй его копией в слое MCP она разошлась бы с
первой на первой же правке.

Модуль на инструмент. Поля записи, общие для нескольких инструментов, — `arguments.py`,
формы записи — `views.py`; их же берут `get_task`, `close_task` и `wait_journal`.
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.case import (
    add_entry,
    add_summary,
    add_verdict,
    answer,
    ask,
    read_entries,
    resolve,
)
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (
    read_entries,
    add_summary,
    add_entry,
    ask,
    answer,
    resolve,
    add_verdict,
)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
