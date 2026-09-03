"""Контекст одного вызова инструмента: сессия БД и актор за токеном.

Инструмент MCP устроен так же, как обработчик HTTP-запроса: открыть сессию, узнать, кто
зовёт, позвать сценарий. Разница ровно одна — токен приезжает не через зависимость
FastAPI, а из заголовков сообщения MCP, поэтому разбор заголовка живёт здесь.

## Границу транзакции держит вход, а не инструмент

`Runtime.sessions` — это `session_scope` (`app/db/session.py`), тот же, которым
пользуются HTTP-запрос и командная строка: вышли из блока без исключения — коммит, с
исключением — откат. Своей транзакции инструмент не открывает, и это не стилистика.
Долгое ожидание обязано отпускать соединение на время сна, а собственная транзакция
поверх сценария это свойство отменила бы: несколько ждущих агентов исчерпали бы пул
соединений, и встал бы весь остальной сервер.

## Фабрика сессий — параметр, а не импорт

Сервер собирается функцией и получает фабрику извне: тесты подставляют свою, привязанную
к откатываемой транзакции теста. Тот же приём, что у сессии запроса в `app/api/deps.py`,
которую тест подменяет через `app.dependency_overrides`.

## Заголовки доезжают до вызова контекстной переменной

Инструмент получил бы их из объекта `Context`, но **ресурс** — нет: SDK запрещает
внедрять контекст в статический ресурс (`Context injection for static resources is not
supported`). Поэтому заголовки входящего сообщения кладёт в контекстную переменную
`headers_middleware`, и берут их оттуда и инструменты, и ресурсы — одним способом, а не
двумя.

Переменная восстанавливается токеном (`reset`), а не присваиванием `None`: сообщения
обрабатываются конкурентно, и оставленное значение утекло бы в соседний вызов — то есть
чужой токен стал бы действующим.
"""

import contextvars
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.context import ServerRequestContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, UnauthorizedError
from app.db.models.actor import Actor
from app.db.session import session_scope
from app.mcp.errors import resource_error, tool_error
from app.services.auth import authenticate_by_token

#: Как открыть сессию с транзакцией. По умолчанию — `session_scope`; тесты дают свою.
type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_AUTHORIZATION = "authorization"
_BEARER = "bearer"

#: Заголовки обрабатываемого сейчас сообщения MCP. Заполняет `headers_middleware`.
_headers: contextvars.ContextVar[Mapping[str, str] | None] = contextvars.ContextVar(
    "mcp_request_headers",
    default=None,
)


@asynccontextmanager
async def use_headers(headers: Mapping[str, str] | None) -> AsyncIterator[None]:
    """Подставляет заголовки текущего вызова. Нужен тестам и `headers_middleware`."""
    token = _headers.set(headers)
    try:
        yield
    finally:
        _headers.reset(token)


async def headers_middleware(ctx: ServerRequestContext[Any, Any], call_next: Any) -> Any:
    """Кладёт заголовки входящего сообщения в контекстную переменную на время его обработки.

    Регистрируется на сервере один раз и действует на все сообщения — и на вызовы
    инструментов, и на чтение ресурсов. Второй способ добраться до токена (аргумент
    инструмента, отдельная схема авторизации) заводить нельзя: он немедленно разошёлся
    бы с REST, где токен один и тот же.
    """
    async with use_headers(getattr(ctx.request, "headers", None)):
        return await call_next(ctx)


@dataclass(frozen=True, slots=True)
class Runtime:
    """Всё, что нужно инструменту помимо его собственных аргументов."""

    sessions: SessionFactory = session_scope

    @asynccontextmanager
    async def call(self) -> AsyncIterator[tuple[AsyncSession, Actor]]:
        """Сессия и актор на время вызова инструмента.

        Доменная ошибка становится `ToolError`: она приезжает модели как результат с
        текстом, а не как сбой протокола, и по ней агент исправляет вызов.
        """
        try:
            async with self._open() as pair:
                yield pair
        except AppError as exc:
            raise tool_error(exc) from exc

    @asynccontextmanager
    async def read(self) -> AsyncIterator[tuple[AsyncSession, Actor]]:
        """То же самое для чтения ресурса.

        Отдельный метод, потому что у ресурса своё семейство ошибок: `ToolError`,
        вылетевший из ресурса, SDK считает крахом обработчика и заменяет сообщение на
        безличное — то есть отбирает у агента причину отказа.
        """
        try:
            async with self._open() as pair:
                yield pair
        except AppError as exc:
            raise resource_error(exc) from exc

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[tuple[AsyncSession, Actor]]:
        """Сессия и актор за токеном.

        Перевод ошибки стоит **снаружи** сессии: сначала транзакция откатывается, и
        только потом ошибка превращается в текст для агента. Обратный порядок оставил бы
        часть изменений записанной.
        """
        async with self.sessions() as session:
            actor = await authenticate_by_token(session, bearer_token(_headers.get()))
            yield session, actor


def bearer_token(headers: Mapping[str, str] | None) -> str:
    """Секрет токена из заголовка `Authorization: Bearer ...`.

    Схема та же, что у REST: акторы и токены одни на оба интерфейса, и второй способ
    представиться означал бы вторую модель доступа. Отсутствие заголовка — обычный
    `unauthorized` с причиной в подробностях: по ней агент понимает, что дело в
    настройке клиента, а не в самом вызове.
    """
    value = None if headers is None else headers.get(_AUTHORIZATION)
    if not value:
        raise UnauthorizedError(
            message="Authorization header with an actor API token is required",
            details={"reason": "missing_token", "header": "Authorization: Bearer <token>"},
        )
    scheme, _, secret = value.partition(" ")
    if scheme.lower() != _BEARER or not secret.strip():
        raise UnauthorizedError(
            message="Authorization header must use the Bearer scheme",
            details={"reason": "invalid_scheme", "header": "Authorization: Bearer <token>"},
        )
    return secret.strip()
