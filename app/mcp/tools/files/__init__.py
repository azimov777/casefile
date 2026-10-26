"""Инструменты файлов: ссылки на загрузку и замену, выдача, список, удаление.

Файл — строка установки, у него один проект (`TRK/files#3`); прикладывает файл к записи
аргумент `files` инструментов дела. Байты ни в одну сторону не идут через инструмент
(TRK~8#11): `request_file_upload` и `request_file_replace` выдают одноразовую ссылку для
`curl -T`, `read_file` отдаёт изображение содержимым `image`, а документ — карточкой и
ссылкой для `curl -o` (`app/mcp/file_links.py`). Реестр группы — `TOOLS` в `__init__.py`: он
же задаёт порядок в `tools/list`.
"""

from collections.abc import Sequence
from types import ModuleType

from app.mcp.tools.files import (
    delete_file,
    list_files,
    read_file,
    request_file_replace,
    request_file_upload,
)
from app.mcp.toolset import Toolset

#: Инструменты группы: модуль на инструмент, в порядке `tools/list`.
TOOLS: Sequence[ModuleType] = (
    request_file_upload,
    request_file_replace,
    read_file,
    list_files,
    delete_file,
)


def register(tools: Toolset) -> None:
    """Объявляет инструменты группы по порядку `TOOLS`."""
    for tool in TOOLS:
        tool.register(tools)
