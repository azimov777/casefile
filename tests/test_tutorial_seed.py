"""Засев учебного проекта `START` (`app/services/tutorial.py`, `TRK-370`).

Тексты сами по себе проверяет `tests/test_tutorial.py` (`TRK-366`) — здесь только
условие засева и то, что он делает со свежей и с непустой установкой: сценарии, а не
слог задачи.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.repositories import ProjectRepository
from app.domain.authors import AuthorKind
from app.domain.errors import TutorialAdminMissingError
from app.domain.projects import normalize_project_key
from app.domain.tasks import TaskStatus
from app.domain.tutorial import TUTORIAL_PROJECT_KEY
from app.services import projects as projects_service
from app.services.auth import Actor
from app.services.tutorial import create_tutorial_project, seed_tutorial_on_boot


async def test_the_boot_step_seeds_an_empty_installation(
    db_session: AsyncSession, owner: Participant
) -> None:
    """Обзорная проверка 2, первая половина: `START` и его задачи заводятся в `open`.

    Автор — `tracker` и без исполнителя: задача заведена для агента, который её возьмёт,
    а не для конкретного имени.
    """
    seed = await seed_tutorial_on_boot(db_session)

    assert seed.created
    assert seed.project is not None
    assert seed.project.key == TUTORIAL_PROJECT_KEY
    assert seed.project.created_by.kind is AuthorKind.TRACKER
    assert seed.project.created_by.signature is None

    assert seed.tasks, "учебный проект без единой задачи агенту нечего брать"
    for task in seed.tasks:
        assert task.status is TaskStatus.OPEN
        assert task.assignee is None
        assert task.created_by.kind is AuthorKind.TRACKER
        assert task.created_by.signature is None
        # Подстановки окружения заполнены, а не оставлены фигурными скобками.
        assert "{board_url}" not in task.context
        assert "{human_name}" not in task.context
        assert owner.name in task.context


async def test_the_boot_step_is_idempotent(db_session: AsyncSession, owner: Participant) -> None:
    """Обзорная проверка 2, вторая половина: повторный вызов не заводит ничего."""
    first = await seed_tutorial_on_boot(db_session)
    assert first.created

    second = await seed_tutorial_on_boot(db_session)

    assert not second.created
    assert second.project is None
    assert second.tasks == []


async def test_the_boot_step_refuses_without_an_administrator(db_session: AsyncSession) -> None:
    """Нет ни одного человека с учётной записью администратора — отказ, а не выдумка.

    Без фикстуры `owner` в базе нет ни одной учётной записи вовсе.
    """
    with pytest.raises(TutorialAdminMissingError):
        await seed_tutorial_on_boot(db_session)


async def test_the_boot_step_does_nothing_on_an_installation_with_a_project(
    db_session: AsyncSession, owner: Participant, main_actor: Actor
) -> None:
    """Обзорная проверка 3, первая половина: чужой проект уже делает установку непустой."""
    await projects_service.create_project(db_session, actor=main_actor, key="TRK", title="Трекер")

    seed = await seed_tutorial_on_boot(db_session)

    assert not seed.created
    key = normalize_project_key(TUTORIAL_PROJECT_KEY)
    assert await ProjectRepository(db_session).get_by_key(key) is None


async def test_the_boot_step_does_nothing_when_the_only_project_is_archived(
    db_session: AsyncSession, owner: Participant, main_actor: Actor
) -> None:
    """Обзорная проверка 3: архивный проект тоже считается — установка не пуста."""
    project = await projects_service.create_project(
        db_session, actor=main_actor, key="TRK", title="Трекер"
    )
    await projects_service.archive_project(
        db_session, project, actor=main_actor, reason="Проект больше не нужен"
    )

    seed = await seed_tutorial_on_boot(db_session)

    assert not seed.created


async def test_the_human_command_seeds_start_on_a_non_empty_installation(
    db_session: AsyncSession, owner: Participant, main_actor: Actor
) -> None:
    """Обзорная проверка 3, вторая половина: заводит `START` там, где `demo` не подошёл."""
    await projects_service.create_project(db_session, actor=main_actor, key="TRK", title="Трекер")

    seed = await create_tutorial_project(db_session)

    assert seed.created
    assert seed.project is not None
    assert seed.project.key == TUTORIAL_PROJECT_KEY


async def test_the_human_command_does_nothing_when_start_already_exists(
    db_session: AsyncSession, owner: Participant
) -> None:
    """Обзорная проверка 3: существующий `START` команда не трогает."""
    first = await create_tutorial_project(db_session)
    assert first.created

    second = await create_tutorial_project(db_session)

    assert not second.created
    assert second.project is None
