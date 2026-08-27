"""Зависимости FastAPI, общие для всех роутеров."""

from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.actor import Actor
from app.db.pagination import MAX_PAGE_SIZE, MIN_PAGE_SIZE
from app.db.session import get_session
from app.services.auth import authenticate_by_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]
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
