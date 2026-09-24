"""Сценарии по проектам.

Карточка проекта меняется со служебной записью в его деле (`CONCEPT.md`, 3.4, «Дело
проекта»): заведение подшивает `created`, правка названия и описания — `field_changed`
на каждое изменённое поле. Изменение, не оставившее записи, не доходит до ленты (4.1).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.author import created_by_columns
from app.db.models.project import Project
from app.db.pagination import Page
from app.db.repositories import ProjectRepository
from app.domain.errors import ProjectKeyTakenError, ProjectNotFoundError
from app.domain.projects import normalize_project_key, validate_project_key
from app.domain.tasks import TaskField
from app.domain.tokens import TokenScope
from app.services import case as case_service
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
    """Заводит проект. Ключ канонизируется и дальше неизменяем.

    Первая страница дела нового проекта — `created`, в той же транзакции.

    Очередь изменений (`lock_changes`) здесь берёт подшивка `created`, то есть **после**
    вставки строки, а не первым делом, как в остальных мутирующих сценариях. Фактов,
    которые надо читать под очередью, у заведения нет: занятость ключа решает уникальный
    индекс, а проверка `get_by_key` — лишь ранний доменный отказ. Взятая первой, очередь
    сериализовала бы две гонящихся попытки до проверки, и второй всегда доставался бы
    `project_key_taken`; гонку, которую разводит индекс и переводит в `conflict` граница
    транзакции, стережёт `tests/test_integrity_conflicts.py`, и её поведение не меняется.
    """
    ensure_scope(actor, TokenScope.MAIN, action="project.create")

    canonical = validate_project_key(key)
    repository = ProjectRepository(session)
    if await repository.get_by_key(canonical) is not None:
        raise ProjectKeyTakenError(details={"key": canonical})

    project = await repository.add(
        Project(
            key=canonical,
            title=title.strip(),
            description=description.strip(),
            **created_by_columns(actor.author),
        )
    )
    await case_service.record_project_created(session, project, actor=actor)
    return project


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

    Каждое изменённое поле подшивает `field_changed` с прежним и новым значением; все
    записи одного вызова делят `action_id`. Присланное значение, равное нынешнему, записи
    не оставляет: правки не было.
    """
    ensure_scope(actor, TokenScope.MAIN, action="project.update")
    await lock_changes(session)
    # Под очередью изменений перечитать: проект разрешён из ключа до неё, и «было» в
    # записи иначе могло бы оказаться чужим устаревшим снимком.
    await session.refresh(project)

    changes = {
        TaskField.TITLE: None if title is None else title.strip(),
        TaskField.DESCRIPTION: None if description is None else description.strip(),
    }
    action_id = uuid.uuid4()
    for field, after in changes.items():
        before: str = getattr(project, field.value)
        if after is None or after == before:
            continue
        setattr(project, field.value, after)
        await case_service.record_project_field_changed(
            session,
            project,
            actor=actor,
            field=field,
            before=before,
            after=after,
            action_id=action_id,
        )
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
