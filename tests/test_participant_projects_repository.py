"""Репозиторий доступа к проектам: режим по умолчанию, замена списка, ограничения (TRK-746)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.participant_project import ParticipantProject
from app.db.models.project import Project
from app.db.repositories.participant_projects import ParticipantProjectRepository
from app.domain.participants import ParticipantKind
from app.domain.project_access import ProjectAccess, ProjectAccessMode
from app.services import participants as participants_service
from app.services.auth import TRACKER_ACTOR


async def make_projects(session: AsyncSession, owner: Participant) -> list[Project]:
    projects = [
        Project(
            key=key,
            title=key,
            created_by_kind=owner.author.kind,
            created_by_signature=owner.author.signature,
        )
        for key in ("PAA", "PAB", "PAC")
    ]
    session.add_all(projects)
    await session.flush()
    return projects


async def make_agent(session: AsyncSession) -> Participant:
    return await participants_service.register_participant(
        session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="scoped"
    )


async def test_a_new_participant_has_the_all_mode_and_an_empty_list(
    db_session: AsyncSession, owner: Participant
) -> None:
    agent = await make_agent(db_session)
    assert agent.project_access_mode is ProjectAccessMode.ALL
    assert await ParticipantProjectRepository(db_session).get_access(agent) == ProjectAccess()


async def test_replace_swaps_the_mode_and_the_whole_list(
    db_session: AsyncSession, owner: Participant
) -> None:
    projects = await make_projects(db_session, owner)
    first, second, third = (project.id for project in projects)
    agent = await make_agent(db_session)
    repo = ParticipantProjectRepository(db_session)

    await repo.replace_access(agent, ProjectAccessMode.ONLY, [first, second])
    await db_session.refresh(agent)
    access = await repo.get_access(agent)
    assert (access.mode, access.project_ids) == (
        ProjectAccessMode.ONLY,
        frozenset({first, second}),
    )

    await repo.replace_access(agent, ProjectAccessMode.EXCEPT, [third])
    await db_session.refresh(agent)
    access = await repo.get_access(agent)
    assert (access.mode, access.project_ids) == (ProjectAccessMode.EXCEPT, frozenset({third}))

    await repo.replace_access(agent, ProjectAccessMode.ALL, [first])
    await db_session.refresh(agent)
    assert await repo.get_access(agent) == ProjectAccess()
    assert await db_session.scalar(text("SELECT count(*) FROM participant_projects")) == 0


async def test_add_project_is_idempotent(db_session: AsyncSession, owner: Participant) -> None:
    projects = await make_projects(db_session, owner)
    first, second = projects[0].id, projects[1].id
    agent = await make_agent(db_session)
    repo = ParticipantProjectRepository(db_session)
    await repo.replace_access(agent, ProjectAccessMode.ONLY, [first])

    await repo.add_project(agent.id, second)
    await repo.add_project(agent.id, second)
    await db_session.refresh(agent)
    assert (await repo.get_access(agent)).project_ids == frozenset({first, second})


async def test_the_database_refuses_a_second_pair_and_a_foreign_mode(
    db_session: AsyncSession, owner: Participant
) -> None:
    first, *_ = await make_projects(db_session, owner)
    agent = await make_agent(db_session)
    db_session.add(ParticipantProject(participant_id=agent.id, project_id=first.id))
    await db_session.flush()
    with pytest.raises(IntegrityError, match="uq_participant_projects_participant_id_project_id"):
        async with db_session.begin_nested():
            db_session.add(ParticipantProject(participant_id=agent.id, project_id=first.id))
            await db_session.flush()
    with pytest.raises(IntegrityError, match="ck_participants_project_access_mode"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE participants SET project_access_mode = 'some' WHERE id = :id"),
                {"id": agent.id},
            )
