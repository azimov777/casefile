"""Инструменты MCP, разложенные по областям работы.

Регистрация собрана в одну функцию: список областей — это и есть объём того, что агент
умеет делать с трекером, и держать его в одном месте дешевле, чем искать по модулям.
"""

from mcp.server.mcpserver import MCPServer

from app.mcp.runtime import Runtime
from app.mcp.tools import (
    automation,
    boards,
    discussion,
    issues,
    links,
    notifications,
    projects,
    queues,
    setup,
)

#: Модули инструментов в том порядке, в каком их читает агент: рабочий цикл впереди,
#: настройка процесса в конце. Порядок регистрации задаёт порядок в списке инструментов,
#: а он — первое, что модель видит о сервере.
MODULES = (
    issues,
    discussion,
    links,
    queues,
    projects,
    boards,
    automation,
    notifications,
    setup,
)


def register_all(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует все инструменты трекера на сервере."""
    for module in MODULES:
        module.register(server, runtime)
