"""Автор строки: две колонки и одно свойство, общие для всех реестров.

Структура автора (`app/domain/authors.py`) хранится развёрнутой в две колонки, а не в
JSONB: по подписи ищут («что делал этот агент»), а поиск по полю JSONB требует своего
индекса и своего синтаксиса ради двух строковых значений.

Примесь, а не таблица: автор — это свойство строки, а не сущность. Отдельная таблица
авторов означала бы либо строку на каждое действие временного агента, либо реестр,
дублирующий участников, — то есть ровно ту вторую форму идентичности, от которой
концепция уходит.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import string_enum
from app.domain.authors import Author, AuthorKind


class CreatedByMixin:
    """Кто завёл строку. Заполняется один раз при создании и не меняется.

    Хранится именно автор, а не ссылка на участника: временный агент участником не
    является, и внешний ключ на реестр обнулился бы ровно там, где подпись нужна больше
    всего. У автора рода `tracker` подпись пуста — это единственный законный `NULL`
    в паре колонок, и инвариант держит конструктор `Author`.
    """

    created_by_kind: Mapped[AuthorKind] = mapped_column(
        string_enum(AuthorKind, name="author_kind", length=16),
        nullable=False,
    )
    created_by_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @property
    def created_by(self) -> Author:
        """Автор строки одной структурой — той же, что приезжает из аутентификации."""
        return Author(kind=self.created_by_kind, signature=self.created_by_signature)


def created_by_columns(author: Author) -> dict[str, object]:
    """Значения колонок автора для конструктора модели.

    Функция, а не присваивание по месту: пар колонок в проекте будет столько же, сколько
    таблиц с автором, и разложенная руками структура однажды разложится наполовину —
    род запишется, подпись нет, и запись окажется анонимной.
    """
    return {"created_by_kind": author.kind, "created_by_signature": author.signature}
