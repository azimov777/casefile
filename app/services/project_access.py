"""Доступ участника-агента к проектам: чтение и настройка (TRK~28#6).

Режим и список лежат на участнике (`app/db/repositories/participant_projects.py`), сам
доступ вызова загружает `authenticate` (`app/services/auth.py`). Здесь — действие человека:
посмотреть и задать агенту режим `all` / `except` / `only` и список проектов.

Настраивает человек с учётной записью, которому доступен агент: свои агенты и агенты без
хозяина — любой такой человек, чужой агент — администратор (`agent_owned_by_another`).
Агент себе доступ не меняет (`account_required`): правило то же, что у выпуска ключа.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.repositories import ProjectRepository
from app.db.repositories.participant_projects import ParticipantProjectRepository
from app.domain.errors import ParticipantNotAgentError
from app.domain.participants import ParticipantKind
from app.domain.project_access import ProjectAccessMode, parse_project_access_mode
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services.auth import Actor
from app.services.tokens import ensure_may_manage_agent

ACTION = "participant.projects"


@dataclass(frozen=True, slots=True)
class AgentProjectAccess:
    """Режим доступа агента и проекты списка (в `all` список пуст), по ключу."""

    participant: Participant
    mode: ProjectAccessMode
    projects: list[Project]


async def read_project_access(
    session: AsyncSession, name: str, *, actor: Actor
) -> AgentProjectAccess:
    """Режим и список проектов агента; у человека ограничений нет - `all` и пустой список."""
    participant = await _managed(session, name, actor=actor)
    return await _view(session, participant)


async def set_project_access(
    session: AsyncSession,
    name: str,
    *,
    actor: Actor,
    mode: str,
    project_keys: Sequence[str],
) -> AgentProjectAccess:
    """Заменяет режим и список целиком. В режиме `all` список очищается.

    Порядок отказов: агент и право распоряжаться им, режим (`project_access_mode_invalid`),
    проекты (`project_not_found`; архивный проект принимается, как везде, TRK#99). Список
    дублей не хранит.
    """
    participant = await _managed(session, name, actor=actor)
    if participant.kind is not ParticipantKind.AGENT:
        raise ParticipantNotAgentError(
            details={"name": participant.name, "kind": participant.kind.value}
        )
    parsed = parse_project_access_mode(mode)
    projects = [await projects_service.get_project(session, key) for key in project_keys]
    repository = ParticipantProjectRepository(session)
    await repository.replace_access(participant, parsed, {project.id for project in projects})
    return await _view(session, participant)


async def _managed(session: AsyncSession, name: str, *, actor: Actor) -> Participant:
    participant = await participants_service.get_participant(session, name)
    await ensure_may_manage_agent(session, actor, participant, action=ACTION)
    return participant


async def _view(session: AsyncSession, participant: Participant) -> AgentProjectAccess:
    access = await ParticipantProjectRepository(session).get_access(participant)
    by_key = await ProjectRepository(session).list_by_ids(access.project_ids)
    return AgentProjectAccess(
        participant=participant,
        mode=access.mode,
        projects=sorted(by_key, key=lambda project: project.key),
    )
