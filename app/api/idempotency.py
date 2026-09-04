"""HTTP-сторона идемпотентности: заголовок, отпечаток запроса и повтор ответа.

Сам механизм живёт в `app/services/idempotency.py` и общий с MCP. Здесь только то, чего
у MCP нет: имя заголовка, перевод запроса и ответа в JSON и объявление зависимости.

## Почему обработчик оборачивает свою работу в замыкание

Ключ обязан быть занят **до** работы, а ответ записан **после** неё, и всё это — внутри
транзакции запроса. Ни зависимость, ни промежуточный слой в эту рамку не помещаются:
зависимость закрывается уже после того, как ответ собран, а слой видит только байты и не
знает про транзакцию. Поэтому обработчик отдаёт свою работу как замыкание, а
`Once.run` решает, звать его или отдать сохранённый ответ.

## Ответ всегда проходит через JSON и обратно

И у первого вызова, и у повтора. Лишняя проверка модели на первом вызове стоит
микросекунд и покупает важное: путь повтора исполняется на **каждом** создающем
запросе. Модель, которая не собирается обратно из своего же JSON, ломается сразу и
громко, а не через сутки на повторе у агента.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorDep, SessionDep
from app.domain.idempotency import IDEMPOTENCY_KEY_HEADER, KEY_TTL, MAX_KEY_LENGTH
from app.services import idempotency as service
from app.services.auth import Actor

# Шаблона и границ длины в объявлении нет намеренно, по тому же правилу, что у метки
# временного агента (`app/api/deps.py`): форму ключа проверяет домен, одинаково для REST
# и для MCP. С `max_length` здесь длинный ключ приходил бы в REST общим
# `validation_error`, а в MCP — предметным `invalid_idempotency_key` с потолком в
# подробностях, то есть один и тот же вход отвечал бы двум интерфейсам по-разному.
IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias=IDEMPOTENCY_KEY_HEADER,
        examples=["6b1f0c34-9b2e-4b0a-9a5f-3f1d6c8e0a11"],
        description=(
            "Makes this creating call safe to repeat. A retry with the same key and the "
            "same request answers with the first response instead of creating a second "
            "object; the same key with a different request answers 409 "
            f"idempotency_key_reused. Keys are paired with the token, are at most "
            f"{MAX_KEY_LENGTH} characters long and are forgotten after "
            f"{int(KEY_TTL.total_seconds() // 3600)} hours"
        ),
    ),
]


@dataclass(frozen=True, slots=True)
class Once:
    """Способ выполнить работу обработчика один раз на ключ идемпотентности."""

    session: AsyncSession
    actor: Actor
    key: str | None
    #: Имя операции — оно же `operation_id` маршрута. Берётся из маршрута, а не пишется
    #: строкой у вызывающего: строка разошлась бы с именем обработчика при первом же
    #: переименовании, и повтор старого ключа получил бы `409` на ровном месте.
    operation: str
    status_code: int | None

    async def run[ResponseT: BaseModel](
        self,
        model: type[ResponseT],
        *,
        request: Any,
        build: Callable[[], Awaitable[ResponseT]],
    ) -> ResponseT:
        """Зовёт `build` или отдаёт ответ первого вызова с этим ключом.

        `request` — то, что отличает этот вызов от другого: тело запроса и всё, что
        приехало путём. Значения пути передаются **разрешёнными** (`task.key`, а не
        `task_key` из адреса): адресация в проекте мягкая, и `trk-1` с `TRK-1` иначе
        считались бы разными запросами, то есть повтор отвечал бы конфликтом.
        """

        async def encoded() -> Any:
            return jsonable_encoder(await build())

        stored = await service.run_once(
            self.session,
            actor=self.actor,
            key=self.key,
            operation=self.operation,
            request=jsonable_encoder(request),
            build=encoded,
            status_code=self.status_code,
        )
        return model.model_validate(stored)


def get_once(
    request: Request,
    session: SessionDep,
    actor: ActorDep,
    key: IdempotencyKeyHeader = None,
) -> Once:
    """Зависимость создающих маршрутов: ключ из заголовка плюс имя и статус маршрута.

    Маршрут лежит в `scope` к моменту разбора зависимостей — Starlette кладёт его туда
    при выборе обработчика. Отсюда берутся имя операции (`route.name`, из него же
    собирается `operation_id`) и объявленный статус ответа: дублировать их в каждом
    вызове значило бы завести второй источник правды о маршруте.
    """
    route = request.scope["route"]
    return Once(
        session=session,
        actor=actor,
        key=key,
        operation=route.name,
        status_code=route.status_code,
    )


OnceDep = Annotated[Once, Depends(get_once)]
"""Идемпотентность создающего маршрута: объявлена зависимостью — значит, есть в схеме."""
