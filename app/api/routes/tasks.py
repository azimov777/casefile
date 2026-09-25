"""Задачи: создание, пакет преемника, частичное обновление, переход, записи дела.

Роутер только переводит HTTP в вызов сценария и обратно: своей логики здесь нет, иначе
те же операции из MCP пошли бы другим путём и мимо служебных записей дела.

Маршрутов правки и удаления записей нет и не будет: записи дела неизменяемы, и это
стережёт тест по схеме OpenAPI.
"""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import (
    ActorDep,
    AfterNoQuery,
    CursorQuery,
    EntryNosQuery,
    EntryTypesQuery,
    LimitQuery,
    OffsetQuery,
    SessionDep,
    TaskKeyPath,
)
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.entries import (
    EntryCreate,
    EntryHeadingRead,
    EntryRead,
    entry_read,
)
from app.api.schemas.links import LinkTaskRead, TaskLinkRead
from app.api.schemas.search import (
    FieldsParam,
    QueryParam,
    SortParam,
    TaskFilterParams,
    TaskSearchRead,
    search_page,
)
from app.api.schemas.tasks import (
    TaskAlreadyThereRead,
    TaskClosing,
    TaskCreate,
    TaskFeaturesRead,
    TaskMove,
    TaskMoveBatch,
    TaskMoveBatchRead,
    TaskMovedRead,
    TaskMoveRefusedRead,
    TaskPackageRead,
    TaskRead,
    TaskTransition,
    TaskUpdate,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.tasks import CheckEdit
from app.services import case as case_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as service
from app.services.tasks import (
    TaskAlreadyThere,
    TaskChanges,
    TaskMoved,
    TaskMoveOutcome,
    TaskMoveRefused,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

EntryNoPath = Annotated[
    int,
    Path(ge=1, description="Entry number inside the task, from 1", examples=[12]),
]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a task")
async def create_task(
    payload: TaskCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[TaskRead]:
    """Заводит задачу в `backlog`. Ключ выдаёт счётчик проекта, статус не принимается.

    В деле сразу появляется запись `created` с автором из токена. Разделы можно
    оставить пустыми и дописать в `backlog`; перед переходом в `open` четыре раздела
    должны быть заполнены, а `checks` — содержать хотя бы одну проверку.

    Повтор с тем же `Idempotency-Key` и тем же телом отвечает первой задачей, а не
    заводит вторую: номер проекта на этом не тратится.
    """

    # Проект разрешается **до** занятия ключа: запрос, отклонённый до работы, не должен
    # тратить ключ. Он же уезжает в отпечаток разрешённым (`TRK`, а не `trk`) — адресация
    # в проекте мягкая, и иначе повтор тем же ключом отвечал бы конфликтом.
    project = await projects_service.get_project(session, payload.project)

    async def create() -> DataResponse[TaskRead]:
        task = await service.create_task(
            session,
            actor=actor,
            project=project,
            title=payload.title,
            description=payload.description,
            goal=payload.goal,
            context=payload.context,
            constraints=payload.constraints,
            output=payload.output,
            checks=payload.checks,
            assignee=payload.assignee,
            priority=payload.priority,
        )
        return DataResponse[TaskRead](data=TaskRead.model_validate(task))

    return await once.run(
        DataResponse[TaskRead],
        request={
            "project": project.key,
            "task": payload.model_dump(mode="json", exclude={"project"}),
        },
        build=create,
    )


@router.get("", summary="List and search tasks", response_model_exclude_unset=True)
async def list_tasks(
    session: SessionDep,
    actor: ActorDep,
    filters: TaskFilterParams,
    query: QueryParam = None,
    sort: SortParam = None,
    fields: FieldsParam = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
    offset: OffsetQuery = None,
) -> CollectionResponse[TaskSearchRead]:
    """Задачи по строке запроса, по структурному фильтру или по обоим сразу.

    Оба входа сводятся к одному отбору и на одинаковых условиях дают одинаковый
    результат в одинаковом порядке: `?query=project: TRK and status: open` и
    `?project=TRK&status=open` — это буквально один путь исполнения. Условия из разных
    источников складываются по `and`.

    Запрос без условий — законный: это «все задачи» по ключу, и отдельного способа
    сказать то же самое заводить незачем. Ошибка разбора приходит `422
    invalid_search_query` с позицией символа; незнакомое имя поля — `422
    search_field_unknown` со списком допустимых в `details.allowed`.

    Задачи архивного проекта в выдачу не попадают, пока отбор не назовёт их равенством
    или вхождением: проект условием `project`, саму задачу — `key`, её родителя —
    `parent` (`docs/CONCEPT.md`, 4.4). Поля «архивный» в языке нет.

    Отбирать можно и по вычисляемым признакам (`blocked`, `open_questions`,
    `open_blocking_questions`, `open_remarks`): колонок под них нет, они считаются из
    связей и дела прямо в запросе. Запрос кандидатов назначателя — одна строка:
    `project: TRK and status: open and blocked: false and open_blocking_questions: 0`.
    Есть и поле отбора без признака — `remarks_in_work`: «замечание приняли в работу, а
    названная задача ещё не закрыта».

    Те же признаки приходят **в каждой строке** объектом `features` — тем самым, что
    в пакете преемника: значок «заблокирована» и счётчик вопросов рисуются из списка,
    без запроса на каждую строку.

    `fields` оставляет в ответе только перечисленные поля плюс `key`: полная задача с
    пятью разделами съедает контекст агента, которому нужен столбец ключей. Признаки
    выбираются целиком именем `features`; отдельный признак именем поля выдачи не
    выбирается — `blocked` остаётся именем условия отбора.

    **Страницами.** `meta.total` — сколько задач нашлось по отбору, а не сколько их на
    странице: из него и `limit` собирается «страница 3 из 7, всего 98». Это
    единственная коллекция API, которая его считает, и считает всегда — вторым запросом
    по тому же отбору.

    Страницу адресует либо `cursor` из `meta.next_cursor` предыдущей страницы, либо
    `offset` — номер первой строки от начала выдачи: страница N размера L начинается с
    `(N - 1) * L`. Вместе они не принимаются (`422 cursor_with_offset`): это два разных
    адреса одной страницы, и выбрать за клиента значило бы отдать не ту.

    Цена смещения названа честно: база читает и выбрасывает пропускаемые строки, а
    страница сдвигается, если между двумя запросами задачу завели или подняли наверх
    (`sort=-updated_at`) — строка на границе покажется дважды или пропадёт. Курсор от
    этого свободен, поэтому обход **всей** выдачи (и агенты через MCP) идёт им.
    Смещение за концом выдачи — законный запрос: пустая страница, `has_more: false` и
    прежний `total`.
    """
    outcome = await search_service.search_tasks(
        session,
        actor=actor,
        query=query,
        structured=filters.to_terms(),
        sort=sort or (),
        fields=fields or (),
        limit=limit,
        cursor=cursor,
        offset=offset,
        # Число выдачи здесь считают всегда: этот список рисует человеку номера страниц,
        # а «попроси, и посчитаю» дало бы интерфейсу способ забыть попросить — и пустое
        # место вместо «всего 98». Агенты ходят сюда не этим маршрутом, а инструментом
        # MCP `search_tasks`, и за подсчёт не платят.
        with_total=True,
    )
    return search_page(outcome)


# Фиксированный сегмент `move` объявлен до маршрутов с `{task_key}` (`docs/notes/api.md`):
# сейчас `POST /tasks/{task_key}` нет, но первый же такой маршрут перехватил бы пакет.
@router.post("/move", summary="Move a list of tasks to another project")
async def move_tasks(
    payload: TaskMoveBatch,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskMoveBatchRead]:
    """Переносит задачи списка в один проект, каждую отдельно (TRK-309). Требует `main`.

    Задачи переносятся по одной в порядке списка — по нему же идут новые номера — и
    каждая получает свою запись `moved` с общей причиной. Ответ — итог по каждому
    элементу списка, повторы тоже: `moved` (ключи до и после, номер записи), `already`
    (задача уже в целевом проекте, `task_already_in_project`) или `error` с кодом,
    сообщением и подробностями того отказа, каким ответил бы одиночный перенос
    (`task_not_found`, `project_archived` исходного проекта…). Отказ одной задачи
    остальных не откатывает.

    Отказы всего вызова, до первого переноса: набор `task` — `403 permission_denied`;
    пустая причина — `422 task_move_reason_required`; пустой список или длиннее
    потолка — `422 task_move_batch_size_invalid`; неизвестный целевой проект — `404
    project_not_found`; целевой проект в архиве — `409 project_archived`.
    """
    outcomes = await service.move_tasks(
        session,
        payload.keys,
        actor=actor,
        project_key=payload.project,
        reason=payload.reason,
    )
    return DataResponse[TaskMoveBatchRead](
        data=TaskMoveBatchRead(results=[_move_outcome_read(item) for item in outcomes])
    )


def _move_outcome_read(
    value: TaskMoveOutcome,
) -> TaskMovedRead | TaskAlreadyThereRead | TaskMoveRefusedRead:
    """Итог пакетного переноса по одному ключу — в схему ответа."""
    match value:
        case TaskMoved():
            return TaskMovedRead(
                key=value.key,
                outcome="moved",
                from_key=value.from_key,
                to_key=value.to_key,
                no=value.no,
            )
        case TaskAlreadyThere():
            return TaskAlreadyThereRead(key=value.key, outcome="already", to_key=value.to_key)
        case TaskMoveRefused():
            return TaskMoveRefusedRead(
                key=value.key,
                outcome="error",
                code=value.refusal.code,
                message=value.refusal.message,
                details=value.refusal.details,
            )


@router.get("/{task_key}", summary="Read a task")
async def read_task(
    task_key: TaskKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskPackageRead]:
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.

    Карточка, связи с обеих сторон со статусом задачи на другой стороне, вычисляемые
    признаки, последняя сводка целиком, открытые вопросы и неразобранные замечания
    целиком, опись дела и переходы по таблице. Тела остальных записей читаются отдельно
    в `GET /tasks/{key}/entries`.
    Переходы перечислены по таблице; валидации (заполненные разделы, сводка, вердикты,
    блокеры, дети) проверяются в момент перехода, а не при чтении.
    """
    package = await service.read_task_package(session, task_key, actor=actor)
    key = package.task.key
    return DataResponse[TaskPackageRead](
        data=TaskPackageRead(
            task=TaskRead.model_validate(package.task),
            parent=None
            if package.parent is None
            else LinkTaskRead.model_validate(package.parent.other),
            children=[LinkTaskRead.model_validate(link.other) for link in package.children],
            links=[TaskLinkRead.model_validate(link) for link in package.links],
            features=TaskFeaturesRead.model_validate(package.features, from_attributes=True),
            # `entry_read` отдаёт вариант по типу записи, а сценарий гарантирует, что
            # сюда попали именно сводка, вопросы и замечания: сузить тип здесь нечем и
            # незачем.
            summary=None if package.summary is None else entry_read(package.summary, task_key=key),
            questions=[entry_read(question, task_key=key) for question in package.questions],
            remarks=[entry_read(remark, task_key=key) for remark in package.remarks],
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
    task_field_locked`); исполнитель и приоритет — в любом незакрытом статусе; в
    `done` и `cancelled` не меняется ничего (`409 task_closed`). Каждое изменение
    подшивает запись: раздел — `section_changed`, исполнитель — `assignee_changed`,
    приоритет — `field_changed`. Поля без записи не бывает: изменение, не
    оставившее записи, не доходит до ленты (`CONCEPT.md`, 4.1). `version` — не поле
    задачи, а условие: устаревшая версия отвечает `409 version_conflict`.

    Проверку правят двумя способами: `check` меняет текст одной на месте, `checks`
    заменяет список целиком и годится, когда меняется сам состав. Вместе они не
    принимаются — это два разных ответа на один вопрос.
    """
    task = await service.get_task(session, task_key)
    # `exclude_unset` — единственный фильтр: у `assignee` явный `null` осмыслен и обязан
    # дожить до сценария, у остальных полей его уже отвергла схема.
    changes = payload.model_dump(exclude_unset=True)
    version = changes.pop("version", None)
    if "check" in changes:
        # Схема отдаёт вложенную модель словарём, а сценарий ждёт значение домена:
        # перевод стоит здесь, где кончается транспорт.
        changes["check"] = CheckEdit(**changes["check"])
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
    последнего входа в него (`409 summary_required`); `in_progress → done` —
    положительного последнего вердикта по каждой проверке, подшитого после последнего
    входа в `in_progress` (`409 checks_not_passed`, незасчитанные проверки в
    `details.checks` парами `check_no` и `reason`). Вход в `in_progress` делает только
    исполнитель задачи: без исполнителя — `409 assignee_required`, от другой подписи
    (имя участника токена или метка `X-Actor-Label`) — `409 assignee_mismatch` с
    `details.assignee` и `details.requester`. Вход в
    `in_progress` отклоняется и при открытом блокере (`409 task_blocked`, их ключи в
    `details.blockers`), закрытие — и `done`, и `cancelled` — при детях не в `done` и
    не в `cancelled` (`409 task_has_unclosed_children`, ключи в `details.children`).
    Переход подшивает `status_changed` с `from`, `to` и `reason`.

    Цель `done` не принимается: закрытие подшивает вердикты и сводку и переводит задачу
    одной транзакцией, и у него свой маршрут — `409 closing_not_a_transition`.
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


@router.post("/{task_key}/move", summary="Move a task to another project")
async def move_task(
    task_key: TaskKeyPath,
    payload: TaskMove,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[TaskRead]:
    """Переносит задачу в другой проект (`CONCEPT.md`, 3.3). Требует набора `main`.

    Задача получает следующий номер целевого проекта, а если ключ в нём у неё уже был —
    этот прежний ключ. Уходящий ключ дописывается в `previous_keys` и дальше ведёт на
    задачу везде, где принимается ключ. Статус не важен: закрытая задача переносится
    тоже. Связи, родство и дело не меняются; в дело задачи подшивается `moved` с обоими
    проектами, обоими ключами и причиной.

    Отказы: набор `task` — `403 permission_denied`; пустая причина — `422
    task_move_reason_required`; неизвестный проект — `404 project_not_found`; текущий
    или целевой проект в архиве — `409 project_archived`; целевой проект тот же, где
    задача лежит, — `409 task_already_in_project`; устаревшая `version` — `409
    version_conflict`.
    """
    task = await service.get_task(session, task_key)
    project = await projects_service.get_project(session, payload.project)
    moved = await service.move_task(
        session,
        task,
        actor=actor,
        project=project,
        reason=payload.reason,
        expected_version=payload.version,
    )
    return DataResponse[TaskRead](data=TaskRead.model_validate(moved.task))


@router.post("/{task_key}/close", summary="Close a task")
async def close_task(
    task_key: TaskKeyPath,
    payload: TaskClosing,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[TaskRead]:
    """Подшивает записи, вердикты и финальную сводку и переводит задачу в `done` — всё
    одним запросом и одной транзакцией.

    Единственный путь в `done`: у перехода эта цель отвечает `409
    closing_not_a_transition`. Частичного закрытия не бывает — отказ на любой части не
    оставляет в деле ни одной записи и статуса не меняет.

    Порядок подшивки: присланные записи, вердикты, сводка. Требования выхода прежние и
    проверяются после подшивки: положительный последний вердикт по каждой проверке
    среди подшитых после последнего входа в `in_progress` (`409 checks_not_passed`),
    закрытые дети (`409 task_has_unclosed_children`), задача в `in_progress` (`409
    transition_not_allowed`). Вердикты этого запроса засчитываются наравне с подшитыми
    раньше по ходу работы, поэтому список может быть пуст.

    Повтор с тем же `Idempotency-Key` отвечает первым результатом и второго закрытия не
    заводит. В ответе — карточка задачи; подшитые записи читаются `GET
    /tasks/{task_key}/entries`.
    """
    task = await service.get_task(session, task_key)
    given = payload.model_dump(mode="json")

    async def close() -> DataResponse[TaskRead]:
        closure = await service.close_task(
            session,
            task,
            actor=actor,
            summary=case_service.SummaryFiling(**given["summary"]),
            verdicts=[case_service.VerdictFiling(**item) for item in given["verdicts"]],
            entries=[
                case_service.EntryFiling(
                    type=item["type"],
                    title=item["title"],
                    body=item["body"],
                    refs=item["refs"],
                )
                for item in given["entries"]
            ],
            expected_version=payload.version,
        )
        return DataResponse[TaskRead](data=TaskRead.model_validate(closure.task))

    return await once.run(
        DataResponse[TaskRead],
        request={"task": task.key, "closing": given},
        build=close,
    )


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
    once: OnceDep,
) -> DataResponse[EntryRead]:
    """Подшивает запись агента: сводку, решение, попытку, находку, артефакт, вопрос,
    ответ, вердикт или заметку.

    Форма нагрузки зависит от типа: тело запроса — размеченное по `type` объединение.
    Заголовок принимается только там, где его нечем вывести: у `summary` он равен
    первой строке `done`, у `answer` и `verdict` собирается из нагрузки.
    Служебные типы (`status_changed`, `created`, ...) подшивает сам трекер, и в запросе
    они не принимаются. Замечания к форме приходят разом в `422 entry_fields_invalid`,
    списком `details.fields`. Записи неизменяемы, а в закрытую задачу подшиваются.

    Повтор с тем же `Idempotency-Key` отвечает первой записью: агент, упавший до ответа,
    не подшивает вторую копию своей сводки.
    """
    task = await service.get_task(session, task_key)
    # Все поля уезжают в сценарий как есть: разбирать объединение по ветвям здесь
    # значило бы держать в роутере знание о том, у какого типа какая нагрузка, — а оно
    # уже выражено доменом и схемой.
    given = entry.model_dump(mode="json")

    async def append() -> DataResponse[EntryRead]:
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

    return await once.run(
        DataResponse[EntryRead],
        request={"task": task.key, "entry": given},
        build=append,
    )


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
