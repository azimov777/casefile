"""Зависимости FastAPI, общие для всех роутеров."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
"""Сессия БД на время запроса. Тесты подменяют её через `app.dependency_overrides`."""
