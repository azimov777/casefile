"""Репозитории проекта: сценарии импортируют их из одного места."""

from app.db.repositories.accounts import AccountRepository
from app.db.repositories.entries import EntryRepository
from app.db.repositories.idempotency import IdempotencyRepository
from app.db.repositories.links import LinkRepository
from app.db.repositories.participants import ParticipantRepository
from app.db.repositories.queues import QueueRepository
from app.db.repositories.search import TaskSearchRepository
from app.db.repositories.tasks import TaskRepository
from app.db.repositories.tokens import TokenRepository

__all__ = [
    "AccountRepository",
    "EntryRepository",
    "IdempotencyRepository",
    "LinkRepository",
    "ParticipantRepository",
    "QueueRepository",
    "TaskRepository",
    "TaskSearchRepository",
    "TokenRepository",
]
