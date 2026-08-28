"""Сценарии обсуждения: лента, упоминания, правка, мягкое удаление, события.

Главное здесь — то, ради чего удаление сделано мягким: реплика исчезает из обсуждения,
но не оставляет в нём дыры. И то, ради чего упоминания разбираются при сохранении:
адресаты лежат отдельным полем, а не вычисляются заново на каждой доставке.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.comment import Comment
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.issue import Issue
from app.db.repositories import OutboxRepository
from app.domain.actors import ActorType
from app.domain.comments import COMMENTS_CHANGE_FIELD
from app.domain.errors import CommentDeletedError, CommentNotFoundError, InvalidCommentBodyError
from app.domain.events import EventType, ObjectType
from app.services import actors as actors_service
from app.services import comments as service

MakeIssue = Callable[..., Awaitable[Issue]]


async def _history(session: AsyncSession, issue: Issue) -> list[ChangelogEntry]:
    statement = (
        select(ChangelogEntry)
        .where(ChangelogEntry.issue_id == issue.id)
        .order_by(ChangelogEntry.created_at, ChangelogEntry.id)
    )
    return list((await session.scalars(statement)).all())


async def _comment_events(session: AsyncSession, comment: Comment) -> list[OutboxEvent]:
    return await OutboxRepository(session).list_by_object(
        object_type=ObjectType.COMMENT.value,
        object_id=comment.id,
    )


# --- Лента ------------------------------------------------------------------------


async def test_a_comment_lands_in_the_feed_with_its_author(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    comment = await service.add_comment(
        db_session,
        issue,
        initiator=owner,
        body="  Починил выдачу ключей  ",
    )

    page = await service.list_comments(db_session, issue, initiator=owner)
    assert [item.id for item in page.items] == [comment.id]
    assert comment.body == "Починил выдачу ключей"
    assert comment.author.key == "owner"
    assert comment.edited_at is None
    assert not comment.is_deleted


async def test_an_automation_comment_is_the_same_entity_as_a_human_one(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
    system_actor: Actor,
) -> None:
    """Автоматика пишет в ту же ленту от имени системного актора.

    Отдельной сущности для служебных сообщений нет: различает их тип актора, и лента
    остаётся одна — читателю не приходится склеивать две.
    """
    issue = await make_issue()

    await service.add_comment(db_session, issue, initiator=owner, body="Человек")
    robotic = await service.add_comment(
        db_session,
        issue,
        initiator=system_actor,
        body="Правило перевело задачу в работу",
        author=system_actor,
    )

    page = await service.list_comments(db_session, issue, initiator=owner)
    assert [item.author.key for item in page.items] == ["owner", "system"]
    assert robotic.author.type is ActorType.SYSTEM


async def test_an_empty_comment_is_refused(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()

    with pytest.raises(InvalidCommentBodyError):
        await service.add_comment(db_session, issue, initiator=owner, body="   ")


async def test_a_comment_of_another_issue_is_invisible(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Чужая реплика неотличима от несуществующей: адресуется она своей задачей."""
    discussed = await make_issue(summary="Первая")
    other = await make_issue(summary="Вторая")
    comment = await service.add_comment(db_session, discussed, initiator=owner, body="Реплика")

    with pytest.raises(CommentNotFoundError):
        await service.get_comment(db_session, other, comment.id)


# --- Упоминания -------------------------------------------------------------------


async def test_mentions_are_parsed_on_save_and_keep_only_existing_actors(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """В поле адресатов попадают только существующие акторы.

    `@nobody` остаётся текстом: поле упоминаний означает «кому это адресовано», и
    несуществующий ключ адресатом быть не может.
    """
    issue = await make_issue()
    await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="release_bot",
        display_name="Release bot",
    )

    comment = await service.add_comment(
        db_session,
        issue,
        initiator=owner,
        body="@release_bot собери сборку, @nobody тут ни при чём",
    )

    assert comment.mentions == ["release_bot"]


async def test_editing_recomputes_the_mentions(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Убранный из текста `@owner` перестаёт быть адресатом.

    Иначе уведомления продолжали бы приходить по ссылке, которой в тексте уже нет.
    """
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="@owner глянь")
    assert comment.mentions == ["owner"]

    await service.update_comment(
        db_session,
        comment,
        issue=issue,
        initiator=owner,
        body="уже не нужно",
    )

    assert comment.mentions == []


# --- Правка -----------------------------------------------------------------------


async def test_an_edit_marks_the_comment_and_writes_one_history_entry(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="Было")

    await service.update_comment(
        db_session,
        comment,
        issue=issue,
        initiator=owner,
        body="Стало",
    )

    assert comment.body == "Стало"
    assert comment.edited_at is not None
    events = [entry.event_type for entry in await _history(db_session, issue)]
    assert events == [
        EventType.ISSUE_CREATED.value,
        EventType.COMMENT_CREATED.value,
        EventType.COMMENT_UPDATED.value,
    ]


async def test_an_edit_with_the_same_text_changes_nothing(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Правка без правки не ставит пометку «изменён» и не порождает события.

    То же правило, что в единой точке изменения задачи: событие на изменение, которого
    не было, заставило бы автоматику сработать впустую.
    """
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="Текст")

    await service.update_comment(
        db_session,
        comment,
        issue=issue,
        initiator=owner,
        body="  Текст  ",
    )

    assert comment.edited_at is None
    assert len(await _comment_events(db_session, comment)) == 1


async def test_anyone_can_edit_a_comment_in_this_version(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """В v1 ролей нет: правит любой активный актор, не только автор.

    Проверка стоит здесь, чтобы ограничение появилось осознанно — в единой точке
    проверки прав, а не расползлось по сценариям.
    """
    issue = await make_issue()
    agent, _ = await actors_service.ensure_actor(
        db_session,
        actor_type=ActorType.AGENT,
        key="helper_bot",
        display_name="Helper",
    )
    comment = await service.add_comment(db_session, issue, initiator=owner, body="Мой текст")

    await service.update_comment(
        db_session,
        comment,
        issue=issue,
        initiator=agent,
        body="Правка агента",
    )

    assert comment.body == "Правка агента"


# --- Мягкое удаление --------------------------------------------------------------


async def test_deletion_keeps_the_row_and_wipes_the_text(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Реплика остаётся в ленте плашкой, а сказанное исчезает из базы.

    Скрыть текст только в выдаче было бы обманом: «удалил» обязано означать, что
    сказанного больше нет, — иначе первый же дамп это опровергнет.
    """
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="@owner неверно")

    await service.delete_comment(db_session, comment, issue=issue, initiator=owner)

    assert comment.is_deleted
    assert comment.body == ""
    assert comment.mentions == []
    page = await service.list_comments(db_session, issue, initiator=owner)
    # Плашка на месте: лента без неё получила бы дыру, а страницы — сдвиг.
    assert [item.id for item in page.items] == [comment.id]


async def test_a_deleted_comment_cannot_be_edited_or_deleted_again(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="Текст")
    await service.delete_comment(db_session, comment, issue=issue, initiator=owner)

    with pytest.raises(CommentDeletedError):
        await service.update_comment(
            db_session, comment, issue=issue, initiator=owner, body="Возврат"
        )
    with pytest.raises(CommentDeletedError):
        await service.delete_comment(db_session, comment, issue=issue, initiator=owner)


# --- События ----------------------------------------------------------------------


async def test_every_change_publishes_one_event_with_the_full_text(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Событие несёт текст целиком, а прежний — отдельным полем.

    Подписчику этого хватает: пока событие лежит в очереди, реплику успевают
    отредактировать ещё раз, и поход в базу вернул бы не то состояние.
    """
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="Первый текст")
    await service.update_comment(
        db_session, comment, issue=issue, initiator=owner, body="Второй текст"
    )

    events = await _comment_events(db_session, comment)
    assert [event.event_type for event in events] == [
        EventType.COMMENT_CREATED.value,
        EventType.COMMENT_UPDATED.value,
    ]
    created, updated = events
    assert created.object_key == f"{issue.key}:{comment.id}"
    assert created.payload["comment"]["body"] == "Первый текст"
    assert created.payload["previous"] is None
    assert updated.payload["comment"]["body"] == "Второй текст"
    assert updated.payload["previous"]["body"] == "Первый текст"
    # Снимок задачи в нагрузке — по общему правилу: подписчику не нужно идти в базу.
    assert updated.payload["issue"]["key"] == issue.key


async def test_the_history_entry_carries_an_excerpt_not_the_whole_text(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """В журнал задачи идёт отрывок: история читается страницами и должна быть лёгкой."""
    issue = await make_issue()
    long_body = "текст комментария " * 30
    comment = await service.add_comment(db_session, issue, initiator=owner, body=long_body)

    entry = (await _history(db_session, issue))[-1]
    change = entry.changes[0]
    assert change["field"] == COMMENTS_CHANGE_FIELD
    assert change["before"] is None
    assert change["after"]["comment"] == str(comment.id)
    assert len(change["after"]["excerpt"]) < len(long_body)
    assert change["after"]["excerpt"].endswith("…")


async def test_deletion_shows_up_in_history_as_a_disappearance(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """«Стало» пусто: текста в обсуждении больше нет, и это то самое изменение."""
    issue = await make_issue()
    comment = await service.add_comment(db_session, issue, initiator=owner, body="Текст")
    await service.delete_comment(db_session, comment, issue=issue, initiator=owner)

    entry = (await _history(db_session, issue))[-1]
    assert entry.event_type == EventType.COMMENT_DELETED.value
    assert entry.changes[0]["before"]["comment"] == str(comment.id)
    assert entry.changes[0]["after"] is None


async def test_deleting_an_issue_takes_its_discussion_with_it(
    db_session: AsyncSession,
    make_issue: MakeIssue,
    owner: Actor,
) -> None:
    """Каскад по задаче уносит комментарии молча, без события на каждый.

    Подписчику достаточно `issue.deleted` — так же, как со связями. Ожидание
    `comment.deleted` на каждую реплику оставило бы его ни с чем.
    """
    from app.services import issues as issues_service

    issue = await make_issue()
    await service.add_comment(db_session, issue, initiator=owner, body="Реплика")

    await issues_service.delete_issue(db_session, issue, initiator=owner)
    await db_session.flush()

    remaining = await db_session.scalars(select(Comment).where(Comment.issue_id == issue.id))
    assert list(remaining) == []
