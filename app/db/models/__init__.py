"""ORM-модели проекта.

Каждая модель наследует `app.db.base.BaseModel` и импортируется здесь: Alembic видит
таблицы только через `Base.metadata`, а метаданные наполняются в момент импорта модуля.
Модель, не импортированная в этом файле, для автогенерации миграций не существует.
"""

from app.db.base import Base, BaseModel
from app.db.models.author import CreatedByMixin, created_by_columns
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.token import Token

__all__ = [
    "Base",
    "BaseModel",
    "CreatedByMixin",
    "Participant",
    "Queue",
    "Token",
    "created_by_columns",
]
