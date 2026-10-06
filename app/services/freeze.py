"""Заморозка архива: единственное место, где возникают отказы архива проекта и направления.

Архивный проект заморожен целиком вместе с задачами и направлениями (`CONCEPT.md`, 3.2 и
3.7): ни новой задачи, ни записи в дело проекта, его задач или направлений, ни перехода,
ни правки, ни атрибута, ни новой связи. Архивное направление заморожено так же, но только
само: карточка, атрибуты и дело. Правило одно, и проверка у него одна — `ensure_unfrozen`.
Россыпь проверок по сценариям пропустила бы следующее новое действие молча: забытая
строка в сценарии не видна ни тестом, ни чтением.

Архив проекта называется раньше архива направления: восстановить направление в архивном
проекте всё равно нельзя, и агент, получивший `direction_archived`, чинил бы не то.

## Две опоры, одна проверка

1. **Подшивка записи** (`app/services/case.py`, `_append`). Любое изменение состояния
   подшивает служебную запись в той же транзакции (`docs/CONVENTIONS.md`, «Журнал»), и
   все записи идут через `_append`. Проверка там — гарантия: изменение, дошедшее до
   записи в дело архивного проекта или его задачи, откатывается целиком, в каком бы
   сценарии его ни забыли проверить.
2. **Начало сценария** (`lock_unfrozen`). Сценарий, который до подшивки проверяет свои
   правила, иначе ответил бы чужим отказом: переход задачи с открытым блокером —
   `task_blocked`, правка раздела вне `backlog` — `task_field_locked`, — и агент чинил бы
   не то. `lock_unfrozen` занимает очередь изменений и тут же спрашивает ту же
   `ensure_unfrozen`: архив называется первым. Создание задачи к тому же берёт номер
   до подшивки и проверку обязано сделать раньше него.

Обе опоры зовут одну функцию, поэтому правило и текст отказа не расходятся.

## Исключения

Записи, которые архив пропускает, названы в `UNFROZEN_ENTRY_TYPES` — одним словарём
рядом с проверкой, а не условием в сценарии:

- `archived` — подшивается в момент архивирования, `restored` — в момент восстановления
  архивного: без них сами действия были бы невозможны;
- `link_removed` — снятие связи с задачей архивного проекта (`TRK-164#9`, вариант C):
  незакрытая архивная задача держит блокер или родителя в живом проекте, и связь можно
  снять, не восстанавливая проект. Сценарий `unlink` поэтому занимает очередь без
  проверки (`app/services/links.py`), а `link_removed` ложится и в дело замороженной
  задачи.

Чтение не проверяется вовсе: архив читается как обычно.
"""

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.direction import Direction
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import DirectionRepository, ProjectRepository
from app.domain.case import EntryType
from app.domain.directions import format_direction_address
from app.domain.errors import DirectionArchivedError, ProjectArchivedError

#: Записи, которые ложатся в дело архивного проекта и его задач: сами действия архива и
#: снятие связи. Всё остальное архив отклоняет.
UNFROZEN_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {EntryType.ARCHIVED, EntryType.RESTORED, EntryType.LINK_REMOVED}
)


async def ensure_unfrozen(
    session: AsyncSession,
    *,
    tasks: Iterable[Task] = (),
    projects: Iterable[Project] = (),
    directions: Iterable[Direction] = (),
) -> None:
    """Отказывает, если названный проект, проект задачи или направления в архиве
    (`ProjectArchivedError`), а затем — если названное направление в архиве
    (`DirectionArchivedError`).

    Звать под очередью изменений: архивирование и восстановление тоже её занимают, и
    состояние, прочитанное под ней, не изменится до конца транзакции.
    """
    directions = tuple(directions)
    project_ids = (
        {task.project_id for task in tasks}
        | {project.id for project in projects}
        | {direction.project_id for direction in directions}
    )
    archived = await ProjectRepository(session).first_archived(project_ids)
    if archived is not None:
        key, archived_at = archived
        # Единственная точка возникновения отказа архива проекта в сценариях: `grep` по
        # его коду в `app/services` находит только строку `raise` ниже.
        refusal = ProjectArchivedError(details={"key": key, "archived_at": archived_at.isoformat()})
        raise refusal  # project_archived
    archived_direction = await DirectionRepository(session).first_archived(
        {direction.id for direction in directions}
    )
    if archived_direction is not None:
        project_key, direction_key, direction_archived_at = archived_direction
        # Так же единственная точка отказа архива направления.
        raise DirectionArchivedError(
            details={
                "key": format_direction_address(project_key, direction_key),
                "archived_at": direction_archived_at.isoformat(),
            }
        )


async def lock_unfrozen(
    session: AsyncSession,
    *tasks: Task,
    project: Project | None = None,
    direction: Direction | None = None,
) -> None:
    """Очередь изменений и проверка заморозки — первым шагом мутирующего сценария.

    То же, что `lock_changes` (задачи перечитываются под очередью), и сразу после неё
    `ensure_unfrozen` по названным задачам, проекту и направлению.
    """
    await lock_changes(session, *tasks)
    await ensure_unfrozen(
        session,
        tasks=tasks,
        projects=() if project is None else (project,),
        directions=() if direction is None else (direction,),
    )
