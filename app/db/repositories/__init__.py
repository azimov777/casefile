"""Репозитории проекта: сценарии импортируют их из одного места."""

from app.db.repositories.actors import ActorRepository
from app.db.repositories.api_tokens import ApiTokenRepository
from app.db.repositories.catalogs import CatalogRepository
from app.db.repositories.queues import QueueRepository

__all__ = [
    "ActorRepository",
    "ApiTokenRepository",
    "CatalogRepository",
    "QueueRepository",
]
