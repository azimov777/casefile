"""Раскладка инструментов MCP: группа → файл инструмента (TRK-149).

Человек читает сервер сверху вниз: реестр групп `REGISTRARS`, реестр группы `TOOLS`, файл
инструмента. Тест держит, что эта дорога ведёт туда, куда обещает: каждый инструмент из
`tools/list` лежит в `app/mcp/tools/<группа>/<имя>.py`, реестр группы называет этот модуль,
модуль объявляет ровно свой инструмент, а порядок реестров и есть порядок `tools/list`.
"""

import sys
from pathlib import Path
from types import ModuleType

from mcp.server.mcpserver import MCPServer

from app.core.config import get_settings
from app.mcp import tools as tools_package
from app.mcp.runtime import Runtime
from app.mcp.tools import REGISTRARS
from app.mcp.toolset import Toolset

TOOLS_ROOT = Path(tools_package.__file__).parent

#: Файлы группы, которые не инструменты: реестр и общее для нескольких её инструментов.
GROUP_SHARED_FILES = {"__init__.py", "arguments.py", "views.py"}


def _groups() -> list[ModuleType]:
    """Пакеты групп в порядке `REGISTRARS`."""
    return [sys.modules[registrar.__module__] for registrar in REGISTRARS]


def _declared(module: ModuleType) -> list[str]:
    """Имена инструментов, которые объявляет модуль, — на отдельном пустом сервере."""
    probe = Toolset(server=MCPServer(name="probe"), runtime=Runtime(), settings=get_settings())
    module.register(probe)
    return list(probe.scopes)


def test_every_tool_module_declares_exactly_the_tool_it_is_named_after() -> None:
    """`app/mcp/tools/<группа>/<имя>.py` объявляет инструмент `<имя>` и ничего больше."""
    for group in _groups():
        group_dir = TOOLS_ROOT / group.__name__.rsplit(".", 1)[1]
        for module in group.TOOLS:
            name = module.__name__.rsplit(".", 1)[1]
            assert Path(module.__file__) == group_dir / f"{name}.py"
            assert _declared(module) == [name], module.__name__


def test_every_tool_file_of_a_group_is_named_by_its_registry() -> None:
    """Файл инструмента, забытый в `TOOLS`, не подключится молча: тест назовёт его."""
    for group in _groups():
        group_dir = Path(group.__file__).parent
        listed = {f"{module.__name__.rsplit('.', 1)[1]}.py" for module in group.TOOLS}
        on_disk = {path.name for path in group_dir.glob("*.py")} - GROUP_SHARED_FILES
        assert on_disk == listed, group.__name__


async def test_the_registries_give_the_order_of_tools_list(mcp_server: MCPServer) -> None:
    """Реестры групп, прочитанные подряд, — это `tools/list` без фильтра по набору токена."""
    from_registries = [
        name for group in _groups() for module in group.TOOLS for name in _declared(module)
    ]
    listed = [tool.name for tool in await mcp_server.list_tools()]

    assert from_registries == listed
