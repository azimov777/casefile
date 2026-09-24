"""Проект: единственный уровень группировки задач."""

from sqlalchemy import CheckConstraint, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel
from app.db.models.author import CreatedByMixin
from app.domain.projects import MAX_PROJECT_DESCRIPTION_LENGTH


class Project(BaseModel, CreatedByMixin):
    """Строка реестра проектов.

    Проект отвечает на вопрос «про что задачи», а не «кто делает» (`CONCEPT.md`, 3.2).
    Описание — короткое «что это», не длиннее `MAX_PROJECT_DESCRIPTION_LENGTH` знаков: оно
    едет в карточке каждой задачи проекта вместе с ключом и названием. Факты проекта живут
    в атрибутах, решения — в его деле.

    Удаления нет, ключ неизменяем: ключ вшит в ключ каждой задачи проекта.
    """

    __tablename__ = "projects"
    __table_args__ = (
        # Предел проверяет домен (`validate_project_description`) и отвечает предметным
        # кодом; ограничение в схеме — страховка от записи мимо сценариев (миграция,
        # приём архива переноса). `char_length` считает знаки, как `len` в Python.
        CheckConstraint(
            f"char_length(description) <= {MAX_PROJECT_DESCRIPTION_LENGTH}",
            name="description_length",
        ),
    )

    # Ключ хранится канонизированным (верхний регистр) — как и имя участника, только в
    # другую сторону. Уникальность без учёта регистра держит обычное `UNIQUE`.
    key: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)

    # Счётчик выданных номеров, а не число задач: номер не переиспользуется, и удалённая
    # (в будущем — отменённая) задача свой номер с собой не уносит. Инкремент делает
    # база одним `UPDATE ... RETURNING` — см. `ProjectRepository.allocate_task_number`.
    last_task_number: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
