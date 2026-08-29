"""Зависимости FastAPI, общие для всех роутеров."""

import uuid
from typing import Annotated, Any

from fastapi import Depends, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import (
    FieldsDescription,
    QueryDescription,
    SortDescription,
)
from app.core.errors import UnauthorizedError
from app.db.models.actor import Actor
from app.db.pagination import MAX_PAGE_SIZE, MIN_PAGE_SIZE
from app.db.session import get_session, session_scope
from app.domain.search import MAX_QUERY_LENGTH, MAX_SORT_TERMS
from app.services.auth import authenticate_by_token
from app.services.event_stream import SessionFactory

# `scope="function"` — не украшение, а единственное, что доводит упавший коммит до
# клиента. FastAPI держит два стека завершения зависимостей: обычный закрывается уже
# **после** отправки ответа, и исключение из него превращается в
# `RuntimeError: Caught handled exception, but response already started` — клиент
# получает оборванный ответ вместо оболочки ошибки. Стек с областью `function`
# закрывается до отправки, и коммит, упавший на отложенном ограничении
# (`DEFERRABLE INITIALLY DEFERRED`), успевает стать нормальным `409 conflict`.
# Границу транзакции это не раздваивает: она по-прежнему одна, в `session_scope`.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
"""Сессия БД на время запроса. Тесты подменяют её через `app.dependency_overrides`."""

# `auto_error=False` обязателен: со значением по умолчанию FastAPI сам отвечает
# `403 {"detail": "Not authenticated"}` — мимо нашего конверта ошибки и с неверным
# статусом (по соглашениям отсутствие токена — это 401 `unauthorized`).
# Схема заодно попадает в OpenAPI, и в /docs появляется кнопка Authorize.
bearer_scheme = HTTPBearer(
    scheme_name="ApiToken",
    description="API token issued for an actor: `Authorization: Bearer trk_...`",
    auto_error=False,
)

CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_current_actor(session: SessionDep, credentials: CredentialsDep) -> Actor:
    """Актор, от имени которого выполняется запрос.

    Тонкая обёртка над сценарием `authenticate_by_token`: разбор заголовка — дело
    HTTP-слоя, всё остальное общее с MCP и командной строкой.
    """
    if credentials is None:
        raise UnauthorizedError(details={"reason": "missing_token"})
    return await authenticate_by_token(session, credentials.credentials)


CurrentActorDep = Annotated[Actor, Depends(get_current_actor)]
"""Текущий актор. Зависимость кешируется на запрос, поэтому лишнего похода в БД нет."""


def get_session_factory() -> SessionFactory:
    """Фабрика сессий для долгоживущего потока событий.

    Сессия запроса (`SessionDep`) потоку не годится: FastAPI закрывает её, когда
    обработчик вернул ответ, — то есть **до** того, как поток отдал первый кадр. А
    держать одну сессию всё время потока нельзя тем более: соединение из пула,
    занятое на часы, исчерпало бы пул на десятке клиентов.

    Поэтому поток получает не сессию, а способ открыть её на время одной выборки.
    Зависимостью, а не импортом, ровно затем, что и всё остальное здесь: тест подменяет
    её своей транзакцией и проверяет поток на данных, которых нет в общей базе.
    """
    return session_scope


StreamSessionsDep = Annotated[SessionFactory, Depends(get_session_factory)]
"""Способ открыть сессию на время одной выборки потока: сама сессия потоку не годится."""


# Параметры пагинации объявлены здесь, а не в каждом роутере: коллекции во всём API
# листаются одинаково, и три копии одного объявления неизбежно разъехались бы по
# границам и описаниям. Через `Annotated`, а не значением по умолчанию: так требует
# современный стиль FastAPI, и вызов `Query` не оказывается в списке аргументов, где
# он вычисляется один раз на всё приложение.
#
# Границы объявлены и здесь, и в `resolve_limit`, и это не дубль по недосмотру:
# параметр запроса даёт их в OpenAPI и отсекает мусор на входе, а проверка в сценарии
# работает для MCP и фоновых вызовов, которые мимо FastAPI не проходят.
LimitQuery = Annotated[int, Query(ge=MIN_PAGE_SIZE, le=MAX_PAGE_SIZE, description="Page size")]
CursorQuery = Annotated[
    str | None, Query(description="Cursor from `meta.next_cursor` of a previous page")
]


# Ключ задачи в пути. Объявлен здесь, а не в роутере задач: тем же ключом адресуют
# задачу связи и всё, что появится дальше, а два объявления одного параметра
# разъехались бы описаниями в сгенерированном клиенте.
#
# Без `pattern`: параметр адресует существующую задачу, а адресация в проекте мягкая.
# Невнятный ключ отвергает домен кодом `invalid_issue_key` с ожидаемым форматом в
# `details` — шаблон в пути такого объяснения дать не может.
IssueKeyPath = Annotated[
    str,
    Path(description="Issue key, immutable and never reused", examples=["TRK-123"]),
]


# Ключ очереди и ссылка на запись справочника — здесь по той же причине, что и ключ
# задачи: их принимают маршруты двух разных роутеров (очереди и справочники — свои,
# редактор воркфлоу — чужие), а два объявления одного параметра разъезжаются описаниями
# и примерами, и в сгенерированном клиенте один и тот же параметр выглядит по-разному.
#
# Без `pattern`: параметр адресует существующий объект, а адресация в проекте мягкая —
# `trk` находит ту же очередь, что и `TRK`. Строгий шаблон стоит в схеме создания, где
# ключ придумывают; невнятную ссылку справочника отвергает `parse_catalog_ref` кодом
# `invalid_catalog_ref` — с ожидаемым форматом в `details`, чего шаблон дать не может.
QueueKeyPath = Annotated[
    str,
    Path(description="Queue key, immutable once created", examples=["TRK"]),
]


def catalog_ref_path(kind: str) -> Any:
    """Параметр пути со ссылкой на запись справочника нужного вида."""
    return Path(
        description=f"{kind} reference: `key` for a global entry, `QUEUE.key` for a local one",
        examples=["open", "TRK.open"],
    )


StatusRefPath = Annotated[str, catalog_ref_path("Status")]
IssueTypeRefPath = Annotated[str, catalog_ref_path("Issue type")]
ResolutionRefPath = Annotated[str, catalog_ref_path("Resolution")]


# Параметры поиска объявлены здесь по той же причине, что и параметры пагинации: их
# принимают два роутера — общий поиск и список задач проекта, — и две копии описания
# разъехались бы в сгенерированном клиенте, показав фронтенду разные подсказки для
# одного и того же параметра.
#
# Импорт описаний из схем, а не повтор строк: тексты попадают ещё и в тело запроса
# `POST /search/issues`, и третьего варианта формулировки быть не должно.
QueryParam = Annotated[
    str | None,
    Query(max_length=MAX_QUERY_LENGTH, description=QueryDescription),
]
SortParam = Annotated[
    list[str] | None,
    Query(max_length=MAX_SORT_TERMS, description=SortDescription),
]
FieldsParam = Annotated[list[str] | None, Query(description=FieldsDescription)]
SavedFilterParam = Annotated[
    uuid.UUID | None,
    Query(description="Run a saved filter; `query` narrows it further"),
]
