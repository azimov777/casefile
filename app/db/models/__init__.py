"""ORM-модели проекта.

Каждая модель наследует `app.db.base.BaseModel` и импортируется здесь: Alembic видит
таблицы только через `Base.metadata`, а метаданные наполняются в момент импорта модуля.
Модель, не импортированная в этом файле, для автогенерации миграций не существует.
"""

from app.db.base import Base, BaseModel
from app.db.models.actor import Actor
from app.db.models.api_token import ApiToken

__all__ = ["Actor", "ApiToken", "Base", "BaseModel"]
