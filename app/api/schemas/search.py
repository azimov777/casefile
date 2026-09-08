"""Схемы отбора задач: параметры запроса, структурный фильтр и задача в выдаче.

## Почему у задачи в выдаче все поля необязательны

Список умеет отдавать подмножество полей (`fields`), и это не оптимизация, а требование
концепции: полная задача с пятью разделами съедает контекст агента, которому нужен один
столбец ключей. Схема обязана честно это показывать — поле, которого может не быть, в
сгенерированном клиенте должно быть необязательным. Маршрут отдаёт ответ с
`response_model_exclude_unset`, поэтому непрошенные поля не приезжают ни как `null`, ни
как значение по умолчанию.

Без явного `fields` возвращается задача целиком — ровно в том же виде, в каком её отдаёт
чтение, плюс вычисляемые признаки: набор полей у `TaskSearchRead` — это поля `TaskRead` и
`features`, и это стережёт тест. Два разных представления одной задачи в одном API — то,
чего проект не допускает, поэтому признаки приезжают тем же объектом `TaskFeaturesRead`,
что и в пакете преемника, а не плоскими полями рядом с колонками задачи.

## Два способа задать отбор и один результат

`query` — строка на языке запросов, остальные параметры — структурный фильтр. Их можно
сочетать: условия складываются по `and`. Значения структурного фильтра разбираются теми
же правилами, что и значения языка, поэтому `?assignee=empty()` и `assignee: empty()` —
это буквально один путь исполнения.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import CollectionResponse
from app.api.schemas.tasks import TaskFeaturesRead, TaskQueueRead
from app.domain.query_language import (
    QUERY_EXAMPLES,
    QUERY_RIGHT_SHAPE,
    QUERY_WRONG_SHAPE,
)
from app.domain.search import (
    FEATURES_FIELD,
    MAX_QUERY_LENGTH,
    MAX_SORT_TERMS,
    MAX_VALUES_PER_CONDITION,
    Operator,
    searchable_names,
    selectable_names,
    sortable_names,
)
from app.domain.tasks import TaskPriority, TaskStatus, feature_names
from app.services.search import FoundTask, SearchOutcome, StructuredTerm

_QUERY_DESCRIPTION = (
    "Query language string, for example `queue: TRK and status: open and blocked: false "
    "and open_blocking_questions: 0`. Fields: "
    + ", ".join(f"`{name}`" for name in searchable_names())
    + ". Operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` (contains), `!~`, `in`, "
    "`not in`; `empty()` matches tasks with no value in the field. The operator goes "
    f"**after** the colon — `{QUERY_RIGHT_SHAPE}`, not `{QUERY_WRONG_SHAPE}`: "
    "parentheses group conditions, not values. Without an operator a condition means "
    "equality, and several comma-separated values already mean set membership. Combine "
    "with `and`, `or` and parentheses. Values with spaces or a leading language word go "
    "in quotes. Examples: "
    + "; ".join(f"`{example}`" for example in QUERY_EXAMPLES)
    + ". A parse error answers 422 with the position of the offending character and, "
    "where the right shape follows from it, with that shape in `details.hint`"
)
_SORT_DESCRIPTION = (
    "Sort keys, most significant first. A leading `-` sorts descending: `-updated_at`. "
    "Sortable: " + ", ".join(f"`{name}`" for name in sortable_names()) + ". `key` orders "
    "by queue and task number, so `TRK-10` follows `TRK-2`. The result is always "
    "tie-broken by task id, so paging stays stable while tasks are being created"
)
_FIELDS_DESCRIPTION = (
    "Fields to return, to keep the answer small: "
    + ", ".join(f"`{name}`" for name in selectable_names())
    + ". Omit for the whole task, computed features included. The task key is always "
    "included. `features` is picked as a whole and brings "
    + ", ".join(f"`{name}`" for name in feature_names())
    + "; a single feature is not a field of the answer, and asking for one answers 422 "
    "`search_field_unknown` with the selectable names"
)
QueryParam = Annotated[
    str | None,
    Query(
        max_length=MAX_QUERY_LENGTH,
        examples=["queue: TRK and status: open and blocked: false"],
        description=_QUERY_DESCRIPTION,
    ),
]
SortParam = Annotated[
    list[str] | None,
    Query(max_length=MAX_SORT_TERMS, examples=[["-updated_at"]], description=_SORT_DESCRIPTION),
]
FieldsParam = Annotated[
    list[str] | None,
    Query(examples=[["title", "status"]], description=_FIELDS_DESCRIPTION),
]


@dataclass(frozen=True, slots=True)
class TaskFilters:
    """Структурный фильтр: по параметру запроса на поле отбора.

    Значения одного параметра складываются по `or`, параметры между собой — по `and`.
    Это и есть смысл формы поиска: сузить по каждому полю, приняв любое из отмеченных
    значений. Параметр, который не передали, не фильтрует; переданный пустым списком —
    тоже, иначе снятая в интерфейсе галочка обнуляла бы выдачу.

    Датакласс через `Depends()`, а не модель Pydantic через `Query()`: FastAPI
    раскладывает модель на отдельные параметры, **только** если она единственный
    параметр запроса у маршрута, а здесь рядом стоят `query`, `sort`, `fields`, `limit`
    и `cursor`. С моделью отбор молча перестал бы работать — параметры доезжали бы
    пустыми, и ответ выглядел бы как «ничего не отфильтровано» (`docs/notes/api.md`).
    """

    queue: Annotated[
        list[str] | None,
        Query(
            max_length=MAX_VALUES_PER_CONDITION,
            examples=[["TRK"]],
            description="Queue keys; matching ignores case",
        ),
    ] = None
    parent: Annotated[
        list[str] | None,
        Query(
            max_length=MAX_VALUES_PER_CONDITION,
            examples=[["TRK-7"]],
            description=(
                "Parent task keys: the answer holds their direct children, one level "
                "deep. `empty()` finds tasks with no parent — the top level of a queue. "
                "An unknown key answers 422 instead of an empty page: emptiness here "
                "reads as «no children» and would hide the typo"
            ),
        ),
    ] = None
    status: Annotated[
        list[TaskStatus] | None, Query(examples=[[TaskStatus.OPEN]], description="Task statuses")
    ] = None
    assignee: Annotated[
        list[str] | None,
        Query(
            max_length=MAX_VALUES_PER_CONDITION,
            examples=[["release_bot"]],
            description="Assignee names, matched exactly; `empty()` finds unassigned tasks",
        ),
    ] = None
    priority: Annotated[
        list[TaskPriority] | None,
        Query(examples=[[TaskPriority.HIGH]], description="Task priorities"),
    ] = None
    blocked: Annotated[
        bool | None,
        Query(
            description=(
                "Whether the task has a `blocked_by` link to a task that is neither "
                "`done` nor `cancelled`. Computed from links, not stored"
            )
        ),
    ] = None
    open_questions: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Exact number of questions with no answer. Use the query language for "
                "ranges: `open_questions: > 0`"
            ),
        ),
    ] = None
    open_blocking_questions: Annotated[
        int | None,
        Query(
            ge=0,
            description=("Of those, the ones marked `blocking`; `0` means nothing is in the way"),
        ),
    ] = None
    open_remarks: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Exact number of remarks with no resolution. Use the query language for "
                "ranges: `open_remarks: > 0`"
            ),
        ),
    ] = None
    remarks_in_work: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Remarks resolved as `accepted` whose continuation task is still open: "
                "reviewed, but the work is not finished"
            ),
        ),
    ] = None
    text: Annotated[
        str | None,
        Query(
            min_length=1,
            examples=["выдача ключей"],
            description="Substring of the title or the description, matched case-insensitively",
        ),
    ] = None

    def to_terms(self) -> list[StructuredTerm]:
        """Структурный фильтр → канонические условия. Одно место перевода на весь API.

        Перечисления отдаются строками, а не членами: значение уезжает в тот же разбор,
        что и значение языка, и второй способ его понять развёл бы два входа поиска.
        """
        terms: list[StructuredTerm] = [
            StructuredTerm(name=name, values=values)
            for name, values in (
                ("queue", self.queue),
                ("parent", self.parent),
                ("status", None if self.status is None else [item.value for item in self.status]),
                ("assignee", self.assignee),
                (
                    "priority",
                    None if self.priority is None else [item.value for item in self.priority],
                ),
            )
            if values
        ]
        terms.extend(
            StructuredTerm(name=name, values=[value])
            for name, value in (
                ("blocked", self.blocked),
                ("open_questions", self.open_questions),
                ("open_blocking_questions", self.open_blocking_questions),
                ("open_remarks", self.open_remarks),
                ("remarks_in_work", self.remarks_in_work),
            )
            if value is not None
        )
        if self.text is not None:
            terms.append(
                StructuredTerm(name="text", values=[self.text], operator=Operator.CONTAINS)
            )
        return terms


TaskFilterParams = Annotated[TaskFilters, Depends()]


class TaskSearchRead(BaseModel):
    """Задача в выдаче списка. Приезжают только запрошенные поля.

    Ключ приходит всегда: выдача без него бесполезна — по ней нельзя ни прочитать
    задачу, ни сослаться на неё.
    """

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(examples=["TRK-42"], description="Immutable and never reused")
    id: uuid.UUID | None = None
    queue: TaskQueueRead | None = None
    title: str | None = None
    description: str | None = None
    goal: str | None = None
    context: str | None = None
    constraints: str | None = None
    output: str | None = None
    checks: list[str] | None = None
    status: TaskStatus | None = None
    assignee: str | None = None
    priority: TaskPriority | None = None
    version: int | None = None
    created_by: AuthorRead | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    features: TaskFeaturesRead | None = Field(
        default=None,
        description=(
            "Computed features of the task, the same object the successor package "
            "carries. Included unless `fields` asks for a narrower set without `features`"
        ),
    )

    @classmethod
    def of(cls, found: FoundTask, *, fields: tuple[str, ...] = ()) -> TaskSearchRead:
        """Строка выдачи. Пустой набор полей означает «всё», как при чтении задачи.

        Признаков в словаре нет, если их не считали: `fields` без `features` — прямая
        просьба не платить за подзапросы, и показать в таком ответе `null` значило бы
        соврать про задачу, у которой признаки есть всегда.
        """
        task = found.task
        payload: dict[str, object] = {
            "id": task.id,
            "key": task.key,
            "queue": TaskQueueRead.model_validate(task.queue),
            "title": task.title,
            "description": task.description,
            "goal": task.goal,
            "context": task.context,
            "constraints": task.constraints,
            "output": task.output,
            "checks": list(task.checks),
            "status": task.status,
            "assignee": task.assignee,
            "priority": task.priority,
            "version": task.version,
            "created_by": AuthorRead.model_validate(task.created_by, from_attributes=True),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
        if found.features is not None:
            payload[FEATURES_FIELD] = TaskFeaturesRead.model_validate(
                found.features, from_attributes=True
            )
        if fields:
            payload = {name: value for name, value in payload.items() if name in fields}
        return cls(**payload)  # type: ignore[arg-type]


def search_page(outcome: SearchOutcome) -> CollectionResponse[TaskSearchRead]:
    """Итог поиска в страницу ответа: выбор полей берётся из разрешённого фильтра.

    Живёт здесь, а не в роутере, потому что то же преобразование понадобится любому
    второму входу в поиск: вычислять `fields` заново значило бы завести второе
    толкование того, что именно просил клиент.
    """
    return CollectionResponse[TaskSearchRead].of(
        [TaskSearchRead.of(found, fields=outcome.resolved.fields) for found in outcome.page.items],
        next_cursor=outcome.page.next_cursor,
    )
