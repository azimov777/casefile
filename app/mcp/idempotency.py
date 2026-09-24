"""Сторона MCP у идемпотентности: аргумент вместо заголовка.

Сам механизм живёт в `app/services/idempotency.py` и общий с REST. Здесь только то, чем
инструмент отличается от маршрута: ключ приезжает аргументом `idempotency_key`, а имя
операции берётся у самой функции инструмента.

## Имя операции — имя инструмента, и берётся оно у функции

Отпечаток вызова считается по паре «операция + аргументы» (`app/domain/idempotency.py`).
Строка, написанная по месту, разошлась бы с именем инструмента при первом переименовании,
и повтор старого ключа получил бы `409` на ровном месте. Поэтому `Once.of` принимает саму
функцию: её `__name__` — это и есть имя, под которым инструмент зарегистрирован
(`app/mcp/toolset.py`). Тот же приём, что у REST, где имя берётся из маршрута
(`app/api/idempotency.py`).

## Что обязан и чего не должен делать `build`

Требования два, и оба невыразимы сигнатурой (`app/services/idempotency.py`):

- **не фиксировать транзакцию.** Промежуточный коммит опубликовал бы занятый ключ с
  пустым ответом, и одновременный повтор получил бы строку, отвечать по которой нечем.
  Границу держит `Runtime.call`, и инструменты своей транзакции не открывают;
- **вернуть значение объявленного типа.** Оно ложится в базу и оттуда же достаётся
  повтору. Представления (`app/mcp/views.py`) отдают модели pydantic; в базу их приводит
  к JSON сам `Once`, а обратно поднимает той же моделью. Оба конца проходит и **первый**
  вызов, а не только повтор: иначе первый ответ отличался бы от повторного написанием
  времени, и расхождение всплыло бы у агента, а не в тесте.

И отдельно про порядок: всё, что может отказать (разрешение ключей задач, поиск проекта),
делается **до** `Once`. Иначе отклонённый вызов потратил бы ключ, а повтор с тем же
ключом ответил бы конфликтом вместо работы.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import idempotency as service
from app.services.auth import Actor


@dataclass(frozen=True, slots=True)
class Once:
    """Способ выполнить работу инструмента один раз на ключ идемпотентности."""

    session: AsyncSession
    actor: Actor
    key: str | None
    #: Имя операции — оно же имя инструмента. См. раздел в начале файла.
    operation: str

    @classmethod
    def of(
        cls,
        tool: Callable[..., Any],
        session: AsyncSession,
        actor: Actor,
        key: str | None,
    ) -> Once:
        """Идемпотентность вызова инструмента `tool`."""
        return cls(session=session, actor=actor, key=key, operation=tool.__name__)

    async def run[ResultT: BaseModel](
        self,
        *,
        request: Any,
        result: type[ResultT],
        build: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        """Зовёт `build` или отдаёт результат первого вызова с этим ключом.

        `request` — то, что отличает этот вызов от другого. Значения передаются
        **разрешёнными** (`TRK-1`, а не `trk-1`): адресация в проекте мягкая, и иначе
        повтор того же вызова другим написанием ключа отвечал бы конфликтом.

        `result` — модель ответа инструмента. Она нужна здесь потому, что хранилище
        знает только JSON: сохранённый ответ поднимается обратно ею, и повтор отвечает
        объектом того же типа, что и первый вызов. Вывести её из `build` нельзя —
        аннотация замыкания до вызова не читается.

        И запрос, и результат проходят через сериализатор pydantic: отпечаток считается
        по каноническому JSON, а ответ хранится в базе. Тот же путь проходит **первый**
        вызов, а не только повтор, — иначе первый ответ отличался бы от повторного, и
        расхождение всплыло бы у агента, а не в тесте.
        """

        async def encoded() -> Any:
            return to_jsonable_python(await build())

        stored = await service.run_once(
            self.session,
            actor=self.actor,
            key=self.key,
            operation=self.operation,
            request=to_jsonable_python(request),
            build=encoded,
        )
        assert isinstance(stored, dict)
        return result.model_validate(stored)
