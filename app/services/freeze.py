"""Заморозка: единственное место, где возникают отказы архива проекта и области и отказ
закрытого обсуждения.

Архивный проект заморожен целиком вместе с задачами и областями (TRK#101, TRK#57): ни новой
задачи, ни записи в дело проекта, его задач или областей, ни перехода, ни правки, ни атрибута, ни
новой связи. Архивная область заморожена так же, но только сама: карточка, атрибуты и дело.
Правило одно, и проверка у него одна — `ensure_unfrozen`.
Россыпь проверок по сценариям пропустила бы следующее новое действие молча: забытая
строка в сценарии не видна ни тестом, ни чтением.

Архив проекта называется раньше архива области: восстановить область в архивном
проекте всё равно нельзя, и агент, получивший `area_archived`, чинил бы не то.

Закрытое обсуждение заморожено той же механикой (решение `TRK#51`, пункты 2 и 7):
его дело и привязки не меняются, и снова оно не открывается. Отказ — `discussion_closed`,
после архива проекта: в архивном проекте сначала нужен проект.

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
from app.db.models.area import Area
from app.db.models.discussion import Discussion
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import AreaRepository, DiscussionRepository, ProjectRepository
from app.domain.areas import format_area_address
from app.domain.case import EntryType
from app.domain.discussions import format_discussion_address
from app.domain.errors import AreaArchivedError, DiscussionClosedError, ProjectArchivedError

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
    areas: Iterable[Area] = (),
    discussions: Iterable[Discussion] = (),
) -> None:
    """Отказывает, если названный проект, проект задачи, области или обсуждения в архиве
    (`ProjectArchivedError`), затем — если названная область в архиве
    (`AreaArchivedError`), затем — если названное обсуждение закрыто
    (`DiscussionClosedError`).

    Звать под очередью изменений: архивирование, восстановление и закрытие тоже её
    занимают, и состояние, прочитанное под ней, не изменится до конца транзакции.
    """
    areas = tuple(areas)
    discussions = tuple(discussions)
    project_ids = (
        {task.project_id for task in tasks}
        | {project.id for project in projects}
        | {area.project_id for area in areas}
        | {discussion.project_id for discussion in discussions}
    )
    archived = await ProjectRepository(session).first_archived(project_ids)
    if archived is not None:
        key, archived_at = archived
        # Единственная точка возникновения отказа архива проекта в сценариях: `grep` по
        # его коду в `app/services` находит только строку `raise` ниже.
        refusal = ProjectArchivedError(details={"key": key, "archived_at": archived_at.isoformat()})
        raise refusal  # project_archived
    archived_area = await AreaRepository(session).first_archived({area.id for area in areas})
    if archived_area is not None:
        project_key, area_key, area_archived_at = archived_area
        # Так же единственная точка отказа архива области.
        raise AreaArchivedError(
            details={
                "key": format_area_address(project_key, area_key),
                "archived_at": area_archived_at.isoformat(),
            }
        )
    closed = await DiscussionRepository(session).first_closed(
        {discussion.id for discussion in discussions}
    )
    if closed is not None:
        # И единственная точка отказа закрытого обсуждения.
        raise DiscussionClosedError(details={"key": format_discussion_address(*closed)})


async def lock_unfrozen(
    session: AsyncSession,
    *tasks: Task,
    project: Project | None = None,
    area: Area | None = None,
    discussion: Discussion | None = None,
) -> None:
    """Очередь изменений и проверка заморозки — первым шагом мутирующего сценария.

    То же, что `lock_changes` (задачи перечитываются под очередью), и сразу после неё
    `ensure_unfrozen` по названным задачам, проекту, области и обсуждению.
    """
    await lock_changes(session, *tasks)
    await ensure_unfrozen(
        session,
        tasks=tasks,
        projects=() if project is None else (project,),
        areas=() if area is None else (area,),
        discussions=() if discussion is None else (discussion,),
    )
