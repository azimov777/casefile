"""Регистрация инструментов MCP.

Набора токена нет (TRK-471): любой действующий доступ агента видит в `tools/list` все
инструменты и зовёт любой. По HTTP токен проверяет проверяющий SDK (`verify_token`), по
stdio — промежуточный слой ниже; доступ сценария решает сам сценарий (запись доступов —
человеку с учётной записью).

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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_REQUEST, ToolAnnotations

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.idempotency import IDEMPOTENCY_KEY_ARGUMENT
from app.mcp.errors import describe
from app.mcp.runtime import Runtime

#: Метод, которому нужен разобранный токен до ответа.
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

# Четыре формы аннотаций, по числу различных поведений среди инструментов сервера
# (правило — `docs/notes/mcp.md`, «Аннотации протокола ставятся по поведению вызова»).
# `open_world_hint` у всех `False`: сервер работает с собственными данными установки, а
# не с внешним миром, — ни у одного инструмента такого взаимодействия нет.

#: Читающий инструмент: не меняет состояние, поэтому и повтор без ключа безопасен.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

#: Подшивающий или переводящий инструмент: журнал дела только дописывается — ничего
#: прежнего он не стирает, — но без ключа идемпотентности повтор с теми же аргументами
#: не гарантирует то же состояние: заводит вторую запись/объект или отказывает
#: конфликтом (`link`, `create_task`) либо неприменимым переходом (`transition`).
FILING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)

#: Частичная правка задачи (`update_task`): переданное значение, совпавшее с текущим,
#: не подшивает запись и не поднимает версию (`app/services/tasks.py`,
#: `apply_task_changes`, `_same`) — повтор с теми же аргументами не меняет состояние
#: второй раз. Не разрушает ничего: правка полей задачи хранит `before`/`after` в
#: `section_changed`/`field_changed`, то есть прежнее значение остаётся в деле.
#:
#: Та же форма у правки карточки проекта (`update_project`) с TRK-156: у проекта есть
#: дело, и правка названия и описания подшивает `field_changed` с прежним значением
#: (`app/services/projects.py`, `update_project`).
IDEMPOTENT_TASK_UPDATE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

#: Правка участника (`update_participant`): тоже идемпотентна — то же значение второй раз
#: ничего не меняет, — но, в отличие от задачи и проекта, у участника нет дела: прежнее
#: описание перезаписывается без следа (`app/services/participants.py`). Разрушающее
#: обновление в буквальном смысле хинта.
OVERWRITING_UPDATE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


@dataclass(slots=True)
class Toolset:
    """Сервер, контекст вызова и имена зарегистрированных инструментов.

    Передаётся модулям инструментов вместо самого сервера: декоратор здесь только один,
    и через него проходят ключ идемпотентности и аннотации.
    """

    server: MCPServer
    runtime: Runtime
    settings: Settings
    names: list[str] = field(default_factory=list)

    def tool(
        self,
        *,
        title: str,
        annotations: ToolAnnotations,
        creating: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Объявляет инструмент: имя берётся из функции, описание — из её докстроки.

        `creating` означает «вызов заводит объект»: концепция требует, чтобы такой вызов
        принимал ключ идемпотентности (`CONCEPT.md`, 4.5). Наличие аргумента проверяется
        здесь, при сборке, а не тестом на каждый инструмент: забытый ключ иначе
        обнаружился бы у агента, который повторил упавший вызов и завёл второй объект.

        `annotations` обязателен по той же причине и тем же способом: у нового
        инструмента без объявленного поведения (`readOnlyHint`/`destructiveHint`/
        `idempotentHint`/`openWorldHint`, `docs/notes/mcp.md`) сборка сервера упадёт
        здесь, а не когда клиент решит по умолчанию протокола, что вызов деструктивен.
        `title` — короткое человеческое имя инструмента по-английски; обязателен тем же
        способом (TRK-443). Оно кладётся и в `Tool.title`, и в `annotations.title`: каталоги
        и клиенты читают то или другое.
        Готовые формы — `READ_ONLY`, `FILING`, `IDEMPOTENT_TASK_UPDATE`,
        `OVERWRITING_UPDATE` в шапке модуля; собственная форма нужна инструменту, чьё
        поведение не совпадает ни с одной из них.
        """

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            name = function.__name__
            if creating and IDEMPOTENCY_KEY_ARGUMENT not in inspect.signature(function).parameters:
                raise TypeError(
                    f"Creating tool {name!r} must accept a {IDEMPOTENCY_KEY_ARGUMENT!r} "
                    "argument: a repeated call has to answer with the first result "
                    "instead of creating a second object"
                )
            self.names.append(name)
            titled = annotations.model_copy(update={"title": title})
            self.server.tool(name=name, title=title, annotations=titled)(function)
            return function

        return register

    def middleware(self) -> Callable[..., Any]:
        """Промежуточный слой: `tools/list` с неизвестным токеном получает отказ."""

        async def check_token(
            ctx: ServerRequestContext[Any, Any],
            call_next: Callable[[ServerRequestContext[Any, Any]], Any],
        ) -> Any:
            if ctx.method == LIST_TOOLS:
                await self._authenticate()
            return await call_next(ctx)

        return check_token

    async def _authenticate(self) -> None:
        """Разбирает токен текущего сообщения **до** сборки списка инструментов.

        Неизвестный токен обязан получить отказ, а не полный список (по stdio нет
        проверяющего транспорта, `app/mcp/__main__.py`). Отказ переводится в ошибку
        **протокола**, а не в ошибку инструмента: `tools/list` не инструмент, и `ToolError`
        отсюда клиент прочитал бы как сбой обработчика без причины.
        """
        try:
            async with self.runtime.session():
                return
        except AppError as exc:
            raise MCPError(code=INVALID_REQUEST, message=describe(exc)) from exc
