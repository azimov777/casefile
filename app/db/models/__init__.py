"""ORM-модели проекта.

Каждая модель наследует `app.db.base.BaseModel` и импортируется здесь: Alembic видит
таблицы только через `Base.metadata`, а метаданные наполняются в момент импорта модуля.
Модель, не импортированная в этом файле, для автогенерации миграций не существует.
"""

from app.db.base import Base, BaseModel
from app.db.models.account import Account
from app.db.models.attribute import DirectionAttribute, ProjectAttribute
from app.db.models.author import CreatedByMixin, created_by_columns
from app.db.models.direction import Direction
from app.db.models.entry import Entry
from app.db.models.idempotency import IdempotencyKey
from app.db.models.link import Link
from app.db.models.oauth import OAuthClient, OAuthCode, OAuthRefreshToken
from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.models.token import Token

__all__ = [
    "Account",
    "Base",
    "BaseModel",
    "CreatedByMixin",
    "Direction",
    "DirectionAttribute",
    "Entry",
    "IdempotencyKey",
    "Link",
    "OAuthClient",
    "OAuthCode",
    "OAuthRefreshToken",
    "Participant",
    "Project",
    "ProjectAttribute",
    "Task",
    "Token",
    "created_by_columns",
]
