"""Инструмент ленты: хвост журнала с долгим ожиданием.

Отдельной таблицы событий в трекере нет: журнал всех записей дела и есть лента
(`CONCEPT.md`, 4.1). Фильтр здесь не собирается вручную — ключи задач и очереди
разрешает `journal.resolve_filter`, тот же, что и в REST: опечатка в ключе иначе дала бы
пустую ленту, неотличимую от «ничего не происходит», и ждущий висел бы до таймаута, считая
установку спящей. Там же разбирается и форма `task`: один ключ или список.

Потолки ожидания (`MAX_WAIT_SECONDS`) и числа задач (`MAX_TASK_KEYS`) проверяет домен и
отвечает `journal_wait_too_long` и `journal_too_many_tasks` с числом в подробностях.
Своей ветки условий инструмент не заводит по той же причине, что и `search_tasks`.

Записи ленты — те же формы, что у дела (`app/mcp/tools/case/views.py`), тип-фильтр —
тот же аргумент (`app/mcp/tools/case/arguments.py`).
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.journal import wait_journal
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (wait_journal,)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
