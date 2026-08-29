"""Схемы агрегирующих ответов: карточка задачи, стартовые данные, сводка по проекту.

Своих полей здесь почти нет — только сборка уже существующих схем. Это принципиально:
агрегат обязан отдавать ровно то же, что отдали бы отдельные эндпоинты, иначе у одного
и того же объекта появилось бы два представления, и они разошлись бы на первой же
правке. Поэтому все вложенные модели импортированы, а не переписаны.

Коллекции внутри агрегата отдаются первой страницей плюс курсором **того самого
эндпоинта**, который листает эту коллекцию дальше. Своей пагинации агрегат не заводит:
она стала бы вторым способом листать одно и то же, а два способа расходятся. Поле
названо `*_next_cursor`, чтобы его происхождение читалось без документации — это
`meta.next_cursor` соответствующей коллекции.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.schemas.actors import ActorRead
from app.api.schemas.catalogs import IssueTypeRead, ResolutionRead, StatusRead
from app.api.schemas.checklists import ChecklistItemRead
from app.api.schemas.comments import CommentRead
from app.api.schemas.fields import FieldRead
from app.api.schemas.issues import IssueRead
from app.api.schemas.links import IssueLinkRead
from app.api.schemas.projects import ProjectRead
from app.api.schemas.queues import QueueRead
from app.api.schemas.search import IssueSearchRead
from app.api.schemas.workflows import IssueTransitionRead

NextCursorDescription = (
    "Cursor for the next page of this collection, to be sent to its own endpoint. "
    "Null means the aggregate already carries everything there is"
)


class IssueCardRead(BaseModel):
    """Экран задачи целиком: сама задача, доступные переходы, связи, обсуждение, чеклист.

    Один запрос вместо пяти. Собирается из тех же сценариев, что и отдельные эндпоинты,
    и потому не может показать другое: карточка — способ сэкономить обращения, а не
    второе мнение о задаче.
    """

    issue: IssueRead
    transitions: list[IssueTransitionRead] = Field(
        description=(
            "Workflow transitions out of the current status, available and not. Same as "
            "`GET /issues/{issue_key}/transitions`: an unavailable one carries the "
            "fields it still needs, so the interface can explain the refusal in advance"
        )
    )
    links: list[IssueLinkRead] = Field(
        description=(
            "Links as this issue sees them: a link stored as `A depends_on B` reaches B "
            "as `blocks`. Same as `GET /issues/{issue_key}/links`"
        )
    )
    links_next_cursor: str | None = Field(default=None, description=NextCursorDescription)
    comments: list[CommentRead] = Field(
        description=(
            "Discussion, oldest first. Deleted replies stay in place with a null `body` "
            "and `is_deleted: true`. Same as `GET /issues/{issue_key}/comments`"
        )
    )
    comments_next_cursor: str | None = Field(default=None, description=NextCursorDescription)
    checklist: list[ChecklistItemRead] = Field(
        description=(
            "Checklist in display order. It is never paginated: the whole list is the "
            "unit of meaning, and half a checklist is not a useful answer"
        )
    )


class BootstrapRead(BaseModel):
    """Стартовые данные интерфейса: всё, что нужно, чтобы отрисовать первый экран.

    Один запрос вместо пяти при загрузке приложения. Содержимое отобрано под шапку и
    навигацию, а не «всё, что есть»: конфигурация конкретной очереди приезжает
    отдельным `GET /queues/{queue_key}/config`, когда пользователь в неё зашёл.
    """

    actor: ActorRead = Field(description="The actor behind the token; same as `GET /actors/me`")
    queues: list[QueueRead] = Field(
        description="Active queues, archived ones left out — they do not belong in navigation"
    )
    statuses: list[StatusRead] = Field(
        description=(
            "Global statuses: enough to render any board or filter chip. Statuses local "
            "to a queue arrive with that queue's configuration"
        )
    )
    issue_types: list[IssueTypeRead] = Field(description="Global issue types")
    resolutions: list[ResolutionRead] = Field(description="Global resolutions")
    fields: list[FieldRead] = Field(
        description="Global custom fields; queue-local ones arrive with the queue configuration"
    )
    unread_notifications: int = Field(
        ge=0,
        examples=[3],
        description=(
            "Number of unread inbox notifications for this actor. The count alone, not "
            "the notifications: the badge is drawn before the inbox is ever opened"
        ),
    )


class ProjectSummaryRead(BaseModel):
    """Сводка по проекту: карточка с прогрессом и первая страница его задач.

    Прогресс лежит внутри `project`, а не рядом: он свойство проекта, и второе место,
    где его можно прочитать, однажды показало бы другое число.
    """

    project: ProjectRead = Field(description="Project card with its computed progress")
    issues: list[IssueSearchRead] = Field(
        description=(
            "First page of the project issues, newest first. Same shape and same "
            "`fields` selection as `GET /projects/{project_key}/issues`"
        )
    )
    issues_next_cursor: str | None = Field(default=None, description=NextCursorDescription)
