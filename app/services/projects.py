"""Сценарии по проектам."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.project import Project
from app.db.pagination import Page
from app.db.repositories import ProjectRepository
from app.domain.errors import ProjectKeyTakenError, ProjectNotFoundError
from app.domain.projects import normalize_project_key, validate_project_key
from app.domain.tokens import TokenScope
from app.services.auth import Actor
from app.services.permissions import ensure_scope


async def get_project(session: AsyncSession, key: str) -> Project:
    """Проект по ключу или `project_not_found`. Адресация мягкая: `trk` находит `TRK`."""
    project = await ProjectRepository(session).get_by_key(normalize_project_key(key))
    if project is None:
        raise ProjectNotFoundError(details={"key": key})
    return project


async def read_project(session: AsyncSession, key: str, *, actor: Actor) -> Project:
    """Карточка проекта с описанием — общим контекстом всех его задач."""
    ensure_scope(actor, TokenScope.TASK, action="project.read")
    return await get_project(session, key)


async def list_projects(
    session: AsyncSession,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Project]:
    ensure_scope(actor, TokenScope.TASK, action="project.list")
    return await ProjectRepository(session).list_page(limit=limit, cursor=cursor)


async def create_project(
    session: AsyncSession,
    *,
    actor: Actor,
    key: str,
    title: str,
    description: str = "",
) -> Project:
    """Заводит проект. Ключ канонизируется и дальше неизменяем."""
    ensure_scope(actor, TokenScope.MAIN, action="project.create")

    canonical = validate_project_key(key)
    repository = ProjectRepository(session)
    if await repository.get_by_key(canonical) is not None:
        raise ProjectKeyTakenError(details={"key": canonical})

    return await repository.add(
        Project(
            key=canonical,
            title=title.strip(),
            description=description.strip(),
            **created_by_columns(actor.author),
        )
    )


async def update_project(
    session: AsyncSession,
    project: Project,
    *,
    actor: Actor,
    title: str | None = None,
    description: str | None = None,
) -> Project:
    """Меняет название и описание. Ключ не меняется никогда.

    Ключ вшит в ключ каждой задачи проекта (`TRK-42`), и его правка задним числом
    порвала бы все уже записанные ссылки. В API поля `key` у частичного обновления нет
    вовсе — схема отвергает его как лишнее, а не молча игнорирует.

    `None` означает «поле не передано»: ни у названия, ни у описания нет осмысленного
    значения `null`, поэтому схема `ProjectUpdate` отвергает явный `null` сама.
    """
    ensure_scope(actor, TokenScope.MAIN, action="project.update")

    if title is not None:
        project.title = title.strip()
    if description is not None:
        project.description = description.strip()
    await session.flush()
    return project


async def next_task_number(session: AsyncSession, project: Project, *, actor: Actor) -> int:
    """Следующий номер задачи в проекте.

    Выдаётся атомарным `UPDATE ... RETURNING` (`ProjectRepository.allocate_task_number`):
    два параллельных создания задачи получают разные номера, но платят за это
    сериализацией до конца транзакции. Поэтому номер берут **последним**, после всех
    проверок: откатившаяся транзакция свой номер теряет навсегда.

    Набор `task`, а не `main`: номер берут при создании задачи, то есть в рабочем цикле
    агента.
    """
    ensure_scope(actor, TokenScope.TASK, action="project.allocate_task_number")
    return await ProjectRepository(session).allocate_task_number(project)
