"""Пункт чеклиста: лёгкая декомпозиция задачи без заведения подзадач.

У пункта нет ни статуса, ни процесса, ни собственной истории — только текст, отметка о
выполнении, место в списке и необязательные исполнитель с дедлайном. Всё, чему нужен
процесс, заводится подзадачей и связью `subtask_of`.

## Позиция разрежена, а не порядковая

Порядок задаёт целое число с шагом в тысячу с лишним между соседями
(`app/domain/checklists.py`). Перемещение пункта при этом меняет **одну** строку:
новая позиция вычисляется между соседями по месту вставки. Сплошная нумерация
означала бы переписывание всего списка на каждое перетаскивание карточки.

Уникальности позиции в схеме нет намеренно: перенумерация списка меняет позиции пачкой,
и уникальный индекс отверг бы промежуточное состояние внутри одного UPDATE. Порядок
вместо этого доопределён до устойчивого сортировкой по паре `(position, id)` — два
пункта с одинаковой позицией всё равно встают в один и тот же порядок в любом ответе.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.actor import Actor
from app.domain.checklists import MAX_CHECKLIST_TEXT_LENGTH


class ChecklistItem(BaseModel):
    """Пункт чеклиста задачи.

    `checked_by` и `checked_at` заполняются вместе с отметкой и снимаются вместе с
    ней: «кто отметил» без «когда» и наоборот — состояние, которого не бывает.
    Держать их одним сценарием, а не двумя присваиваниями по месту, обязательно.
    """

    __tablename__ = "checklist_items"
    __table_args__ = (
        # Единственный запрос выдачи: пункты одной задачи по порядку. Пара
        # `(position, id)` — тот самый устойчивый порядок из шапки модуля.
        Index("ix_checklist_items_issue_id_position_id", "issue_id", "position", "id"),
        # «Что назначено на меня» — запрос будущего инбокса (задача 14). Предыдущий
        # индекс начинается с задачи и на этот вопрос не отвечает.
        Index("ix_checklist_items_assignee_id", "assignee_id"),
    )

    # `ondelete="CASCADE"`: чеклист без задачи не значит ничего.
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(String(MAX_CHECKLIST_TEXT_LENGTH), nullable=False)

    # `BigInteger`, а не `Integer`: позиция не порядковый номер, а точка на разреженной
    # шкале — она растёт с каждым добавлением в конец и делится пополам при вставках
    # в середину. Потолка у неё нет, и упереться в него на длинной жизни задачи легче,
    # чем кажется.
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)

    is_done: Mapped[bool] = mapped_column(default=False, server_default=false(), nullable=False)
    # Без `ondelete`: акторов не удаляют, их отключают, — и отметка обязана остаться
    # читаемой вместе с именем того, кто её поставил.
    checked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("actors.id"),
        default=None,
        nullable=True,
    )
    checked_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)

    # Исполнитель и дедлайн пункта необязательны: чеклист чаще всего просто список
    # «что не забыть», и требовать их значило бы превратить его в подзадачи.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("actors.id"),
        default=None,
        nullable=True,
    )
    deadline: Mapped[datetime | None] = mapped_column(default=None, nullable=True)

    # `foreign_keys` обязателен у обеих связей на акторов: путей внешних ключей между
    # пунктом и актором два, и выбрать между ними SQLAlchemy не может.
    checked_by: Mapped[Actor | None] = relationship(
        lazy="selectin",
        foreign_keys=[checked_by_id],
    )
    assignee: Mapped[Actor | None] = relationship(lazy="selectin", foreign_keys=[assignee_id])
