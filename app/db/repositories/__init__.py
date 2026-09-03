"""Репозитории проекта: сценарии импортируют их из одного места."""

from app.db.repositories.actors import ActorRepository
from app.db.repositories.api_tokens import ApiTokenRepository

__all__ = [
    "ActorRepository",
    "ApiTokenRepository",
]
