"""ORM-модели проекта.

Каждая модель наследует `app.db.base.BaseModel` и импортируется здесь: Alembic видит
таблицы только через `Base.metadata`, а метаданные наполняются в момент импорта модуля.
Модель, не импортированная в этом файле, для автогенерации миграций не существует.
"""

from app.db.base import Base, BaseModel
from app.db.models.actor import Actor
from app.db.models.api_token import ApiToken
from app.db.models.catalog import CatalogEntryMixin, IssueType, Resolution, Status
from app.db.models.field import Field, FieldIssueType
from app.db.models.issue import Issue, IssueFollower
from app.db.models.queue import Queue, QueueIssueType

__all__ = [
    "Actor",
    "ApiToken",
    "Base",
    "BaseModel",
    "CatalogEntryMixin",
    "Field",
    "FieldIssueType",
    "Issue",
    "IssueFollower",
    "IssueType",
    "Queue",
    "QueueIssueType",
    "Resolution",
    "Status",
]
