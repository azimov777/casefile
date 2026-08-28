"""Схемы связей между задачами и дерева иерархии.

Тип связи в ответе — тот, которым она называется **со стороны запрошенной задачи**:
у одной стороны `depends_on`, у другой `blocks`. Хранится связь один раз, поэтому
второе имя вычисляется, а не лежит в базе (`app/domain/links.py`).

Вторая сторона приезжает полной записью задачи, а не одним ключом. Это отступление от
общего правила «связанные объекты — ссылками», и оно сознательное: карточка задачи
показывает связи вместе с названием, статусом и исполнителем, и ссылкой на ключ фронт
получил бы список, ради отрисовки которого нужно ещё десять запросов. Форма при этом
та же самая, `IssueRead`, — второго представления задачи в проекте не появляется.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.issues import IssueRead
from app.domain.links import DEFAULT_TREE_DEPTH, MAX_TREE_DEPTH, LinkType
from app.services.links import IssueLinkView, IssueTreeNode

LinkTypeDescription = (
    "How the requested issue relates to the other one. Every type has an opposite side "
    "(`depends_on` ↔ `blocks`), and the same link is reported under the matching name "
    "when read from the other issue"
)


class IssueLinkRead(BaseModel):
    """Связь в ответе, названная со стороны запрошенной задачи."""

    id: uuid.UUID
    type: LinkType = Field(examples=[LinkType.DEPENDS_ON], description=LinkTypeDescription)
    issue: IssueRead = Field(description="The issue on the other side of the link")
    author: str = Field(examples=["alice"], description="Key of the actor who created the link")
    created_at: datetime

    @classmethod
    def of(cls, view: IssueLinkView) -> IssueLinkRead:
        return cls(
            id=view.link.id,
            type=view.link_type,
            issue=IssueRead.of(view.issue),
            author=view.link.author.key,
            created_at=view.link.created_at,
        )


class IssueLinkCreate(BaseModel):
    """Заведение связи: `<задача из пути> <type> <issue>`.

    Направление читается слева направо, как фраза: `{"type": "blocks", "issue": "TRK-2"}`
    у задачи `TRK-1` означает «TRK-1 блокирует TRK-2». В какую сторону связь ляжет в
    базу, клиента не касается — обратная сторона всё равно видна у второй задачи.
    """

    model_config = ConfigDict(extra="forbid")

    type: LinkType = Field(examples=[LinkType.BLOCKS], description=LinkTypeDescription)
    issue: str = Field(examples=["TRK-124"], description="Key of the issue to link with")


class IssueTreeNodeRead(BaseModel):
    """Узел дерева иерархии: задача и её подзадачи."""

    issue: IssueRead
    children: list[IssueTreeNodeRead] = Field(
        default_factory=list,
        description="Direct subtasks, in the order the links were created",
    )
    has_more_children: bool = Field(
        description=(
            "True when the node has subtasks that did not fit the requested depth or the "
            f"per-response node cap. Depth defaults to {DEFAULT_TREE_DEPTH} and cannot "
            f"exceed {MAX_TREE_DEPTH}"
        )
    )

    @classmethod
    def of(cls, node: IssueTreeNode) -> IssueTreeNodeRead:
        return cls(
            issue=IssueRead.of(node.issue),
            children=[cls.of(child) for child in node.children],
            has_more_children=node.has_more_children,
        )


IssueTreeNodeRead.model_rebuild()
