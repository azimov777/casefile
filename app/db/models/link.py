"""Связь между двумя задачами: одна строка на связь, видимая с обеих сторон.

Направление приведено к каноническому виду до вставки (`app/domain/links.py`), поэтому
в колонке `kind` встречаются только «прямые» виды (`parent`, `blocks`, `relates`), а
обратная сторона вычисляется при чтении. Хранить обе стороны двумя строками нельзя:
удаление одной оставило бы вторую висеть, и задача осталась бы заблокирована задачей,
которая её не блокирует.

Строка читается так: `source` **является** этим для `target`. У `parent` источник —
родитель, у `blocks` источник блокирует цель.

## Что стережёт база, а что сценарий

Базе достаются инварианты, выражаемые одной строкой или одним индексом: нет связи
задачи с самой собой, нет двух одинаковых связей, в `kind` не попадает обратный вид.
Это вторая линия обороны; первую держит `app/services/links.py`, и именно он отдаёт
клиенту предметный код ошибки.

Отсутствие циклов базой не проверяется и проверено быть не может: это свойство графа
целиком, а не строки. Оно живёт в сценарии, и цена этого названа в `docs/notes/links.md`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.db.models.task import Task
from app.domain.links import STORED_LINK_KINDS, LinkKind, visible_kind

#: Литерал списка канонических видов для ограничения CHECK. Собирается из домена, а не
#: пишется руками: два независимых перечня разошлись бы при добавлении вида связи, и
#: база молча приняла бы то, чего код не умеет читать.
_STORED_KINDS_SQL = ", ".join(f"'{kind.value}'" for kind in sorted(STORED_LINK_KINDS))


class Link(BaseModel, CreatedByMixin):
    """Связь: исходная задача, целевая задача, вид, автор и время.

    `source` и `target` — стороны канонического направления, а не «главная» и
    «второстепенная». Кто из двух задач просил связь, здесь не хранится: это свойство
    запроса, а не связи, и обе стороны равноправны при чтении.

    Внешние ключи без `ondelete`: задачи не удаляются — как и у записей дела. Если это
    однажды случится, база откажет, и связи не исчезнут молча вместе с делом, в котором
    про них написано.
    """

    __tablename__ = "links"
    __table_args__ = (
        # Дубликат ловится именно здесь и только благодаря канонизации: без неё
        # «A blocks B» и «B blocked_by A» были бы двумя разными тройками.
        UniqueConstraint("source_id", "target_id", "kind"),
        CheckConstraint("source_id <> target_id", name="no_self_link"),
        CheckConstraint(f"kind IN ({_STORED_KINDS_SQL})", name="stored_link_kind"),
        # Связи задачи читаются с обеих сторон (`source = ? OR target = ?`), поэтому
        # индексов два. Вид в них вторым: «дети этой задачи» — это
        # `source = ? AND kind = 'parent'`, и тем же запросом идёт шаг проверки цикла.
        Index("ix_links_source_id_kind", "source_id", "kind"),
        Index("ix_links_target_id_kind", "target_id", "kind"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    kind: Mapped[LinkKind] = mapped_column(
        string_enum(LinkKind, name="link_kind", length=16),
        nullable=False,
    )

    # `foreign_keys` обязателен у обеих связей: путей внешних ключей между связью и
    # задачей два, и выбрать между ними SQLAlchemy не может.
    #
    # `selectin`, а не `joined`: обе стороны нужны **всегда** — карточка показывает
    # статус задачи на другой стороне, — а два внешних соединения на строку связи, у
    # каждой из которых своё соединение с очередью, дали бы декартово произведение
    # там, где хватает одного запроса на уровень.
    source: Mapped[Task] = relationship(lazy="selectin", foreign_keys=[source_id])
    target: Mapped[Task] = relationship(lazy="selectin", foreign_keys=[target_id])

    def seen_from(self, task_id: uuid.UUID) -> tuple[LinkKind, Task]:
        """Как связь называется со стороны этой задачи и кто на другой стороне.

        Одним методом, а не двумя: обе половины ответа выводятся из одного и того же
        сравнения, и разнесённые по разным методам они однажды разошлись бы — вид
        посчитали бы со стороны источника, а задачу взяли бы со стороны цели.

        Ошибка, а не `None`, если задача к связи не относится: такой вызов означает,
        что связь взяли не у той задачи, и тихий ответ увёл бы отладку в сборку ответа.
        """
        if task_id == self.source_id:
            return visible_kind(self.kind, from_source=True), self.target
        if task_id == self.target_id:
            return visible_kind(self.kind, from_source=False), self.source
        raise ValueError(f"Task {task_id} is not a side of link {self.id}")
