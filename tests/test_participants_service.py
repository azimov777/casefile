"""Сценарии по участникам: успех и основные отказы."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.participant import Participant
from app.domain.authors import AuthorKind
from app.domain.errors import (
    InvalidParticipantNameError,
    ParticipantNameTakenError,
    ParticipantNotFoundError,
)
from app.domain.participants import ParticipantKind
from app.services import participants as service
from app.services.auth import TRACKER_ACTOR, Actor


async def test_registration_canonicalises_the_name_and_records_the_author(
    db_session: AsyncSession,
    main_actor: Actor,
) -> None:
    participant = await service.register_participant(
        db_session,
        actor=main_actor,
        kind=ParticipantKind.AGENT,
        name="Release_Bot",
        description="  Релизный бот  ",
    )

    assert participant.name == "release_bot"
    assert participant.description == "Релизный бот"
    assert participant.created_by.kind is AuthorKind.HUMAN
    assert participant.created_by.signature == "owner"


async def test_a_name_differing_only_in_case_is_taken(
    db_session: AsyncSession,
    main_actor: Actor,
    owner: Participant,
) -> None:
    """Обзорная проверка 1: это конфликт имени, а не разговор о форме строки."""
    with pytest.raises(ParticipantNameTakenError) as error:
        await service.register_participant(
            db_session,
            actor=main_actor,
            kind=ParticipantKind.HUMAN,
            name="Owner",
        )

    assert error.value.status_code == 409
    assert error.value.details["name"] == owner.name


async def test_a_malformed_name_does_not_reach_the_database(
    db_session: AsyncSession,
    main_actor: Actor,
) -> None:
    with pytest.raises(InvalidParticipantNameError):
        await service.register_participant(
            db_session,
            actor=main_actor,
            kind=ParticipantKind.HUMAN,
            name="release-bot",
        )


async def test_registration_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
) -> None:
    with pytest.raises(PermissionDeniedError) as error:
        await service.register_participant(
            db_session,
            actor=task_actor,
            kind=ParticipantKind.AGENT,
            name="release_bot",
        )

    assert error.value.details == {
        "action": "participant.register",
        "scope": "task",
        "required_scope": "main",
    }


async def test_reading_and_listing_are_open_to_the_task_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    owner: Participant,
) -> None:
    """Рабочему циклу реестр нужен: без него агенту некому адресовать вопрос."""
    read = await service.read_participant(db_session, "OWNER", actor=task_actor)
    page = await service.list_participants(db_session, actor=task_actor)

    assert read.id == owner.id
    assert [participant.name for participant in page.items] == ["owner"]


async def test_an_unknown_name_is_not_found(db_session: AsyncSession, task_actor: Actor) -> None:
    with pytest.raises(ParticipantNotFoundError) as error:
        await service.read_participant(db_session, "ghost", actor=task_actor)

    assert error.value.code == "participant_not_found"


async def test_update_changes_the_description_only(
    db_session: AsyncSession,
    main_actor: Actor,
    owner: Participant,
) -> None:
    """Имя и род править нечем: сценарий их не принимает, а схема отвергает лишнее поле."""
    updated = await service.update_participant(
        db_session, owner, actor=main_actor, description="Читает вопросы по вечерам"
    )

    assert updated.description == "Читает вопросы по вечерам"
    assert updated.name == "owner"
    assert updated.kind is ParticipantKind.HUMAN


async def test_update_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    owner: Participant,
) -> None:
    with pytest.raises(PermissionDeniedError):
        await service.update_participant(db_session, owner, actor=task_actor, description="нет")


async def test_the_tracker_can_register_the_first_participant(db_session: AsyncSession) -> None:
    """На пустой установке участника заводит трекер: другого автора не существует."""
    participant = await service.register_participant(
        db_session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.HUMAN,
        name="first",
    )

    assert participant.created_by.kind is AuthorKind.TRACKER
    assert participant.created_by.signature is None
