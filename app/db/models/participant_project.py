"""Проект в списке доступа участника-агента (TRK-746; слово владельца TRK~28#6).

Смысл строки зависит от режима участника (`participants.project_access_mode`): в `except`
проект закрыт, в `only` открыт, в `all` список пуст и не читается. Проект назван
идентификатором, не ключом. Пара уникальна; внешние ключи без `ondelete`: ни участники, ни
проекты не удаляются, а если однажды — база откажет, и список не изменится молча
(TRK/db#2). Предметные коды отказа отдаёт домен (`app/domain/project_access.py`).
"""

import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class ParticipantProject(BaseModel):
    """Строка списка: участник и проект."""

    __tablename__ = "participant_projects"
    __table_args__ = (
        # Имя по соглашению `uq_<таблица>_<колонка1>_<колонка2>` (TRK/db#25).
        UniqueConstraint("participant_id", "project_id"),
        # Участника покрывает уникальный индекс (он первая колонка); по проекту читают,
        # кого он касается.
        Index("ix_participant_projects_project_id", "project_id"),
    )

    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
