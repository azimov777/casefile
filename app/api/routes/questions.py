"""Вопросы поперёк задач: «входящая» участника.

Не новая сущность, а **представление** над делом (`CONCEPT.md`, 3.6): вопрос — это
запись `question`, открытая, пока в той же задаче нет `answer` с её номером. Поэтому
здесь только чтение: задаются и закрываются вопросы записями в дело конкретной задачи,
и второй способ их создать развёл бы вопрос с делом, в котором он живёт.

Роутер только переводит HTTP в вызов сценария и обратно.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse
from app.api.schemas.entries import QuestionEntryRead, entry_read
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import case as case_service
from app.services import queues as queues_service

router = APIRouter(prefix="/questions", tags=["questions"])

AddresseeQuery = Annotated[
    str | None,
    Query(
        description=(
            "Participant the question is addressed to; matching ignores case. Defaults "
            "to the participant whose token made the request"
        ),
        examples=["owner"],
    ),
]
QueueQuery = Annotated[
    str | None,
    Query(description="Queue key of the question's task; matching ignores case", examples=["TRK"]),
]
BlockingQuery = Annotated[
    bool | None,
    Query(description="Keep only questions that do (or do not) block the work"),
]
OpenQuery = Annotated[
    bool,
    Query(
        alias="open",
        description=(
            "true (the default) keeps only questions with no answer yet; false drops the "
            "filter and returns every question, answered or not. To read the questions "
            "of one task use its case with `types=question`"
        ),
    ),
]


@router.get("", summary="List questions")
async def list_questions(
    session: SessionDep,
    actor: ActorDep,
    addressee: AddresseeQuery = None,
    queue: QueueQuery = None,
    blocking: BlockingQuery = None,
    open_only: OpenQuery = True,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[QuestionEntryRead]:
    """Вопросы всех задач с фильтрами; по умолчанию — открытые вопросы текущего участника.

    Порядок — от самого старого: дольше всех ждёт ответа тот, кого задали первым.
    Ответ на вопрос убирает его из выдачи, потому что открытость считается по делу, а
    не хранится флагом. Адресовать можно только участника реестра, поэтому запрос общим
    агентским токеном без явного `addressee` — `422 actor_not_addressable`: пустой
    список молча соврал бы, что вопросов не пришло.
    """
    page = await case_service.list_questions(
        session,
        actor=actor,
        addressee=addressee,
        queue=None if queue is None else await queues_service.get_queue(session, queue),
        blocking=blocking,
        open_only=open_only,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[QuestionEntryRead].of(
        [entry_read(item.entry, task_key=item.task_key) for item in page.items],
        next_cursor=page.next_cursor,
    )
