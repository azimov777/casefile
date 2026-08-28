"""Выборки и изменения по комментариям задачи.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Удалённые комментарии из выдачи не исключаются: удаление мягкое, и плашка «комментарий
удалён» остаётся частью ленты (`app/db/models/comment.py`). Фильтр по `deleted_at`
здесь означал бы дыру в обсуждении и разъехавшуюся нумерацию страниц.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.comment import Comment
from app.db.pagination import Page, paginate


class CommentRepository:
    """Доступ к таблице `comments`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, comment_id: uuid.UUID) -> Comment | None:
        statement = select(Comment).where(Comment.id == comment_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_for_issue_page(
        self,
        issue_id: uuid.UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Comment]:
        """Страница ленты задачи, от старого к новому.

        Порядок хронологический, как у истории изменений: обсуждение читают сверху
        вниз, и курсорная пагинация проекта идёт ровно по этой паре `(created_at, id)`.
        """
        statement = select(Comment).where(Comment.issue_id == issue_id)
        return await paginate(self._session, statement, Comment, limit=limit, cursor=cursor)

    async def add(self, comment: Comment) -> Comment:
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def flush(self) -> None:
        """Фиксирует изменения объекта в базе, не закрывая транзакцию.

        Нужен сценариям правки и удаления: событие обязано нести состояние **после**
        изменения, включая `updated_at`, который проставляет база.
        """
        await self._session.flush()
