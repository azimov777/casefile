"""Схема ответа проверки здоровья."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Состояние сервиса. `database` подтверждается реальным запросом, а не наличием конфига."""

    status: Literal["ok"]
    version: str
    environment: str
    database: Literal["ok"]
