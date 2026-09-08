"""Регистрация инструментов и фильтр `tools/list` по набору токена.

Право в трекере одно — набор токена (`CONCEPT.md`, 3.1). Здесь оно превращается в два
разных, но согласованных поведения:

1. **Состав `tools/list`.** Клиент видит только те инструменты, которые открывает его
   токен. Не ради безопасности — отказ всё равно случится при вызове, — а ради контекста
   модели: четыре недоступных инструмента в списке это четыре описания, прочитанных зря,
   и четыре повода попробовать то, что не получится.
2. **Отказ на вызове.** Он приходит **не отсюда**, а из той же единой точки прав, что и в
   REST (`app/services/permissions.py`): сценарий, которому нужен `main`, отвечает
   `permission_denied` независимо от того, каким интерфейсом его позвали. Второй проверки
   набора в слое MCP нет намеренно — она была бы вторым местом, где живёт правда о правах.

Отсюда и роль объявленного здесь набора: он описывает **список**, а не решает, можно ли.
Разойтись с настоящими правами ему не даёт тест, который зовёт каждый инструмент набора
`main` токеном `task` и ждёт `permission_denied`.

## Почему фильтр — промежуточный слой, а не свой обработчик

`MCPServer.list_tools()` — метод без контекста запроса: токена в нём нет и взяться ему
неоткуда. Промежуточный слой видит и метод сообщения (`ctx.method`), и его заголовки,
поэтому фильтр стоит именно там: он пропускает всё, кроме `tools/list`, а у него правит
результат.

## Почему запрет лишнего аргумента стоит на модели, а не в промежуточном слое

Прислать инструменту то, чего в его подписи нет, — ошибка того же рода, что и лишнее
поле в теле REST, и отвечать на неё трекер обязан так же: отказом с именем присланного
(`TRK-22`). Слой для этого не годится, и это проверено: он сидит **выше** диспетчера
инструментов, и `ToolError`, брошенный оттуда, доезжает до клиента протокольной ошибкой
JSON-RPC, а не результатом `is_error` с текстом. Все прочие отказы трекера приходят
агенту текстом в результате, и заводить второй способ отказывать ради одного класса
ошибок значило бы разделить их на два по признаку, о котором агент не знает.

Отказ поэтому приходит оттуда же, откуда приходит любой отказ по схеме, — из разбора
аргументов. Запрет объявлен один раз, на базовой модели, от которой SDK производит
модель аргументов **каждого** инструмента (`create_model(__base__=ArgModelBase)`).
Отсюда три следствия разом: схема в `tools/list` честно объявляет
`additionalProperties: false`, разбор отвечает `extra_forbidden` с именем аргумента, и
новый инструмент получает то и другое сам, не поминая запрет в своей подписи.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp.shared.exceptions import MCPError
from mcp_types import INTERNAL_ERROR, INVALID_REQUEST, ListToolsResult

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.idempotency import IDEMPOTENCY_KEY_ARGUMENT
from app.domain.tokens import TokenScope
from app.mcp.errors import describe
from app.mcp.runtime import Runtime

#: Метод, состав ответа которого зависит от набора токена.
LIST_TOOLS = "tools/list"

# Лишний аргумент инструмента — отказ, а не тихо отброшенное значение.
#
# Умолчание pydantic — `extra="ignore"`, и SDK его не меняет: `ArgModelBase` объявляет
# только `arbitrary_types_allowed`. С ним вызов `create_task` с `goal` верхним уровнем
# вместо вложенного `sections` отвечал успехом и заводил задачу с пустыми разделами
# (`TRK-22`). Это худший вид сбоя: агент получает успех и уверен, что прислал понятое.
#
# Строка стоит на базовой модели, а не в декораторе `Toolset.tool` ниже, потому что
# схему аргументов SDK строит один раз, при регистрации, и правка конфига после неё
# требовала бы ещё и пересчёта уже сохранённой схемы. Здесь она действует раньше:
# `create_model(__base__=ArgModelBase)` читает конфиг базы в момент создания модели.
#
# Импорт `ArgModelBase` — намеренная опора на устройство SDK. Ломается она громко:
# переименование класса даёт `ImportError` при старте, а не молчаливо снятый запрет.
ArgModelBase.model_config = {**ArgModelBase.model_config, "extra": "forbid"}


@dataclass(slots=True)
class Toolset:
    """Сервер, контекст вызова и то, какой набор открывает каждый инструмент.

    Передаётся модулям инструментов вместо самого сервера: регистрация без объявленного
    набора невозможна, потому что декоратор здесь только один.
    """

    server: MCPServer
    runtime: Runtime
    settings: Settings
    scopes: dict[str, TokenScope] = field(default_factory=dict)

    def tool(
        self,
        *,
        scope: TokenScope = TokenScope.TASK,
        creating: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Объявляет инструмент: имя берётся из функции, описание — из её докстроки.

        `creating` означает «вызов заводит объект»: концепция требует, чтобы такой вызов
        принимал ключ идемпотентности (`CONCEPT.md`, 4.5). Наличие аргумента проверяется
        здесь, при сборке, а не тестом на каждый инструмент: забытый ключ иначе
        обнаружился бы у агента, который повторил упавший вызов и завёл второй объект.
        """

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            name = function.__name__
            if creating and IDEMPOTENCY_KEY_ARGUMENT not in inspect.signature(function).parameters:
                raise TypeError(
                    f"Creating tool {name!r} must accept a {IDEMPOTENCY_KEY_ARGUMENT!r} "
                    "argument: a repeated call has to answer with the first result "
                    "instead of creating a second object"
                )
            self.scopes[name] = scope
            self.server.tool(name=name)(function)
            return function

        return register

    def allowed(self, scope: TokenScope) -> set[str]:
        """Имена инструментов, которые открывает этот набор."""
        return {name for name, required in self.scopes.items() if scope.allows(required)}

    def middleware(self) -> Callable[..., Any]:
        """Промежуточный слой, оставляющий в `tools/list` инструменты набора токена."""

        async def filter_tools(
            ctx: ServerRequestContext[Any, Any],
            call_next: Callable[[ServerRequestContext[Any, Any]], Any],
        ) -> Any:
            if ctx.method != LIST_TOOLS:
                return await call_next(ctx)
            # Токен разбирается **до** сборки списка: неизвестный токен обязан получить
            # отказ, а не пустой список, неотличимый от сервера без инструментов.
            scope = await self._scope()
            return _keep(await call_next(ctx), self.allowed(scope))

        return filter_tools

    async def _scope(self) -> TokenScope:
        """Набор токена текущего сообщения.

        Отказ переводится в ошибку **протокола**, а не в ошибку инструмента: `tools/list`
        не инструмент, и `ToolError` отсюда клиент прочитал бы как сбой обработчика без
        причины. Причина при этом та же, что у любого отказа трекера, — код и подробности.
        """
        try:
            async with self.runtime.session() as (_, actor):
                return actor.scope
        except AppError as exc:
            raise MCPError(code=INVALID_REQUEST, message=describe(exc)) from exc


def _keep(result: Any, allowed: set[str]) -> Any:
    """Оставляет в ответе `tools/list` только разрешённые инструменты.

    Форм ответа две, и это не перестраховка. Объявленный тип обработчика —
    `ListToolsResult`, но до промежуточного слоя ответ доезжает уже свёрнутым в словарь
    (`{"tools": [{"name": ..., ...}]}`) — так его отдаёт диспетчер SDK 2.1. Обе формы
    обрабатываются явно, потому что версия SDK может вернуть любую из них.

    Незнакомая форма — отказ, а не ответ как есть. Пропустить её значило бы отдать
    полный список инструментов токену, который их не открывает, и заметить это по одному
    молчаливо лишнему полю в ответе никто бы не смог.
    """
    if isinstance(result, ListToolsResult):
        return result.model_copy(
            update={"tools": [tool for tool in result.tools if tool.name in allowed]}
        )
    if isinstance(result, Mapping) and "tools" in result:
        return {
            **result,
            "tools": [tool for tool in result["tools"] if tool.get("name") in allowed],
        }
    raise MCPError(
        code=INTERNAL_ERROR,
        message=(
            f"Cannot filter {LIST_TOOLS} by token scope: the handler answered with "
            f"{type(result).__name__}, which is neither ListToolsResult nor a mapping"
        ),
    )
