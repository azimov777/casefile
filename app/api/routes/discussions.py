"""Обсуждения: переписка человека и агентов по узкому вопросу (решение проекта `TRK#51`).

Ресурс верхнего уровня, как задачи: адрес `TRK~7` называет проект сам, тильда в сегменте
пути экранирования не требует, а входящая по обсуждениям идёт поперёк проектов.

Здесь только то, что вызывает интерфейс человека (решение проекта `TRK#53`): список
с отбором, экран обсуждения, его дело, заметка и ответ, «Новое обсуждение» запиской,
привязать и отвязать задачу. Вопрос, итог и закрытие подшивает агент — через MCP
(TRK-671): человек в интерфейсе обсуждение не закрывает (`TRK#51`, п. 7). Записи
неизменяемы: маршрутов правки и удаления записей нет.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.deps import (
    ActorDep,
    AfterNoQuery,
    CursorQuery,
    EntryNosQuery,
    EntryTypesQuery,
    LimitQuery,
    SessionDep,
    TaskKeyPath,
)
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.discussions import (
    DiscussionCreate,
    DiscussionDetailRead,
    DiscussionRead,
    DiscussionTaskAttach,
    DiscussionTaskRead,
    discussion_detail_read,
    discussion_read,
    discussion_task_read,
)
from app.api.schemas.entries import DiscussionEntryCreate, EntryRead, entry_read
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.case import EntryType
from app.domain.discussions import DiscussionOrder, DiscussionStatus, DiscussionTurn
from app.services import case as case_service
from app.services import discussions as service
from app.services import projects as projects_service
from app.services import tasks as tasks_service

router = APIRouter(prefix="/discussions", tags=["discussions"])

DiscussionPath = Annotated[
    str,
    Path(
        description="Discussion address `PROJECT~number`; matching ignores case",
        examples=["TRK~7"],
    ),
]
DiscussionProjectQuery = Annotated[
    str | None,
    Query(
        description=(
            "Project key; matching ignores case. Without it discussions of archived "
            "projects are left out; a project named here is listed even archived"
        ),
        examples=["TRK"],
    ),
]
DiscussionStatusQuery = Annotated[
    DiscussionStatus | None,
    Query(description="Keep only open or only closed discussions"),
]
DiscussionTurnQuery = Annotated[
    DiscussionTurn | None,
    Query(
        description=(
            "Keep only discussions where the move is a human's (`human`: a question has no "
            "answer) or an agent's (`agent`); the inbox is `status=open&turn=human`"
        )
    ),
]
DiscussionTaskQuery = Annotated[
    str | None,
    Query(
        description=(
            "Key of a task: keep only discussions it is attached to; matching ignores case. "
            "A previous key of a moved task names it as well"
        ),
        examples=["TRK-42"],
    ),
]
DiscussionOrderQuery = Annotated[
    DiscussionOrder,
    Query(
        description=(
            "`oldest` (the default) puts the earliest discussion first, as an inbox needs; "
            "`newest` the latest first, as a history needs. A cursor only continues the "
            "order it was issued in"
        )
    ),
]


@router.get("", summary="List discussions")
async def list_discussions(
    session: SessionDep,
    actor: ActorDep,
    project: DiscussionProjectQuery = None,
    status: DiscussionStatusQuery = None,
    turn: DiscussionTurnQuery = None,
    task: DiscussionTaskQuery = None,
    order: DiscussionOrderQuery = DiscussionOrder.OLDEST,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[DiscussionRead]:
    """Обсуждения с отбором: входящая — `status=open&turn=human`, история — без отбора с
    `order=newest`, обсуждения задачи — `task`.

    У каждого — чей ход и число открытых вопросов, посчитанные при чтении. Неизвестный
    проект — `404 project_not_found`, неизвестная задача — `404 task_not_found`: пустая
    выдача на такой отбор читалась бы как ответ.
    """
    page = await service.list_discussions(
        session,
        actor=actor,
        project=None if project is None else await projects_service.get_project(session, project),
        status=status,
        turn=turn,
        task=None if task is None else await tasks_service.get_task(session, task),
        order=order,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[DiscussionRead].of(
        [discussion_read(row) for row in page.items], next_cursor=page.next_cursor
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a discussion")
async def create_discussion(
    payload: DiscussionCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[DiscussionDetailRead]:
    """Заводит обсуждение запиской и привязывает задачи из `tasks` тем же действием.

    Название — сам узкий вопрос; оно же заголовок первой записи дела, заметки с телом
    `body`. Номер выдаётся внутри проекта, адрес — `TRK~7`. В деле обсуждения ложатся
    `created`, заметка и `attached` на каждую задачу, в деле задачи — свой `attached`.
    Отказы: архивный проект — `409 project_archived`, закрытая задача — `409 task_closed`,
    название не одной строкой — `422 entry_fields_invalid`. Повтор с тем же
    `Idempotency-Key` отвечает первым обсуждением, а не заводит второе.
    """
    project = await projects_service.get_project(session, payload.project)
    tasks = [await tasks_service.get_task(session, key) for key in payload.tasks]

    async def create() -> DataResponse[DiscussionDetailRead]:
        discussion = await service.create_discussion(
            session,
            actor=actor,
            project=project,
            title=payload.title,
            opening=EntryType.NOTE,
            body=payload.body,
            refs=payload.refs,
            tasks=tasks,
        )
        detail = await service.read_discussion(session, discussion, actor=actor)
        return DataResponse[DiscussionDetailRead](data=discussion_detail_read(detail))

    return await once.run(
        DataResponse[DiscussionDetailRead],
        request={
            "project": project.key,
            "tasks": [task.key for task in tasks],
            "discussion": payload.model_dump(mode="json", exclude={"project", "tasks"}),
        },
        build=create,
    )


@router.get("/{discussion}", summary="Read a discussion")
async def read_discussion(
    discussion: DiscussionPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[DiscussionDetailRead]:
    """Экран обсуждения: карточка, чей ход, открытые вопросы, привязанные задачи и
    последний итог. Лента записей — `/discussions/{discussion}/entries`.

    Адрес не по форме — `422 invalid_discussion_address`, неизвестный проект —
    `404 project_not_found`, номер — `404 discussion_not_found`.
    """
    found = await service.get_discussion(session, discussion)
    detail = await service.read_discussion(session, found, actor=actor)
    return DataResponse[DiscussionDetailRead](data=discussion_detail_read(detail))


@router.get("/{discussion}/entries", summary="Read discussion case entries")
async def list_discussion_entries(
    discussion: DiscussionPath,
    session: SessionDep,
    actor: ActorDep,
    nos: EntryNosQuery = None,
    types: EntryTypesQuery = None,
    after_no: AfterNoQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[EntryRead]:
    """Записи дела обсуждения с телами и нагрузкой, в порядке `no` — те же фильтры, что у
    дела задачи. Ссылка на запись — `TRK~7#3`."""
    found = await service.get_discussion(session, discussion)
    page = await case_service.list_discussion_entries(
        session,
        found,
        actor=actor,
        nos=nos,
        types=types,
        after_no=after_no,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[EntryRead].of(
        [entry_read(item, discussion=found.address) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/{discussion}/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Append a discussion case entry",
)
async def create_discussion_entry(
    discussion: DiscussionPath,
    entry: DiscussionEntryCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Подшивает в дело обсуждения заметку или ответ — формы «Заметка» и «Ответить на #N».

    Ответ ссылается на вопрос этого же обсуждения (`question_no`); первый ответ закрывает
    вопрос, и задачи, которые он держал, снова можно брать в работу. Закрытое обсуждение —
    `409 discussion_closed`; замечания к форме и ссылкам — разом в
    `422 entry_fields_invalid`. Повтор с тем же `Idempotency-Key` отвечает первой записью.
    """
    found = await service.get_discussion(session, discussion)
    given = entry.model_dump(mode="json")

    async def append() -> DataResponse[EntryRead]:
        appended = await case_service.append_discussion_entry(
            session,
            found,
            actor=actor,
            type=given["type"],
            title=given.get("title"),
            body=given.get("body", ""),
            payload=given.get("payload"),
            refs=given.get("refs", []),
        )
        return DataResponse[EntryRead](data=entry_read(appended, discussion=found.address))

    return await once.run(
        DataResponse[EntryRead],
        request={"discussion": found.address, "entry": given},
        build=append,
    )


@router.post(
    "/{discussion}/tasks",
    status_code=status.HTTP_201_CREATED,
    summary="Attach a task to a discussion",
)
async def attach_discussion_task(
    discussion: DiscussionPath,
    payload: DiscussionTaskAttach,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[DiscussionTaskRead]:
    """Привязывает задачу: она зависит от итога — не берётся в работу, пока в обсуждении
    есть вопрос без ответа, и не закрывается, пока оно открыто.

    `attached` ложится в дело обсуждения и в дело задачи. Отказы: закрытое обсуждение —
    `409 discussion_closed`, закрытая задача — `409 task_closed`, уже привязана —
    `409 discussion_task_exists`. Повтор с тем же `Idempotency-Key` отвечает первой
    привязкой.
    """
    found = await service.get_discussion(session, discussion)
    task = await tasks_service.get_task(session, payload.task)

    async def attach() -> DataResponse[DiscussionTaskRead]:
        attachment = await service.attach_task(session, found, task, actor=actor)
        return DataResponse[DiscussionTaskRead](data=discussion_task_read(attachment))

    return await once.run(
        DataResponse[DiscussionTaskRead],
        request={"discussion": found.address, "task": task.key},
        build=attach,
    )


@router.delete(
    "/{discussion}/tasks/{task_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a task from a discussion",
)
async def detach_discussion_task(
    discussion: DiscussionPath,
    task_key: TaskKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> None:
    """Отвязывает задачу: она больше не ждёт итога этого обсуждения. `detached` ложится в
    дела обеих сторон. Привязки нет — `404 discussion_task_not_found`; закрытое
    обсуждение — `409 discussion_closed`: у закрытого привязки не меняются."""
    found = await service.get_discussion(session, discussion)
    task = await tasks_service.get_task(session, task_key)
    await service.detach_task(session, found, task, actor=actor)
