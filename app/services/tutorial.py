"""Засев учебного проекта `START` (`TRK-370`).

Заводит проект и его задачи сценариями сервисов, как демо (`app/services/demo.py`):
`create_project`, `create_task`, `transition_task`. Автор всего заведённого — `tracker`
(`TRACKER_ACTOR`), как и у остального, что установка делает сама (`docs/CONCEPT.md`,
3.1) — засев не запрошен человеком, его делает первый подъём или его же команда.
Тексты и подстановки — задача об учебном сценарии (`app/domain/tutorial.py`, `TRK-366`);
здесь только то, что их заводит.

Два сценария, два условия «уже сделано» — как у `initialize_installation` и
`ensure_local_token` (`app/services/setup.py`):

- `seed_tutorial_on_boot` — шаг подъёма. Срабатывает только на установке без единого
  проекта, архивного тоже (`ProjectRepository.any_exists`): признак пустоты из
  `setup.py` — отсутствие токенов — здесь не годится, к этому шагу токены уже выпущены
  (`TRK-360#38`). Установка, обновлённая с прежней версии, уже не пуста, и этот вызов
  для неё не делает ничего — учебный проект ей заводит человек, второй командой.
- `create_tutorial_project` — команда человека. Признак — существование самого `START`:
  на непустой установке считать все проекты незачем, хватает ключа, который заводит
  этот же засев.

Оба зовут один и тот же `_seed`: разница только в условии, при котором он вызывается.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import AccountRepository, ProjectRepository
from app.domain.errors import TutorialAdminMissingError
from app.domain.projects import normalize_project_key
from app.domain.tasks import TaskStatus
from app.domain.tutorial import TUTORIAL_PROJECT_KEY, TutorialLanguage, render_tutorial_project
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.auth import TRACKER_ACTOR


@dataclass(frozen=True, slots=True)
class TutorialSeed:
    """Что засеяно этим вызовом. `None` в `project` значит «условие не выполнено»."""

    project: Project | None
    tasks: list[Task]

    @property
    def created(self) -> bool:
        return self.project is not None


_NOTHING = TutorialSeed(project=None, tasks=[])


async def seed_tutorial_on_boot(
    session: AsyncSession, *, language: TutorialLanguage = "en"
) -> TutorialSeed:
    """Заводит `START`, только когда в установке нет ни одного проекта.

    Это шаг подъёма (`docker compose run --rm tutorial` без флага): идёт на каждом
    подъёме, идемпотентен и молчит на установке, где уже есть хоть один проект — своей
    ли рукой заведённый, демонстрационный или сам `START`. Установка, у которой уже
    были проекты до этого шага (обновлённая с прежней версии), учебный проект получает
    только командой человека (`create_tutorial_project`).
    """
    if await ProjectRepository(session).any_exists():
        return _NOTHING
    return await _seed(session, language=language)


async def create_tutorial_project(
    session: AsyncSession, *, language: TutorialLanguage = "en"
) -> TutorialSeed:
    """Заводит `START`, если его ещё нет — команда человека на установке, где есть проекты.

    Признак — существование самого проекта `START`, а не общее число проектов: здесь их
    уже может быть много, и это не мешает завести учебный. Существующий `START` эта
    команда не трогает — ни задач, ни текста: тексты правит только задача об учебном
    сценарии (`TRK-366`), не засев.
    """
    if await ProjectRepository(session).get_by_key(normalize_project_key(TUTORIAL_PROJECT_KEY)):
        return _NOTHING
    return await _seed(session, language=language)


async def _seed(session: AsyncSession, *, language: TutorialLanguage) -> TutorialSeed:
    """Заводит проект `START` и его задачи, в `open`, без исполнителя.

    Имя человека в тексте задачи — участник с действующей учётной записью администратора
    (`AccountRepository.first_admin`): нет такого — отказ `tutorial_admin_missing`,
    а не текст с выдуманным именем. Адрес доски — настройка установки
    (`Settings.effective_ui_public_url`), не собранная из заголовков запроса. Транзакцию
    держит вход в приложение (`session_scope` команды): всё это — одна транзакция, и
    отказ на любом шаге не оставляет по себе ни проекта, ни задачи.
    """
    admin = await AccountRepository(session).first_admin()
    if admin is None:
        raise TutorialAdminMissingError()

    text = render_tutorial_project(
        language,
        board_url=get_settings().effective_ui_public_url,
        human_name=admin.participant.name,
    )

    project = await projects_service.create_project(
        session,
        actor=TRACKER_ACTOR,
        key=TUTORIAL_PROJECT_KEY,
        title=text.title,
        description=text.description,
    )

    tasks: list[Task] = []
    for task_text in text.tasks:
        task = await tasks_service.create_task(
            session,
            actor=TRACKER_ACTOR,
            project=project,
            title=task_text.title,
            description=task_text.description,
            goal=task_text.goal,
            context=task_text.context,
            constraints=task_text.constraints,
            output=task_text.output,
            checks=list(task_text.checks),
            # Исполнителя нет: задача заведена для агента, который его назовёт, взяв её
            # (`docs/CONCEPT.md`, 3.3).
            assignee=None,
        )
        await tasks_service.transition_task(session, task, actor=TRACKER_ACTOR, to=TaskStatus.OPEN)
        tasks.append(task)

    return TutorialSeed(project=project, tasks=tasks)
