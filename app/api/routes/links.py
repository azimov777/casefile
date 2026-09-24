"""Связи между задачами: поставить и снять.

Отдельный роутер с тем же префиксом, что и задачи: маршрутов два, но у них своя область
и свой набор кодов ошибок, а в `tasks.py` они растворились бы среди дела.

Чтения здесь нет намеренно. Связи приезжают в пакете преемника
(`GET /api/v1/tasks/{key}`) вместе со статусом задачи на другой стороне: отдельная
выдача означала бы второй запрос ради того, что агент и так получает первым.
"""

from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import ActorDep, SessionDep, TaskKeyPath
from app.api.idempotency import OnceDep
from app.api.schemas.common import DataResponse
from app.api.schemas.links import LinkCreate, TaskLinkRead
from app.domain.links import LinkKind
from app.services import links as service
from app.services import tasks as tasks_service

router = APIRouter(prefix="/tasks", tags=["links"])

LinkKindPath = Annotated[
    LinkKind,
    Path(
        description="Link kind as seen from the task in the path, not from the other one",
        examples=["blocks"],
    ),
]
OtherTaskKeyPath = Annotated[
    str,
    Path(
        description="Key of the task on the other side; matching ignores case",
        examples=["TRK-7"],
    ),
]


@router.post(
    "/{task_key}/links",
    status_code=status.HTTP_201_CREATED,
    summary="Link two tasks",
)
async def create_task_link(
    task_key: TaskKeyPath,
    payload: LinkCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[TaskLinkRead]:
    """Ставит связь между задачами и подшивает `link_added` в дела обеих.

    Вид связи называет роль задачи из пути: `{"kind": "blocks", "other": "TRK-7"}` у
    `TRK-1` означает «TRK-1 блокирует TRK-7», и в карточке `TRK-7` та же связь
    показывается как `blocked_by TRK-1`. Хранится она одной строкой, поэтому повтор с
    другой стороны — `409 link_exists`, а не вторая связь.

    Отказы: связь с самой собой — `422 link_self_not_allowed`; кольцо в иерархии или в
    блокировках — `409 link_cycle_detected` (виды не смешиваются: родитель, у которого
    `blocked_by` на своих детей, кольцом не считается); второй родитель у задачи —
    `409 task_has_parent` (родитель один, детей сколько угодно); `parent` или `blocks`
    с задачей в `done` или `cancelled` с любой стороны — `409 task_closed`. `relates` с закрытой
    задачей проходит: им связывают её с продолжением. Повтор с тем же `Idempotency-Key`
    отвечает первой связью, а не `409 link_exists`.
    """
    task = await tasks_service.get_task(session, task_key)
    other = await tasks_service.get_task(session, payload.other)

    async def link() -> DataResponse[TaskLinkRead]:
        created = await service.add_link(session, task, other, actor=actor, kind=payload.kind)
        return DataResponse[TaskLinkRead](data=TaskLinkRead.model_validate(created))

    return await once.run(
        DataResponse[TaskLinkRead],
        request={"task": task.key, "other": other.key, "kind": payload.kind},
        build=link,
    )


@router.delete(
    "/{task_key}/links/{kind}/{other_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a link between two tasks",
)
async def delete_task_link(
    task_key: TaskKeyPath,
    kind: LinkKindPath,
    other_key: OtherTaskKeyPath,
    session: SessionDep,
    actor: ActorDep,
) -> None:
    """Снимает связь и подшивает `link_removed` в дела обеих задач.

    Адресуется связь так же, как ставилась, — видом со стороны задачи из пути. Снять её
    можно с любой стороны: `blocks` у одной и `blocked_by` у другой — одна строка.
    Связи нет — `404 link_not_found`; `parent` или `blocks` у закрытой задачи —
    `409 task_closed`, `relates` снимается и у закрытой.
    """
    task = await tasks_service.get_task(session, task_key)
    other = await tasks_service.get_task(session, other_key)
    await service.remove_link(session, task, other, actor=actor, kind=kind)
