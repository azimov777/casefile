"""Первый экран интерфейса человека одним запросом.

Новой сущности здесь нет: это представление над участниками, очередями и вопросами.
Роутер только переводит HTTP в вызов сценария и обратно.
"""

from fastapi import APIRouter

from app.api.deps import ActorDep, SessionDep
from app.api.schemas.bootstrap import BootstrapRead
from app.api.schemas.common import DataResponse
from app.api.schemas.participants import ParticipantRead
from app.api.schemas.queues import QueueRead
from app.api.schemas.tokens import CurrentTokenRead
from app.services import bootstrap as service

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])


@router.get("", summary="Read the first screen")
async def read_bootstrap(session: SessionDep, actor: ActorDep) -> DataResponse[BootstrapRead]:
    """Текущий участник, его токен с набором, очереди установки и число вопросов к нему.

    Ровно то, что нужно интерфейсу до первой отрисовки, и ничего сверх этого: списки
    задач и вопросов приходят своими запросами, уже с фильтрами, которые выбрал человек,
    а сведения установки, одинаковые для любого токена, — `GET /api/v1/installation`.

    `token` — тот токен, что стоит в заголовке: `id` из `GET /api/v1/tokens` и набор. По
    набору интерфейс решает, открыта ли запись, по `id` узнаёт свой ключ в списке токенов.

    У общего агентского токена участника нет: `participant` приходит `null`, а
    `open_questions` — ноль, потому что временного агента нельзя адресовать вопросом
    (`docs/CONCEPT.md`, 3.6). Очереди в этом случае отдаются те же самые.
    """
    state = await service.read_bootstrap(session, actor=actor)
    return DataResponse[BootstrapRead](
        data=BootstrapRead(
            participant=(
                None
                if state.participant is None
                else ParticipantRead.model_validate(state.participant)
            ),
            token=CurrentTokenRead(id=state.token_id, scope=state.scope),
            queues=[QueueRead.model_validate(queue) for queue in state.queues],
            open_questions=state.open_questions,
        )
    )
