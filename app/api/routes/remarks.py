"""Замечания поперёк задач: что ещё не разобрали.

Не новая сущность, а **представление** над делом (`CONCEPT.md`, 3.4), как и вопросы:
замечание — это запись `remark`, открытая, пока в той же задаче нет `resolution` с её
номером. Поэтому здесь только чтение; оставляют и разбирают замечания записями в дело
конкретной задачи.

Отличие от `/questions` ровно одно и оно в природе замечания: адресата у него нет, и
отбор «мои» идёт по автору записи. Умолчания у этого фильтра поэтому тоже нет — список
показывает все неразобранные замечания, пока не спросили про конкретного автора.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse
from app.api.schemas.entries import RemarkEntryRead, entry_read
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import case as case_service
from app.services import projects as projects_service

router = APIRouter(prefix="/remarks", tags=["remarks"])

AuthorQuery = Annotated[
    str | None,
    Query(
        description=(
            "Signature the remark is filed under: a participant name or a temporary "
            "agent label; matching ignores case. Omit to get remarks by anyone"
        ),
        examples=["owner"],
    ),
]
ProjectQuery = Annotated[
    str | None,
    Query(
        description=(
            "Project key of the remark's task; matching ignores case. Without it tasks of "
            "archived projects are left out; a project named here is listed even archived"
        ),
        examples=["TRK"],
    ),
]
OpenQuery = Annotated[
    bool,
    Query(
        alias="open",
        description=(
            "true (the default) keeps only remarks with no resolution yet; false drops "
            "the filter and returns every remark, resolved or not. To read the remarks "
            "of one task use its case with `types=remark`"
        ),
    ),
]


@router.get("", summary="List remarks")
async def list_remarks(
    session: SessionDep,
    actor: ActorDep,
    author: AuthorQuery = None,
    project: ProjectQuery = None,
    open_only: OpenQuery = True,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[RemarkEntryRead]:
    """Замечания всех задач с фильтрами; по умолчанию — все неразобранные.

    Порядок — от самого старого: дольше всех ждёт разбора то, что оставили первым.
    Резолюция убирает замечание из выдачи, потому что открытость считается по делу, а не
    хранится флагом; из дела оно при этом никуда не девается.

    Автор не проверяется по реестру: подписью бывает и метка временного агента, которой
    в реестре нет. Неизвестная подпись поэтому даёт пустой список, а не отказ.
    """
    page = await case_service.list_remarks(
        session,
        actor=actor,
        author=author,
        project=None if project is None else await projects_service.get_project(session, project),
        open_only=open_only,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[RemarkEntryRead].of(
        [entry_read(item.entry, task_key=item.task_key) for item in page.items],
        next_cursor=page.next_cursor,
    )
