"""Сценарии обсуждения: написать, изменить, мягко удалить, прочитать ленту.

## Одна лента на человека, агента и автоматику

Комментарий агента и комментарий человека — одна сущность, различаемая типом актора.
Отдельной «системной» записи для сообщений автоматики нет: она пишет тот же
комментарий от имени системного актора. Вторая сущность означала бы вторую ленту,
которую читателю пришлось бы склеивать на клиенте.

## Упоминания разбираются при сохранении

`@ключ_актора` вынимается из текста и складывается отдельным полем — на него подпишутся
уведомления (задача 14). В поле попадают только **существующие** акторы: упоминание
несуществующего ключа остаётся текстом, потому что поле адресатов должно означать
именно адресатов, а не всё, что похоже на упоминание. Актор, заведённый позже
комментария, в его адресаты задним числом не попадёт — это цена, и она названа прямо.

## Удаление мягкое

Текст затирается, `deleted_at` проставляется, строка остаётся. Дыра в обсуждении хуже
плашки: соседние реплики теряют контекст, а ушедшее уведомление начинает ссылаться в
никуда. Повторное удаление и правка удалённого отвергаются — иначе «удалил» перестало
бы что-либо значить.

Права здесь ровно те же, что во всём v1: любой активный актор может всё. Автор
комментария не выделен — когда появятся роли, ограничение встанет в
`app/services/permissions.py`, а не в этих сценариях.

Транзакцию сценарии не фиксируют: границу держит вход в приложение.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.comment import Comment
from app.db.models.issue import Issue
from app.db.pagination import Page
from app.db.repositories import ActorRepository, CommentRepository
from app.domain.comments import extract_mentions, validate_body
from app.domain.errors import CommentDeletedError, CommentNotFoundError
from app.services import events as events_service
from app.services.permissions import ensure_allowed


async def get_comment(session: AsyncSession, issue: Issue, comment_id: uuid.UUID) -> Comment:
    """Комментарий этой задачи по идентификатору или `comment_not_found`.

    Принадлежность проверяется здесь, а не в роутере: комментарий адресуется в пути
    своей задачей, и чужой комментарий для клиента то же самое, что несуществующий.
    Иначе по идентификатору можно было бы отредактировать реплику из задачи, о которой
    запрос ничего не знал.
    """
    comment = await CommentRepository(session).get_by_id(comment_id)
    if comment is None or comment.issue_id != issue.id:
        raise CommentNotFoundError(details={"comment": str(comment_id), "issue": issue.key})
    return comment


async def list_comments(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Comment]:
    """Страница ленты обсуждения, от старого к новому.

    Удалённые комментарии остаются в выдаче плашкой без текста: лента без них
    получила бы дыры, а страницы — разъехавшуюся нумерацию.
    """
    ensure_allowed(initiator, "issue.comments", target=issue)
    return await CommentRepository(session).list_for_issue_page(
        issue.id,
        limit=limit,
        cursor=cursor,
    )


async def add_comment(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    body: str,
    author: Actor | None = None,
) -> Comment:
    """Пишет комментарий к задаче.

    Автор по умолчанию — инициатор: у реплики, написанной агентом, автором должен быть
    агент, а не владелец установки. Явный `author` нужен автоматике, которая пишет от
    имени системного актора.
    """
    ensure_allowed(initiator, "comment.create", target=issue)
    stored_body = validate_body(body)
    mentions = await _known_mentions(session, stored_body)

    comment = Comment(
        issue_id=issue.id,
        author=author or initiator,
        body=stored_body,
        mentions=mentions,
    )
    await CommentRepository(session).add(comment)
    # Журнал задачи и событие — в той же транзакции, что и сам комментарий: откат
    # уносит всё разом, и подписчик не узнает о реплике, которой не появилось.
    await events_service.record_comment_created(
        session,
        comment,
        issue=issue,
        initiator=initiator,
    )
    return comment


async def update_comment(
    session: AsyncSession,
    comment: Comment,
    *,
    issue: Issue,
    initiator: Actor,
    body: str,
) -> Comment:
    """Меняет текст комментария и пересобирает упоминания.

    Упоминания разбираются заново целиком, а не дополняются: убранный из текста
    `@alice` обязан исчезнуть и из адресатов, иначе уведомления продолжали бы приходить
    по ссылке, которой в тексте уже нет.

    Правка, не меняющая текст, всё равно считается изменением? Нет: такой вызов не
    пишет ни журнала, ни события и не трогает `edited_at`. Иначе в ленте появлялась бы
    пометка «изменён» после сохранения без правок, а автоматика срабатывала бы на
    изменение, которого не было, — то же правило, что у единой точки изменения задачи.
    """
    ensure_allowed(initiator, "comment.update", target=comment)
    _ensure_not_deleted(comment)

    stored_body = validate_body(body)
    if stored_body == comment.body:
        return comment

    previous_body = comment.body
    previous_mentions = list(comment.mentions)

    comment.body = stored_body
    # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации внутри
    # значения, и UPDATE просто не уйдёт. Присваивается всегда новый список.
    comment.mentions = await _known_mentions(session, stored_body)
    comment.edited_at = datetime.now(UTC)
    await CommentRepository(session).flush()

    await events_service.record_comment_updated(
        session,
        comment,
        issue=issue,
        initiator=initiator,
        previous_body=previous_body,
        previous_mentions=previous_mentions,
    )
    return comment


async def delete_comment(
    session: AsyncSession,
    comment: Comment,
    *,
    issue: Issue,
    initiator: Actor,
) -> Comment:
    """Мягко удаляет комментарий: текст затирается, строка остаётся плашкой.

    Текст именно затирается, а не прячется в выдаче. «Удалил» обязано означать, что
    сказанного больше нет в базе, иначе первый же дамп покажет то, что автор считал
    удалённым.

    Упоминания снимаются вместе с текстом: удалённая реплика больше никого не
    адресует, и подписка на упоминания не должна за неё цепляться.
    """
    ensure_allowed(initiator, "comment.delete", target=comment)
    _ensure_not_deleted(comment)

    previous_body = comment.body
    previous_mentions = list(comment.mentions)

    comment.body = ""
    comment.mentions = []
    comment.deleted_at = datetime.now(UTC)
    await CommentRepository(session).flush()

    await events_service.record_comment_deleted(
        session,
        comment,
        issue=issue,
        initiator=initiator,
        previous_body=previous_body,
        previous_mentions=previous_mentions,
    )
    return comment


async def _known_mentions(session: AsyncSession, body: str) -> list[str]:
    """Упоминания из текста, оставленные только для существующих акторов.

    Один запрос на весь набор ключей, а не по запросу на упоминание: комментарий с
    десятком `@` — обычное дело в обсуждении релиза.
    """
    candidates = extract_mentions(body)
    if not candidates:
        return []
    known = await ActorRepository(session).existing_keys(set(candidates))
    return [key for key in candidates if key in known]


def _ensure_not_deleted(comment: Comment) -> None:
    """Правка и повторное удаление удалённого комментария — конфликт, а не тихий успех.

    Время в `details` строкой ISO 8601: подробности ошибки уезжают в JSON, и объект
    `datetime` там оказаться не может — это тот же формат, что в журнале и в событии.
    """
    deleted_at = comment.deleted_at
    if deleted_at is not None:
        raise CommentDeletedError(
            details={"comment": str(comment.id), "deleted_at": deleted_at.isoformat()},
        )
