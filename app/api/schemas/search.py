"""Схемы поиска задач: структурный фильтр, запрос и задача в выдаче.

## Почему у задачи в выдаче все поля необязательны

Поиск умеет отдавать подмножество полей (`fields`), и это не оптимизация, а требование:
полная задача на сто позиций съедает контекст агента целиком. Схема обязана честно это
показывать — поле, которого может не быть, в сгенерированном клиенте должно быть
необязательным. Маршрут отдаёт ответ с `response_model_exclude_unset`, поэтому
непрошенные поля не приезжают ни как `null`, ни как значение по умолчанию.

Без явного `fields` возвращается задача целиком — ровно в том же виде, в каком её
отдаёт чтение. Два разных представления одной задачи в одном API — то, чего проект не
допускает.

## Два способа задать отбор и один результат

`query` — строка на языке запросов, `filter` — структурный набор параметров. Их можно
сочетать: условия складываются по `and`. Значения структурного фильтра разбираются теми
же правилами, что и значения языка, поэтому `{"assignee": ["me()"]}` и `assignee: me()`
— это буквально один путь исполнения.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.api.schemas.common import CollectionResponse
from app.db.models.issue import Issue
from app.db.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MIN_PAGE_SIZE
from app.domain.catalogs import StatusCategory
from app.domain.issues import IssuePriority
from app.domain.search import MAX_QUERY_LENGTH, MAX_SORT_TERMS, Operator
from app.services.catalogs import format_entry_ref
from app.services.search import SearchOutcome, StructuredTerm

QueryDescription = (
    "Query language string, for example `queue: TRK and status: open and assignee: me() "
    "and deadline: <= today()`. Operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` "
    "(contains), `!~`, `in`, `not in`. Functions: `me()`, `today()`, `now()`, `empty()`, "
    "with day offsets such as `today() - 7d`. Combine with `and`, `or` and parentheses"
)
SortDescription = (
    "Sort keys, most significant first. A leading `-` sorts descending: `-deadline`. "
    "Sortable: created_at, updated_at, deadline, priority, summary and single-valued "
    "custom fields. The result is always tie-broken by issue id, so paging is stable"
)
FieldsDescription = (
    "Fields to return. Omit for the whole issue; pass a custom field reference "
    "(`TRK.severity`) to get only that entry of `values`. The issue key is always "
    "included"
)
MomentDescription = (
    "`YYYY-MM-DD`, ISO 8601 with a UTC offset, or a function: `today()`, `now()`, "
    "`today() - 7d`. A bare date covers the whole day"
)
ActorListDescription = "Actor keys; `me()` means the caller, `empty()` means not set"
CatalogListDescription = (
    "Catalog references: bare key for a global entry, `QUEUE.key` for a queue-local one"
)


class SearchTermInput(BaseModel):
    """Одно условие в каноническом виде — так, как его понимает поиск внутри.

    Форма нужна там, где условие надо сохранить и прочитать обратно неизменным: у
    сохранённого фильтра. Структурный фильтр `IssueFilterInput` удобнее для формы
    интерфейса, но обратно из него ничего не восстанавливается — он сводится к этому же
    списку условий.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(
        examples=["status", "TRK.severity"],
        description="System field name or custom field reference",
    )
    operator: Operator = Field(default=Operator.EQ, examples=[Operator.EQ])
    values: list[JsonValue] = Field(
        default_factory=list,
        examples=[["open", "in_progress"]],
        description=(
            "Values joined by `or`. A string goes through the query language value "
            "grammar, so `me()` and `today() - 7d` work here too; `null` means «no value»"
        ),
    )

    def to_term(self) -> StructuredTerm:
        return StructuredTerm(name=self.field, operator=self.operator, values=self.values)


class IssueFilterInput(BaseModel):
    """Структурный фильтр: параметры формы поиска.

    Значения одного параметра складываются по `or`, параметры между собой — по `and`.
    Это и есть смысл формы: сузить по каждому полю, приняв любое из отмеченных значений.

    Пустой список означает «не фильтровать по этому полю», а не «ничего не подходит»:
    иначе снятая галочка обнуляла бы выдачу.
    """

    model_config = ConfigDict(extra="forbid")

    queue: list[str] = Field(default_factory=list, examples=[["TRK"]])
    key: list[str] = Field(default_factory=list, examples=[["TRK-1", "TRK-2"]])
    issue_type: list[str] = Field(default_factory=list, description=CatalogListDescription)
    status: list[str] = Field(default_factory=list, description=CatalogListDescription)
    status_category: list[StatusCategory] = Field(
        default_factory=list,
        description="Machine meaning of the status; boards and reports rely on it",
    )
    resolution: list[str] = Field(
        default_factory=list,
        description=f"{CatalogListDescription}. `empty()` finds unresolved issues",
    )
    priority: list[IssuePriority] = Field(default_factory=list)
    author: list[str] = Field(default_factory=list, description=ActorListDescription)
    assignee: list[str] = Field(default_factory=list, description=ActorListDescription)
    followers: list[str] = Field(default_factory=list, description=ActorListDescription)
    tags: list[str] = Field(
        default_factory=list,
        examples=[["release"]],
        description=(
            "Tags, matched exactly. Canonical spellings come from `GET /api/v1/tags` — "
            "that dictionary is the single source of existing labels"
        ),
    )
    project: list[str] = Field(
        default_factory=list,
        examples=[["alpha"]],
        description="Project keys; `empty()` finds issues outside any project",
    )
    sprint: list[str] = Field(
        default_factory=list,
        examples=[["current"]],
        description=(
            "Sprint UUIDs, or the word `current` for whichever sprints are active now. "
            "`empty()` finds the backlog — issues outside any sprint"
        ),
    )
    summary: str | None = Field(default=None, description="Substring of the summary")
    description: str | None = Field(default=None, description="Substring of the description")
    text: str | None = Field(
        default=None,
        description="Substring of the summary, the description or any comment",
    )
    deadline_from: str | None = Field(default=None, description=MomentDescription)
    deadline_to: str | None = Field(default=None, description=MomentDescription)
    created_from: str | None = Field(default=None, description=MomentDescription)
    created_to: str | None = Field(default=None, description=MomentDescription)
    updated_from: str | None = Field(default=None, description=MomentDescription)
    updated_to: str | None = Field(default=None, description=MomentDescription)
    values: dict[str, JsonValue] = Field(
        default_factory=dict,
        examples=[{"TRK.severity": "critical"}],
        description=(
            "Custom field values keyed by field reference. A list means «any of», "
            "`null` means «no value»"
        ),
    )

    def to_terms(self) -> list[StructuredTerm]:
        """Структурный фильтр → канонические условия. Одно место перевода на весь API."""
        terms: list[StructuredTerm] = [
            StructuredTerm(name=name, values=values)
            for name, values in (
                ("queue", self.queue),
                ("key", self.key),
                ("issue_type", self.issue_type),
                ("status", self.status),
                ("status_category", [item.value for item in self.status_category]),
                ("resolution", self.resolution),
                ("priority", [item.value for item in self.priority]),
                ("author", self.author),
                ("assignee", self.assignee),
                ("followers", self.followers),
                ("tags", self.tags),
                ("project", self.project),
                ("sprint", self.sprint),
            )
            if values
        ]
        terms.extend(
            StructuredTerm(name=name, values=[value], operator=Operator.CONTAINS)
            for name, value in (
                ("summary", self.summary),
                ("description", self.description),
                ("text", self.text),
            )
            if value is not None
        )
        terms.extend(
            StructuredTerm(name=name, values=[value], operator=operator)
            for name, value, operator in (
                ("deadline", self.deadline_from, Operator.GTE),
                ("deadline", self.deadline_to, Operator.LTE),
                ("created_at", self.created_from, Operator.GTE),
                ("created_at", self.created_to, Operator.LTE),
                ("updated_at", self.updated_from, Operator.GTE),
                ("updated_at", self.updated_to, Operator.LTE),
            )
            if value is not None
        )
        terms.extend(
            StructuredTerm(
                name=reference,
                values=list(value) if isinstance(value, list) else [value],
            )
            for reference, value in self.values.items()
        )
        return terms


class IssueSearchRequest(BaseModel):
    """Тело запроса поиска. Все источники отбора складываются по `and`."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        max_length=MAX_QUERY_LENGTH,
        examples=["queue: TRK and status: open"],
        description=QueryDescription,
    )
    filter: IssueFilterInput | None = Field(default=None)
    saved_filter: uuid.UUID | None = Field(
        default=None,
        description="Run a saved filter and narrow it further with `query` and `filter`",
    )
    sort: list[str] = Field(
        default_factory=list,
        max_length=MAX_SORT_TERMS,
        examples=[["-deadline"]],
        description=SortDescription,
    )
    fields: list[str] = Field(
        default_factory=list,
        examples=[["key", "summary", "status"]],
        description=FieldsDescription,
    )
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=MIN_PAGE_SIZE, le=MAX_PAGE_SIZE)
    cursor: str | None = Field(
        default=None,
        description="Cursor from `meta.next_cursor` of a previous page",
    )


class IssueSearchRead(BaseModel):
    """Задача в выдаче поиска. Приезжают только запрошенные поля.

    Ключ приходит всегда: выдача без него бесполезна — по ней нельзя ни прочитать
    задачу, ни сослаться на неё.
    """

    key: str = Field(examples=["TRK-123"], description="Immutable and never reused")
    id: uuid.UUID | None = None
    queue: str | None = Field(default=None, examples=["TRK"])
    issue_type: str | None = Field(default=None, examples=["bug"])
    status: str | None = Field(default=None, examples=["open"])
    resolution: str | None = Field(default=None, examples=["done"])
    priority: IssuePriority | None = None
    summary: str | None = None
    description: str | None = None
    author: str | None = Field(default=None, examples=["alice"])
    assignee: str | None = Field(default=None, examples=["alice"])
    followers: list[str] | None = None
    deadline: datetime | None = None
    tags: list[str] | None = None
    project: str | None = Field(default=None, examples=["alpha"])
    sprint: uuid.UUID | None = None
    values: dict[str, JsonValue] | None = None
    version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def of(
        cls,
        issue: Issue,
        *,
        fields: tuple[str, ...] = (),
        value_refs: tuple[str, ...] = (),
    ) -> IssueSearchRead:
        """Задача в выдаче. Пустой набор полей означает «всё», как при чтении задачи."""
        payload = {
            "id": issue.id,
            "key": issue.key,
            "queue": issue.queue.key,
            "issue_type": format_entry_ref(issue.issue_type),
            "status": format_entry_ref(issue.status),
            "resolution": (
                None if issue.resolution is None else format_entry_ref(issue.resolution)
            ),
            "priority": issue.priority,
            "summary": issue.summary,
            "description": issue.description,
            "author": issue.author.key,
            "assignee": None if issue.assignee is None else issue.assignee.key,
            "followers": [follower.key for follower in issue.followers],
            "deadline": issue.deadline,
            "tags": list(issue.tags),
            "project": None if issue.project is None else issue.project.key,
            "sprint": issue.sprint_id,
            "values": _selected_values(issue, value_refs),
            "version": issue.version,
            "created_at": issue.created_at,
            "updated_at": issue.updated_at,
        }
        if fields:
            payload = {name: value for name, value in payload.items() if name in fields}
        return cls(**payload)


def _selected_values(issue: Issue, value_refs: tuple[str, ...]) -> dict[str, JsonValue]:
    """Значения кастомных полей: все либо только названные ссылками в `fields`."""
    if not value_refs:
        return issue.values
    return {ref: issue.values[ref] for ref in value_refs if ref in issue.values}


def search_page(outcome: SearchOutcome) -> CollectionResponse[IssueSearchRead]:
    """Итог поиска в страницу ответа: выбор полей берётся из разрешённого фильтра.

    Живёт здесь, а не в роутере поиска, потому что страницу собирают два маршрута —
    общий поиск и список задач проекта. Вычислять `fields` второй раз в каждом из них
    значило бы завести второе толкование того, что именно просил клиент.
    """
    return CollectionResponse[IssueSearchRead].of(
        [
            IssueSearchRead.of(
                issue,
                fields=outcome.resolved.fields,
                value_refs=outcome.resolved.value_refs,
            )
            for issue in outcome.page.items
        ],
        next_cursor=outcome.page.next_cursor,
    )
