"""Зависимости FastAPI, общие для всех роутеров."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.actor import Actor
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
