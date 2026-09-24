"""Сценарии по проектам: создание, правка, чтение и выдача номеров."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.project import Project
from app.domain.errors import InvalidProjectKeyError, ProjectKeyTakenError, ProjectNotFoundError
from app.services import projects as service
from app.services.auth import Actor


async def test_creation_canonicalises_the_key_and_records_the_author(
    db_session: AsyncSession,
    main_actor: Actor,
) -> None:
    project = await service.create_project(
        db_session, actor=main_actor, key="ops", title="  Эксплуатация  ", description="Контекст"
    )

    assert project.key == "OPS"
    assert project.title == "Эксплуатация"
    assert project.last_task_number == 0
    assert project.created_by.signature == "owner"


async def test_a_key_differing_only_in_case_is_taken(
    db_session: AsyncSession,
    main_actor: Actor,
    project: Project,
) -> None:
    with pytest.raises(ProjectKeyTakenError) as error:
        await service.create_project(db_session, actor=main_actor, key="trk", title="Дубль")

    assert error.value.details["key"] == "TRK"


async def test_a_malformed_key_is_rejected(db_session: AsyncSession, main_actor: Actor) -> None:
    with pytest.raises(InvalidProjectKeyError):
        await service.create_project(db_session, actor=main_actor, key="TRK-1", title="Дефис")


async def test_creation_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
) -> None:
    """Обзорная проверка 2 на уровне сценария."""
    with pytest.raises(PermissionDeniedError) as error:
        await service.create_project(db_session, actor=task_actor, key="OPS", title="Эксплуатация")

    assert error.value.details["action"] == "project.create"
    assert error.value.status_code == 403


async def test_reading_is_open_to_the_task_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Агент читает описание проекта — это общий контекст всех его задач."""
    read = await service.read_project(db_session, "trk", actor=task_actor)
    page = await service.list_projects(db_session, actor=task_actor)

    assert read.id == project.id
    assert [item.key for item in page.items] == ["TRK"]


async def test_an_unknown_key_is_not_found(db_session: AsyncSession, task_actor: Actor) -> None:
    with pytest.raises(ProjectNotFoundError) as error:
        await service.read_project(db_session, "GHOST", actor=task_actor)

    assert error.value.code == "project_not_found"


async def test_update_changes_title_and_description_but_never_the_key(
    db_session: AsyncSession,
    main_actor: Actor,
    project: Project,
) -> None:
    updated = await service.update_project(
        db_session, project, actor=main_actor, description="Новый контекст"
    )

    assert updated.description == "Новый контекст"
    assert updated.title == "Трекер"
    assert updated.key == "TRK"


async def test_update_requires_the_main_scope(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    with pytest.raises(PermissionDeniedError):
        await service.update_project(db_session, project, actor=task_actor, title="Нельзя")


# --- Номера задач ------------------------------------------------------------------


async def test_numbers_are_handed_out_in_order(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Набор `task`: номер берут при создании задачи, то есть в рабочем цикле агента."""
    numbers = [
        await service.next_task_number(db_session, project, actor=task_actor) for _ in range(3)
    ]

    assert numbers == [1, 2, 3]


async def test_the_loaded_project_sees_its_own_increment(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Иначе ответ, собранный из объекта в том же запросе, показал бы счётчик до выдачи.

    Массовый `UPDATE` не синхронизирует загруженный объект сам — за этим следит
    `ProjectRepository.allocate_task_number`.
    """
    await service.next_task_number(db_session, project, actor=task_actor)

    assert project.last_task_number == 1


async def test_numbers_are_independent_between_projects(
    db_session: AsyncSession,
    main_actor: Actor,
    task_actor: Actor,
    project: Project,
) -> None:
    other = await service.create_project(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация"
    )

    first = await service.next_task_number(db_session, project, actor=task_actor)
    second = await service.next_task_number(db_session, other, actor=task_actor)

    assert (first, second) == (1, 1)
