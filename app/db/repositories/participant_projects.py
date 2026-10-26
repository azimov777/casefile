"""Доступ участника-агента к проектам: режим и список (TRK-746).

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
Режим лежит на участнике, список — в `participant_projects`.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.participant_project import ParticipantProject
from app.domain.project_access import ProjectAccess, ProjectAccessMode


class ParticipantProjectRepository:
    """Доступ к `participants.project_access_mode` и таблице `participant_projects`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_access(self, participant: Participant) -> ProjectAccess:
        """Режим и список участника. В режиме `all` список пуст, даже если строки остались."""
        mode = participant.project_access_mode
        if mode is ProjectAccessMode.ALL:
            return ProjectAccess()
        ids = await self._session.scalars(
            select(ParticipantProject.project_id).where(
                ParticipantProject.participant_id == participant.id
            )
        )
        return ProjectAccess(mode=mode, project_ids=frozenset(ids))

    async def replace_access(
        self, participant: Participant, mode: ProjectAccessMode, project_ids: Iterable[uuid.UUID]
    ) -> ProjectAccess:
        """Заменяет режим и список целиком. В режиме `all` список очищается."""
        ids = frozenset() if mode is ProjectAccessMode.ALL else frozenset(project_ids)
        await self._session.execute(
            delete(ParticipantProject).where(ParticipantProject.participant_id == participant.id)
        )
        participant.project_access_mode = mode
        if ids:
            self._session.add_all(
                ParticipantProject(participant_id=participant.id, project_id=project_id)
                for project_id in ids
            )
        await self._session.flush()
        return ProjectAccess(mode=mode, project_ids=ids)

    async def add_project(self, participant_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """Кладёт проект в список; уже лежащий не дублируется (автодобавление своего проекта)."""
        await self._session.execute(
            insert(ParticipantProject)
            .values(participant_id=participant_id, project_id=project_id)
            .on_conflict_do_nothing(constraint="uq_participant_projects_participant_id_project_id")
        )
