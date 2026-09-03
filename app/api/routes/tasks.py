"""Задачи: создание, пакет преемника, частичное обновление, переход, записи дела.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет, иначе
те же операции из MCP пошли бы другим путём и мимо служебных записей дела.

Маршрутов правки и удаления записей нет и не будет: записи дела неизменяемы, и это
стережёт тест по схеме OpenAPI.
"""

from fastapi import APIRouter, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep, TaskKeyPath
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.entries import EntryHeadingRead, EntryRead
from app.api.schemas.tasks import (
    TaskCreate,
    TaskPackageRead,
    TaskRead,
    TaskTransition,
    TaskUpdate,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import case as case_service
from app.services import queues as queues_service
from app.services import tasks as service
from app.services.tasks import TaskChanges

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a task")
async def create_task(
    payload: TaskCreate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskRead]:
    """Заводит задачу в `backlog`. Ключ выдаёт счётчик очереди, статус не принимается.

    В деле сразу появляется запись `created` с автором из токена. Разделы можно
    оставить пустыми и дописать в `backlog`; перед переходом в `open` четыре раздела
    должны быть заполнены, а `checks` — содержать хотя бы одну проверку.
    """
    queue = await queues_service.get_queue(session, payload.queue)
    task = await service.create_task(
        session,
        actor=actor,
        queue=queue,
        title=payload.title,
        description=payload.description,
        goal=payload.goal,
        context=payload.context,
        constraints=payload.constraints,
        output=payload.output,
        checks=payload.checks,
        assignee=payload.assignee,
        tags=payload.tags,
        priority=payload.priority,
    )
    return DataResponse[TaskRead](data=TaskRead.model_validate(task))


@router.get("/{task_key}", summary="Read a task")
async def read_task(
    task_key: TaskKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskPackageRead]:
    """Пакет преемника: карточка, доступные по таблице переходы и опись дела.

    Опись — заголовки всех записей без тел; тела читаются в `GET /tasks/{key}/entries`.
    Переходы перечислены по таблице; валидации (заполненные разделы, сводка, вердикты,
    блокеры) проверяются в момент перехода, а не при чтении.
    """
    package = await service.read_task_package(session, task_key, actor=actor)
    return DataResponse[TaskPackageRead](
        data=TaskPackageRead(
            task=TaskRead.model_validate(package.task),
            transitions=list(package.transitions),
            index=[EntryHeadingRead.model_validate(heading) for heading in package.index],
        )
    )


@router.patch("/{task_key}", summary="Update a task")
async def update_task(
    task_key: TaskKeyPath,
    payload: TaskUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskRead]:
    """Меняет только переданные поля.

    Название, описание и пять разделов — только в `backlog` (иначе `409
    task_field_locked`); исполнитель, теги и приоритет — в любом незакрытом статусе; в
    `done` и `cancelled` не меняется ничего (`409 task_closed`). Правка раздела
    подшивает `section_changed`, смена исполнителя — `assignee_changed`. `version` —
    не поле задачи, а условие: устаревшая версия отвечает `409 version_conflict`.
    """
    task = await service.get_task(session, task_key)
    # `exclude_unset` — единственный фильтр: у `assignee` явный `null` осмыслен и обязан
    # дожить до сценария, у остальных полей его уже отвергла схема.
    changes = payload.model_dump(exclude_unset=True)
    version = changes.pop("version", None)
    mutation = await service.update_task(
        session,
        task,
        actor=actor,
        changes=TaskChanges(**changes),
        expected_version=version,
    )
    return DataResponse[TaskRead](data=TaskRead.model_validate(mutation.task))


@router.post("/{task_key}/transition", summary="Move a task to another status")
async def transition_task(
    task_key: TaskKeyPath,
    payload: TaskTransition,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskRead]:
    """Переводит задачу по таблице переходов.

    Переход не из таблицы — `409 transition_not_allowed` с допустимыми целями в
    `details.allowed`. Шаг назад по цепочке и отмена требуют `reason` (`422
    transition_reason_required`); `backlog → open` требует заполненных разделов (`422
    task_sections_incomplete`, незаполненные — в `details.fields`). Переход подшивает
    `status_changed` с `from`, `to` и `reason`.
    """
    task = await service.get_task(session, task_key)
    mutation = await service.transition_task(
        session,
        task,
        actor=actor,
        to=payload.to,
        reason=payload.reason,
        expected_version=payload.version,
    )
    return DataResponse[TaskRead](data=TaskRead.model_validate(mutation.task))


@router.get("/{task_key}/entries", summary="Read case entries")
async def list_task_entries(
    task_key: TaskKeyPath,
    session: SessionDep,
    actor: ActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[EntryRead]:
    """Записи дела с телами и нагрузкой, в порядке `no`.

    Записи неизменяемы: маршрутов правки и удаления нет. Фильтры по номерам, типам и
    «после номера» добавляет задача 23.
    """
    task = await service.get_task(session, task_key)
    page = await case_service.list_entries(session, task, actor=actor, limit=limit, cursor=cursor)
    return CollectionResponse[EntryRead].of(
        [EntryRead.of(entry, task_key=task.key) for entry in page.items],
        next_cursor=page.next_cursor,
    )
