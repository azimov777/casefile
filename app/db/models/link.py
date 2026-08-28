"""Связь между двумя задачами: одна строка на связь, видимая с обеих сторон.

Направление приведено к каноническому виду до вставки (`app/domain/links.py`), поэтому
в колонке `link_type` встречаются только «прямые» типы, а обратная сторона вычисляется
при чтении. Хранить обе стороны двумя строками нельзя: удаление одной из них оставило
бы вторую висеть, и задача осталась бы заблокирована задачей, которая её не блокирует.

## Что стережёт база, а что сценарий

Базе достаются те инварианты, которые выражаются одной строкой или одним индексом:
нет связи задачи с самой собой, нет двух одинаковых связей, у задачи не больше одного
родителя, в `link_type` не попадает обратный тип. Всё это — вторая линия обороны;
первую держит `app/services/links.py`, и именно он отдаёт клиенту понятный код ошибки.

Отсутствие циклов базой не проверяется и проверено быть не может: это свойство графа
целиком, а не строки. Оно живёт в сценарии, и цена этого названа в `docs/notes/links.md`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.domain.links import HIERARCHY_STORED_TYPE, STORED_LINK_TYPES, LinkType

#: Литерал списка канонических типов для ограничения CHECK. Собирается из домена, а не
#: пишется руками: два независимых перечня разошлись бы при добавлении типа связи, и
#: база молча приняла бы то, чего код не умеет читать.
_STORED_TYPES_SQL = ", ".join(f"'{link_type.value}'" for link_type in sorted(STORED_LINK_TYPES))


class IssueLink(BaseModel):
    """Связь: исходная задача, целевая задача, тип, автор и время.

    `source` и `target` — стороны в каноническом направлении, а не «главная» и
    «второстепенная». У `depends_on` источник зависит от цели, у `subtask_of` источник
    и есть подзадача. Кто из двух задач спрашивал связь, здесь не хранится: это
    свойство запроса, а не связи.

    Каскад по обоим ключам: связь без одной из задач бессмысленна. Обратная сторона
    каскада названа прямо — удаление задачи уносит её связи молча, без события
    `link.deleted` на каждую (`docs/notes/links.md`).
    """

    __tablename__ = "issue_links"
    __table_args__ = (
        # Дубликат ловится именно здесь и только благодаря канонизации: без неё
        # «A blocks B» и «B depends_on A» были бы двумя разными тройками.
        UniqueConstraint("source_id", "target_id", "link_type"),
        CheckConstraint("source_id <> target_id", name="no_self_link"),
        CheckConstraint(f"link_type IN ({_STORED_TYPES_SQL})", name="stored_link_type"),
        # «У задачи не более одного родителя»: у иерархической связи источник — это
        # ребёнок, поэтому уникальность источника среди иерархических строк и есть
        # искомое правило. Индекс частичный: на остальных типах повторный источник
        # законен — задача связана с несколькими другими.
        Index(
            "uq_issue_links_parent",
            "source_id",
            unique=True,
            postgresql_where=text(f"link_type = '{HIERARCHY_STORED_TYPE.value}'"),
        ),
        # Связи задачи читаются с обеих сторон одним запросом `source = ? OR target = ?`,
        # поэтому индексов два. Тип в них вторым: выборка «дети этой задачи» —
        # `target = ? AND link_type = 'subtask_of'` — и есть шаг построения дерева.
        Index("ix_issue_links_source_id_link_type", "source_id", "link_type"),
        Index("ix_issue_links_target_id_link_type", "target_id", "link_type"),
        # Курсорная пагинация проекта идёт по паре `(created_at, id)`.
        Index("ix_issue_links_created_at_id", "created_at", "id"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[LinkType] = mapped_column(
        string_enum(LinkType, name="issue_link_type", length=16),
        nullable=False,
    )
    # Без `ondelete`: акторов не удаляют, их отключают, — и связь обязана остаться
    # читаемой вместе с именем того, кто её завёл.
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    # `foreign_keys` обязателен у обеих связей: путей внешних ключей между связью и
    # задачей два, и выбрать между ними SQLAlchemy не может.
    source: Mapped[Issue] = relationship(lazy="selectin", foreign_keys=[source_id])
    target: Mapped[Issue] = relationship(lazy="selectin", foreign_keys=[target_id])
    author: Mapped[Actor] = relationship(lazy="selectin")

    def other_side(self, issue_id: uuid.UUID) -> Issue:
        """Вторая задача связи. Ответ на вопрос «а с кем именно связана эта задача».

        Ошибка, а не `None`, если задача к связи не относится: такой вызов означает,
        что связь взяли не у той задачи, и тихий `None` увёл бы отладку в сборку ответа.
        """
        if issue_id == self.source_id:
            return self.target
        if issue_id == self.target_id:
            return self.source
        raise ValueError(f"Issue {issue_id} is not a side of link {self.id}")
