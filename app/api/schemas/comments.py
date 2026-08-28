"""Схемы комментариев.

Автор приезжает ключом актора, а не вложенной записью: полные записи отдаёт список
акторов, и дублировать их в каждой реплике значило бы рассылать одно и то же
несколькими способами. По типу актора клиент отличает комментарий агента от
комментария человека — сущность у них одна.

У удалённого комментария `body` равен `null`, а не пустой строке: «текста нет» и
«текст пустой» — разные состояния, и пустая строка сделала бы плашку неотличимой от
реплики, которую кто-то умудрился сохранить пустой.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.comment import Comment
from app.domain.comments import MAX_COMMENT_LENGTH

BodyField = Field(
    min_length=1,
    max_length=MAX_COMMENT_LENGTH,
    examples=["Починил выдачу ключей, осталось прогнать тесты. @alice посмотришь?"],
    description=(
        "Markdown text. Mentions written as `@actor_key` are parsed on save and returned "
        "in `mentions`; notifications are subscribed to them"
    ),
)
MentionsDescription = (
    "Keys of the actors mentioned in the text, in order of appearance. Only existing "
    "actors get here: `@nobody` stays plain text"
)


class CommentRead(BaseModel):
    """Комментарий в ответе."""

    id: uuid.UUID
    issue: str = Field(examples=["TRK-123"], description="Key of the issue being discussed")
    author: str = Field(examples=["alice"], description="Key of the actor who wrote it")
    body: str | None = Field(
        default=None,
        examples=["Починил выдачу ключей"],
        description="Text of the comment; null once the comment is deleted",
    )
    mentions: list[str] = Field(
        default_factory=list,
        examples=[["alice", "release_bot"]],
        description=MentionsDescription,
    )
    is_deleted: bool = Field(
        description=(
            "Deletion is soft: the comment stays in the feed as a placeholder without "
            "text, so the discussion keeps its shape"
        )
    )
    created_at: datetime
    edited_at: datetime | None = Field(
        default=None,
        description="Set when the text was edited; deletion does not count as an edit",
    )

    @classmethod
    def of(cls, comment: Comment, *, issue_key: str) -> CommentRead:
        """Ключ задачи передаётся, а не читается из связи.

        Связь `comment.issue` объявлена `lazy="raise"`: комментарий всегда читается
        через свою задачу, и она у вызывающего кода уже загружена. Обращение к связи
        стоило бы запроса на каждую страницу ленты ради данных, которые уже есть.
        """
        return cls(
            id=comment.id,
            issue=issue_key,
            author=comment.author.key,
            body=None if comment.is_deleted else comment.body,
            mentions=list(comment.mentions),
            is_deleted=comment.is_deleted,
            created_at=comment.created_at,
            edited_at=comment.edited_at,
        )


class CommentCreate(BaseModel):
    """Новый комментарий.

    Ответить на другую реплику отдельным полем нельзя, и это решение: цепочек ответов
    в проекте нет. Ответ выражается цитатой в Markdown и упоминанием того, кому
    отвечают, — так лента остаётся плоской и читается сверху вниз.
    """

    model_config = ConfigDict(extra="forbid")

    body: str = BodyField


class CommentUpdate(BaseModel):
    """Правка комментария: текст заменяется целиком.

    Частичного обновления здесь нет — у комментария одно изменяемое поле. Упоминания
    пересобираются из нового текста, поэтому убранный `@alice` перестаёт быть
    адресатом.
    """

    model_config = ConfigDict(extra="forbid")

    body: str = BodyField
