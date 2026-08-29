"""Перевод доменной ошибки в ошибку инструмента MCP.

Одна функция на весь слой. Агент не видит ни кода ответа, ни заголовков — всё, что у
него есть, это текст: по нему он либо исправляет вызов с первой попытки, либо уходит в
слепой перебор. Поэтому в текст уезжает всё, что знает ошибка: стабильный код, фраза и
**целиком** подробности.

Подробности особенно важны там, где они называют место ошибки: разбор запроса кладёт в
`details` позицию символа и причину, валидатор значений — список полей с допустимыми
значениями. Урезать их до «invalid query» значило бы отобрать у агента единственный
способ понять, что именно не так.
"""

import json
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from app.core.errors import AppError


def tool_error(exc: AppError) -> ToolError:
    """Доменная ошибка → `ToolError` с кодом, сообщением и подробностями."""
    return ToolError(describe(exc))


def resource_error(exc: AppError) -> ResourceError:
    """Доменная ошибка → `ResourceError`.

    Отдельно от `tool_error`, потому что SDK различает семейства: исключение чужого
    типа, вылетевшее из ресурса, считается крахом обработчика, и клиент получает
    безличное сообщение вместо причины отказа.
    """
    return ResourceError(describe(exc))


def describe(exc: AppError) -> str:
    """Текст ошибки для агента: `code: message` и строка подробностей под ним."""
    text = f"{exc.code}: {exc.message}"
    if not exc.details:
        return text
    return f"{text}\ndetails: {_json(exc.details)}"


def _json(details: dict[str, Any]) -> str:
    """Подробности одной строкой. `default=str` — страховка от значений вроде UUID."""
    return json.dumps(details, ensure_ascii=False, sort_keys=True, default=str)
