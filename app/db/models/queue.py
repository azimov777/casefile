"""Очередь: единственный уровень группировки задач."""

from sqlalchemy import Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel
from app.db.models.author import CreatedByMixin


class Queue(BaseModel, CreatedByMixin):
    """Строка реестра очередей.

    Очередь отвечает на вопрос «про что задачи», а не «кто делает» (`CONCEPT.md`, 3.2).
    Описание — общий контекст всех её задач в markdown: где лежит код, на какие документы
    смотреть, чего не делать. Агент получает ключ и название в карточке задачи, а
    описание запрашивает отдельно, чтобы не тащить его в каждый ответ.

    Удаления нет, ключ неизменяем: ключ вшит в ключ каждой задачи очереди.
    """

    __tablename__ = "queues"

    # Ключ хранится канонизированным (верхний регистр) — как и имя участника, только в
    # другую сторону. Уникальность без учёта регистра держит обычное `UNIQUE`.
    key: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)

    # Счётчик выданных номеров, а не число задач: номер не переиспользуется, и удалённая
    # (в будущем — отменённая) задача свой номер с собой не уносит. Инкремент делает
    # база одним `UPDATE ... RETURNING` — см. `QueueRepository.allocate_task_number`.
    last_task_number: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
