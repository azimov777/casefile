"""ORM-модели проекта.

Каждая модель наследует `app.db.base.BaseModel` и импортируется здесь: Alembic видит
таблицы только через `Base.metadata`, а метаданные наполняются в момент импорта модуля.
Модель, не импортированная в этом файле, для автогенерации миграций не существует.
"""

from app.db.base import Base, BaseModel
from app.db.models.actor import Actor
from app.db.models.api_token import ApiToken
from app.db.models.automation import AutomationRule, AutomationRun
from app.db.models.board import Board, BoardColumn, BoardColumnStatus, IssueRank
from app.db.models.catalog import CatalogEntryMixin, IssueType, Resolution, Status
from app.db.models.checklist import ChecklistItem
from app.db.models.comment import Comment
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.field import Field, FieldIssueType
from app.db.models.issue import Issue, IssueFollower
from app.db.models.link import IssueLink
from app.db.models.notification import Notification, Subscription
from app.db.models.project import (
    PlanningEntityMixin,
    Portfolio,
    PortfolioMember,
    Project,
    ProjectMember,
)
from app.db.models.queue import Queue, QueueIssueType
from app.db.models.saved_filter import SavedFilter
from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.db.models.workflow import Transition, Workflow, WorkflowStatus

__all__ = [
    "Actor",
    "ApiToken",
    "AutomationRule",
    "AutomationRun",
    "Base",
    "BaseModel",
    "Board",
    "BoardColumn",
    "BoardColumnStatus",
    "CatalogEntryMixin",
    "ChangelogEntry",
    "ChecklistItem",
    "Comment",
    "Field",
    "FieldIssueType",
    "Issue",
    "IssueFollower",
    "IssueLink",
    "IssueRank",
    "IssueType",
    "Notification",
    "OutboxEvent",
    "PlanningEntityMixin",
    "Portfolio",
    "PortfolioMember",
    "Project",
    "ProjectMember",
    "Queue",
    "QueueIssueType",
    "Resolution",
    "SavedFilter",
    "Status",
    "Subscription",
    "Transition",
    "WebhookDelivery",
    "WebhookSubscription",
    "Workflow",
    "WorkflowStatus",
]
