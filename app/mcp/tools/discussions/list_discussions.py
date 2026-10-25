"""Инструмент `list_discussions`: обсуждения проекта строкой — адрес, название, статус, ход."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.db.repositories.discussions import DiscussionRow
from app.domain.discussions import DiscussionStatus, DiscussionTurn
from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.enums import DiscussionStatusSchema, DiscussionTurnSchema
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import discussions as discussions_service
from app.services import projects as projects_service
from app.services import tasks as tasks_service

ProjectFilterArg = Annotated[
    str | None,
    Field(
        description=(
            "Only this project's discussions; an archived project's only when named here. "
            "An unknown key is refused with `project_not_found`"
        ),
    ),
]
StatusFilterArg = Annotated[
    DiscussionStatusSchema | None, Field(description="Only open or only closed discussions")
]
TurnFilterArg = Annotated[
    DiscussionTurnSchema | None,
    Field(description="Only discussions with this turn"),
]
TaskFilterArg = Annotated[
    str | None,
    Field(
        description=(
            "Only discussions this task is attached to. An unknown key is refused with "
            "`task_not_found`"
        ),
    ),
]


# Строка списка уже строки REST (`DiscussionRead`): адрес вместо ключа проекта с номером,
# без авторов, времени создания и правки. Привязанные задачи и последний итог несёт
# `get_task`, дело — `read_project_entries` по адресу. Статус и ход строками, как в
# `TaskDiscussionView`: перечисление встало бы в схему копией.
class DiscussionRowView(BaseModel):
    """Discussion in one line."""

    address: str
    title: str
    status: str = Field(description="`open` or `closed`")
    turn: str | None = Field(
        description=(
            "`human`: a question has no answer; `agent`: an answer or a person's entry "
            "follows the latest conclusion; else `null`"
        )
    )
    open_questions: int
    closed_at: datetime | None


def discussion_row(row: DiscussionRow) -> DiscussionRowView:
    """Строка `list_discussions`."""
    item = row.discussion
    return DiscussionRowView(
        address=item.address,
        title=item.title,
        status=item.status.value,
        turn=None if row.turn is None else row.turn.value,
        open_questions=row.open_questions,
        closed_at=item.closed_at,
    )


def register(tools: Toolset) -> None:
    """Объявляет `list_discussions`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(title="List discussions", annotations=READ_ONLY)
    async def list_discussions(
        project: ProjectFilterArg = None,
        status: StatusFilterArg = None,
        turn: TurnFilterArg = None,
        task: TaskFilterArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[DiscussionRowView]:
        """Lists discussions, oldest first, one page at a time: address, title, status,
        turn, number of unanswered questions and closing time. Filters combine. A
        discussion's case is read with `read_project_entries`; its attached tasks and
        latest conclusion come with `get_task`.
        """
        async with runtime.call() as (session, actor):
            listed = await discussions_service.list_discussions(
                session,
                actor=actor,
                project=None
                if project is None
                else await projects_service.get_project(session, project),
                status=None if status is None else DiscussionStatus(status),
                turn=None if turn is None else DiscussionTurn(turn),
                task=None if task is None else await tasks_service.get_task(session, task),
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (discussion_row(row) for row in listed.items), next_cursor=listed.next_cursor
            )
