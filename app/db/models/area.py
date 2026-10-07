"""Область: бесконечная часть работы внутри одного проекта."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.author import CreatedByMixin
from app.db.models.project import Project
from app.domain.areas import (
    MAX_AREA_DESCRIPTION_LENGTH,
    MAX_AREA_KEY_LENGTH,
    format_area_address,
)


class Area(BaseModel, CreatedByMixin):
    """Строка реестра областей (`CONCEPT.md`, 3.7; решения владельца `TRK#16`, `TRK#17`).

    Устроена как проект, только меньше: ключ, название, короткое описание и время архива;
    атрибуты — `area_attributes`, дело — записи `entries` с `area_id`. Статуса,
    исполнителя и проверок нет. Родительской области нет тоже: области пока
    плоские (`TRK#17`), и колонки под вложенность здесь нет намеренно.

    Удаления нет, проект и ключ неизменяемы: адрес `TRK/promotion` стоит в ссылках записей.
    """

    __tablename__ = "areas"
    __table_args__ = (
        # Ключ хранится канонизированным (нижний регистр, `app/domain/areas.py`), и
        # уникальность без учёта регистра внутри проекта держит обычное `UNIQUE` — как у
        # ключа проекта. Тот же индекс отвечает на поиск по адресу.
        UniqueConstraint("project_id", "key"),
        # Предел проверяет домен и отвечает предметным кодом; ограничение — страховка от
        # записи мимо сценариев (приём архива переноса), как у проекта.
        CheckConstraint(
            f"char_length(description) <= {MAX_AREA_DESCRIPTION_LENGTH}",
            name="description_length",
        ),
    )

    # Без `ondelete`: проекты не удаляются, а если однажды — база откажет.
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(MAX_AREA_KEY_LENGTH), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    # Время архивирования или `NULL` у живой области. Заморозку по нему проверяет одна
    # точка — `app/services/freeze.py`.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Ключ проекта — половина адреса, и адрес нужен почти каждому ответу, поэтому `joined`:
    # одно соединение вместо второго запроса (так же `Task.project`).
    project: Mapped[Project] = relationship(lazy="joined")

    @property
    def address(self) -> str:
        """Адрес области: `TRK/promotion`. Им область называют везде."""
        return format_area_address(self.project.key, self.key)
