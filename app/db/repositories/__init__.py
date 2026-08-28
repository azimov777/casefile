"""Репозитории проекта: сценарии импортируют их из одного места."""

from app.db.repositories.actors import ActorRepository
from app.db.repositories.api_tokens import ApiTokenRepository
from app.db.repositories.automation import AutomationRuleRepository, AutomationRunRepository
from app.db.repositories.boards import BoardIssueRepository, BoardRepository, SprintRepository
from app.db.repositories.catalogs import CatalogRepository
from app.db.repositories.checklists import ChecklistRepository
from app.db.repositories.comments import CommentRepository
from app.db.repositories.events import ChangelogRepository, OutboxRepository
from app.db.repositories.fields import FieldRepository
from app.db.repositories.issues import IssueRepository
from app.db.repositories.links import IssueLinkRepository
from app.db.repositories.projects import PortfolioRepository, ProjectRepository
from app.db.repositories.queues import QueueRepository
from app.db.repositories.saved_filters import SavedFilterRepository
from app.db.repositories.search import IssueSearchRepository
from app.db.repositories.workflows import WorkflowRepository

__all__ = [
    "ActorRepository",
    "ApiTokenRepository",
    "AutomationRuleRepository",
    "AutomationRunRepository",
    "BoardIssueRepository",
    "BoardRepository",
    "CatalogRepository",
    "ChangelogRepository",
    "ChecklistRepository",
    "CommentRepository",
    "FieldRepository",
    "IssueLinkRepository",
    "IssueRepository",
    "IssueSearchRepository",
    "OutboxRepository",
    "PortfolioRepository",
    "ProjectRepository",
    "QueueRepository",
    "SavedFilterRepository",
    "SprintRepository",
    "WorkflowRepository",
]
