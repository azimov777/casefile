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
from app.api.schemas.entries import AnsweredQuestionRead, entry_read
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.case import QuestionOrder
from app.services import case as case_service
from app.services import projects as projects_service
from app.services.case import AnsweredQuestion

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
AnyAddresseeQuery = Annotated[
    bool,
    Query(
        description=(
            "true drops the addressee filter and returns questions to anyone. Not "
            "accepted together with `addressee` (`422 addressee_with_any_addressee`)"
        ),
    ),
]
ProjectQuery = Annotated[
    str | None,
    Query(
        description=(
            "Project key of the question's task; matching ignores case. Without it tasks of "
            "archived projects are left out; a project named here is listed even archived"
        ),
        examples=["TRK"],
    ),
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

OrderQuery = Annotated[
    QuestionOrder,
    Query(
        description=(
            "`oldest` (the default) puts the longest-waiting question first, as an inbox "
            "needs; `newest` puts the latest first, as a history needs. A cursor only "
            "continues the order it was issued in"
        ),
    ),
]


@router.get("", summary="List questions")
async def list_questions(
    session: SessionDep,
    actor: ActorDep,
    addressee: AddresseeQuery = None,
    any_addressee: AnyAddresseeQuery = False,
    project: ProjectQuery = None,
    blocking: BlockingQuery = None,
    open_only: OpenQuery = True,
    order: OrderQuery = QuestionOrder.OLDEST,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[AnsweredQuestionRead]:
    """Вопросы всех задач с фильтрами; по умолчанию — открытые вопросы текущего участника.

    Порядок по умолчанию — от самого старого: дольше всех ждёт ответа тот, кого задали
    первым; `order=newest` переворачивает его для истории. Ответ на вопрос убирает его
    из выдачи открытых, потому что открытость считается по делу, а не хранится флагом;
    с `open=false` вопрос остаётся и несёт свои ответы в `answers`. Адресовать можно
    только участника реестра, поэтому запрос общим агентским токеном без явного
    `addressee` и без `any_addressee` — `422 actor_not_addressable`: пустой список
    молча соврал бы, что вопросов не пришло.
    """
    page = await case_service.list_questions(
        session,
        actor=actor,
        addressee=addressee,
        any_addressee=any_addressee,
        project=None if project is None else await projects_service.get_project(session, project),
        blocking=blocking,
        open_only=open_only,
        order=order,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[AnsweredQuestionRead].of(
        [answered_question_read(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


def answered_question_read(item: AnsweredQuestion) -> AnsweredQuestionRead:
    """Строка выдачи: вопрос тем же сборщиком, что и в деле, плюс его ответы."""
    question = entry_read(item.entry, task_key=item.task_key)
    return AnsweredQuestionRead(
        **question.model_dump(by_alias=True),
        answers=[entry_read(answer, task_key=item.task_key) for answer in item.answers],
    )
