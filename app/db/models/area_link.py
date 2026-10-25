"""Связь области с областью `see_also`: одна строка на направленную пару.

Строка читается так: область `source` ссылается на область `target` — «кто работает в
источнике, читает ещё цель» (`app/domain/area_links.py`). Обратная сторона (`see_also_from`)
вычисляется при чтении, второй строки нет. Причина обязательна: от 1 до 200 знаков.

Базе достаются инварианты одной строки: нет связи с собой, пара уникальна, причина в
пределах. Предметные коды отказа отдаёт домен; ограничения — страховка от записи мимо
сценариев (приём архива переноса). Граф не обходят, кольца база не проверяет.

Внешние ключи без `ondelete`: области не удаляются, а если однажды — база откажет и
связи не исчезнут молча (так же `links`, TRK/links#11).
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.area import Area
from app.db.models.author import CreatedByMixin
from app.domain.area_links import MAX_AREA_LINK_REASON_LENGTH


class AreaLink(BaseModel, CreatedByMixin):
    """Связь `see_also`: область-источник, область-цель, причина, автор и время."""

    __tablename__ = "area_links"
    __table_args__ = (
        # Имя по соглашению `uq_<таблица>_<колонка1>_<колонка2>` (TRK/db#25).
        UniqueConstraint("source_area_id", "target_area_id"),
        CheckConstraint("source_area_id <> target_area_id", name="no_self_link"),
        CheckConstraint(
            f"char_length(reason) BETWEEN 1 AND {MAX_AREA_LINK_REASON_LENGTH}",
            name="reason_length",
        ),
        # Исходящие связи покрывает уникальный индекс (источник — первая колонка);
        # входящие читаются по цели.
        Index("ix_area_links_target_area_id", "target_area_id"),
    )

    source_area_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("areas.id"), nullable=False)
    target_area_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("areas.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # `foreign_keys` обязателен: путей между связью и областью два. `selectin`: обе
    # стороны нужны всегда (адрес, название), а проект области подтягивается её `joined`.
    source: Mapped[Area] = relationship(lazy="selectin", foreign_keys=[source_area_id])
    target: Mapped[Area] = relationship(lazy="selectin", foreign_keys=[target_area_id])
