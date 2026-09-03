"""Задачи: создание, пакет преемника, частичное обновление, переход, записи дела.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет, иначе
те же операции из MCP пошли бы другим путём и мимо служебных записей дела.

Маршрутов правки и удаления записей нет и не будет: записи дела неизменяемы, и это
стережёт тест по схеме OpenAPI.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep, TaskKeyPath
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.entries import (
    EntryCreate,
    EntryHeadingRead,
    EntryRead,
    entry_read,
)
from app.api.schemas.tasks import (
    TaskCreate,
    TaskFeaturesRead,
    TaskPackageRead,
    TaskRead,
    TaskTransition,
    TaskUpdate,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.case import EntryType
from app.services import case as case_service
from app.services import queues as queues_service
from app.services import tasks as service
from app.services.tasks import TaskChanges

router = APIRouter(prefix="/tasks", tags=["tasks"])

EntryNoPath = Annotated[
    int,
    Path(ge=1, description="Entry number inside the task, from 1", examples=[12]),
]

# Фильтры чтения дела. Объявлены псевдонимами, а не по месту: те же три фильтра
# принимает инструмент MCP `read_entries`, и разные описания у одного фильтра выглядели
# бы в сгенерированном клиенте как разные параметры.
EntryNosQuery = Annotated[
    list[int] | None,
    Query(description="Read only these entry numbers", examples=[[3, 12]]),
]
EntryTypesQuery = Annotated[
    list[EntryType] | None,
    Query(description="Read only entries of these types", examples=[["summary"]]),
]
AfterNoQuery = Annotated[
    int | None,
    Query(
        ge=1,
        description="Read only entries after this number — what happened since",
        examples=[12],
    ),
]


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
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.

    Карточка, вычисляемые признаки, последняя сводка целиком, открытые вопросы целиком,
    опись дела и переходы по таблице. Тела остальных записей читаются отдельно в
    `GET /tasks/{key}/entries`. Переходы перечислены по таблице; валидации (заполненные
    разделы, сводка, вердикты) проверяются в момент перехода, а не при чтении.
    """
    package = await service.read_task_package(session, task_key, actor=actor)
    key = package.task.key
    return DataResponse[TaskPackageRead](
        data=TaskPackageRead(
            task=TaskRead.model_validate(package.task),
            features=TaskFeaturesRead.model_validate(package.features, from_attributes=True),
            # `entry_read` отдаёт вариант по типу записи, а сценарий гарантирует, что
            # сюда попали именно сводка и вопросы: сузить тип здесь нечем и незачем.
            summary=None if package.summary is None else entry_read(package.summary, task_key=key),
            questions=[entry_read(question, task_key=key) for question in package.questions],
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
    task_sections_incomplete`). Выход из `in_progress` требует сводки, подшитой после
    последнего входа в него (`409 summary_required`); `review → done` — положительного
    последнего вердикта по каждой проверке (`409 checks_not_passed`, проверки без него
    в `details.checks`). Переход подшивает `status_changed` с `from`, `to` и `reason`.
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


@router.post(
    "/{task_key}/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Append a case entry",
)
async def create_task_entry(
    task_key: TaskKeyPath,
    entry: EntryCreate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[EntryRead]:
    """Подшивает запись агента: сводку, решение, попытку, находку, артефакт, вопрос,
    ответ, вердикт или заметку.

    Форма нагрузки зависит от типа: тело запроса — размеченное по `type` объединение.
    Заголовок принимается только там, где его нечем вывести: у `summary` он равен
    первой строке `next_step`, у `answer` и `verdict` собирается из нагрузки.
    Служебные типы (`status_changed`, `created`, ...) подшивает сам трекер, и в запросе
    они не принимаются. Замечания к форме приходят разом в `422 entry_fields_invalid`,
    списком `details.fields`. Записи неизменяемы, а в закрытую задачу подшиваются.
    """
    task = await service.get_task(session, task_key)
    # Все поля уезжают в сценарий как есть: разбирать объединение по ветвям здесь
    # значило бы держать в роутере знание о том, у какого типа какая нагрузка, — а оно
    # уже выражено доменом и схемой.
    given = entry.model_dump(mode="json")
    appended = await case_service.append_entry(
        session,
        task,
        actor=actor,
        type=given["type"],
        title=given.get("title"),
        body=given.get("body", ""),
        payload=given.get("payload"),
        refs=given.get("refs", []),
    )
    return DataResponse[EntryRead](data=entry_read(appended, task_key=task.key))


@router.get("/{task_key}/entries", summary="Read case entries")
async def list_task_entries(
    task_key: TaskKeyPath,
    session: SessionDep,
    actor: ActorDep,
    nos: EntryNosQuery = None,
    types: EntryTypesQuery = None,
    after_no: AfterNoQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[EntryRead]:
    """Записи дела с телами и нагрузкой, в порядке `no`.

    Фильтры сужают выборку вместе: `types=summary` даёт все сводки дела, `after_no`
    — всё, что случилось после названной записи, и вместе они отвечают на вопрос «что
    произошло после последней сводки». `after_no` и `cursor` не спорят: первый задаёт
    клиент, второй продолжает страницу, действуют оба. Записи неизменяемы: маршрутов
    правки и удаления нет.
    """
    task = await service.get_task(session, task_key)
    page = await case_service.list_entries(
        session,
        task,
        actor=actor,
        nos=nos,
        types=types,
        after_no=after_no,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[EntryRead].of(
        [entry_read(entry, task_key=task.key) for entry in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{task_key}/entries/{entry_no}", summary="Read one case entry")
async def read_task_entry(
    task_key: TaskKeyPath,
    entry_no: EntryNoPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[EntryRead]:
    """Одна запись по номеру внутри задачи — адрес из ссылки `TRK-42#12`.

    Номера, которого в задаче нет, — `404 entry_not_found`: номера выдаются без дыр,
    поэтому промах означает ссылку на чужое дело, а не пропущенную страницу.
    """
    task = await service.get_task(session, task_key)
    entry = await case_service.read_entry(session, task, entry_no, actor=actor)
    return DataResponse[EntryRead](data=entry_read(entry, task_key=task.key))
